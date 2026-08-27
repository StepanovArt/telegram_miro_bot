import datetime
import json
import logging
import os
import tempfile
import time
import urllib.parse
from collections import defaultdict, deque
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler,
    MessageHandler, filters, ContextTypes,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Конфиг — падаем сразу, если что-то не задано
# ---------------------------------------------------------------------------

def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(f"[FATAL] {name} не задан в .env")
    return val


TG_TOKEN       = _require("TG_TOKEN")
MIRO_TOKEN     = _require("MIRO_TOKEN")
MIRO_BOARD_ID  = _require("MIRO_BOARD_ID")
GEMINI_API_KEY = _require("GEMINI_API_KEY")
NOTION_TOKEN   = _require("NOTION_TOKEN")
_raw_page_id   = _require("NOTION_PAGE_ID").replace("-", "")
if len(_raw_page_id) != 32:
    raise SystemExit(f"[FATAL] NOTION_PAGE_ID должен быть 32 символа, получено {len(_raw_page_id)}")
NOTION_PAGE_ID = f"{_raw_page_id[:8]}-{_raw_page_id[8:12]}-{_raw_page_id[12:16]}-{_raw_page_id[16:20]}-{_raw_page_id[20:]}"

_raw_ids = os.environ.get("ALLOWED_USER_IDS", "").strip()
if not _raw_ids:
    raise SystemExit("[FATAL] ALLOWED_USER_IDS не задан — бот не стартует")
try:
    ALLOWED_USER_IDS = [int(x.strip()) for x in _raw_ids.split(",") if x.strip()]
except ValueError:
    raise SystemExit("[FATAL] ALLOWED_USER_IDS содержит невалидные значения (нужны числа через запятую)")
if not ALLOWED_USER_IDS:
    raise SystemExit("[FATAL] ALLOWED_USER_IDS пуст — бот не стартует")

# ---------------------------------------------------------------------------
# Состояние: режим + дата последнего заголовка дневника
# ---------------------------------------------------------------------------

STATE_FILE = Path("state.json")


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def _get_mode() -> str:
    return _load_state().get("mode", "miro")


def _set_mode(mode: str) -> None:
    state = _load_state()
    state["mode"] = mode
    _save_state(state)

# ---------------------------------------------------------------------------
# Rate limiting: не более 60 сообщений в час
# ---------------------------------------------------------------------------

_RATE_LIMIT = 60
_message_times: dict[int, deque] = defaultdict(deque)


def _check_rate(user_id: int) -> bool:
    now = time.monotonic()
    dq = _message_times[user_id]
    while dq and now - dq[0] > 3600:
        dq.popleft()
    if len(dq) >= _RATE_LIMIT:
        return False
    dq.append(now)
    return True

# ---------------------------------------------------------------------------
# Miro
# ---------------------------------------------------------------------------

def _create_sticky(text: str) -> None:
    board = urllib.parse.quote(MIRO_BOARD_ID, safe="")
    url = f"https://api.miro.com/v2/boards/{board}/sticky_notes"

    now = datetime.datetime.now()
    seconds_today = now.hour * 3600 + now.minute * 60 + now.second
    y = seconds_today / 30
    x = -2000 + (now.second - 30) * 5  # ±150 от центра на основе секунды

    resp = requests.post(
        url,
        json={
            "data":     {"content": text, "shape": "square"},
            "style":    {"fillColor": "light_yellow"},
            "position": {"x": x, "y": y},
        },
        headers={
            "Authorization": f"Bearer {MIRO_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f"Miro вернул {resp.status_code}: {resp.text[:300]}")

# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

_MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _today_label() -> str:
    d = datetime.date.today()
    return f"{d.day} {_MONTHS_RU[d.month - 1]} {d.year}"


def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _append_blocks(children: list) -> None:
    url = f"https://api.notion.com/v1/blocks/{NOTION_PAGE_ID}/children"
    resp = requests.patch(url, headers=_notion_headers(), json={"children": children}, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"Notion вернул {resp.status_code}: {resp.text[:300]}")


def _append_diary_entry(text: str) -> None:
    state = _load_state()
    today = str(datetime.date.today())

    if state.get("last_heading_date") != today:
        _append_blocks([{
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": _today_label()}}]},
        }])
        state["last_heading_date"] = today
        _save_state(state)

    _append_blocks([{
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }])

# ---------------------------------------------------------------------------
# Gemini — транскрипция аудио
# ---------------------------------------------------------------------------

def _transcribe(audio_path: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"),
            (
                "Transcribe this audio. Return ONLY the transcription as a single "
                "short line suitable for a sticky note. No preamble, no quotes, "
                "no formatting. If the audio contains a task, phrase it as a task."
            ),
        ],
    )
    return response.text.strip()

# ---------------------------------------------------------------------------
# Скачивание голосового из Telegram (два шага)
# ---------------------------------------------------------------------------

async def _download_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    tg_file = await context.bot.get_file(update.message.voice.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    tmp.close()
    await tg_file.download_to_drive(tmp.name)
    return tmp.name

# ---------------------------------------------------------------------------
# Хендлеры
# ---------------------------------------------------------------------------

_KEYBOARD = ReplyKeyboardMarkup(
    [["📋 Miro", "📓 Notion"]],
    resize_keyboard=True,
    is_persistent=True,
)
_MODE_BY_LABEL = {"📋 Miro": "miro", "📓 Notion": "notion"}


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mode = _get_mode()
    label = "📋 Miro" if mode == "miro" else "📓 Notion"
    await update.message.reply_text(f"Режим: {label}", reply_markup=_KEYBOARD)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    # Переключение режима по кнопке клавиатуры
    if update.message.text in _MODE_BY_LABEL:
        mode = _MODE_BY_LABEL[update.message.text]
        _set_mode(mode)
        label = "📋 Miro" if mode == "miro" else "📓 Notion"
        await update.message.reply_text(f"Режим: {label}", reply_markup=_KEYBOARD)
        return

    if not _check_rate(user.id):
        await update.message.reply_text("⚠️ Не долетело: слишком много сообщений, подожди немного (лимит 60/час)")
        return

    try:
        if update.message.voice:
            audio_path = await _download_voice(update, context)
            try:
                text = _transcribe(audio_path)
                log.info("voice transcribed user=%s: %.80s", user.id, text)
            except Exception as e:
                log.warning("transcription failed user=%s: %s", user.id, e)
                text = "🎤 голосовое, транскрипция не удалась"
            finally:
                os.unlink(audio_path)
        else:
            text = update.message.text

        mode = _get_mode()
        if mode == "notion":
            _append_diary_entry(text)
            await update.message.reply_text("📓 В дневник", reply_markup=_KEYBOARD)
        else:
            _create_sticky(text)
            await update.message.reply_text("📌 На доске", reply_markup=_KEYBOARD)

        log.info("entry created mode=%s user=%s: %.80s", mode, user.id, text)

    except Exception as e:
        log.exception("entry creation failed user=%s", user.id)
        await update.message.reply_text(f"⚠️ Не долетело: {e}")

# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def main() -> None:
    app = Application.builder().token(TG_TOKEN).build()
    user_filter = filters.User(user_id=ALLOWED_USER_IDS)

    app.add_handler(CommandHandler("start", handle_start, filters=user_filter))
    app.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND | filters.VOICE) & user_filter,
        handle_message,
    ))

    log.info("bot starting, allowed_users=%s", ALLOWED_USER_IDS)
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()

# Telegram → Miro Inbox Bot

Личный бот для быстрого захвата мыслей и задач. Пишешь текст или наговариваешь голосовое — бот создаёт стикер в зоне высадки на доске Miro. Вечером расставляешь стикеры по календарю руками.

## Как работает

- **Текст** → стикер на доске
- **Голосовое** → транскрипция через Gemini → стикер на доске
- Стикеры появляются в зоне `x = -2000`, позиция по вертикали зависит от времени суток (утренние выше, вечерние ниже)
- Чужие сообщения игнорируются (whitelist по user_id)
- Rate limit: 60 сообщений в час

## Требования

- Python 3.11+
- Токены: Telegram Bot, Miro, Gemini

## Установка и запуск локально

```bash
git clone https://github.com/StepanovArt/telegram_miro_bot.git
cd telegram_miro_bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# заполни .env своими токенами

python bot.py
```

## Переменные окружения

| Переменная | Описание |
|---|---|
| `TG_TOKEN` | Токен бота от [@BotFather](https://t.me/BotFather) |
| `MIRO_TOKEN` | OAuth-токен приложения Miro |
| `MIRO_BOARD_ID` | ID доски из URL (`/board/<ID>/`) |
| `GEMINI_API_KEY` | API-ключ Google Gemini |
| `ALLOWED_USER_IDS` | Твой Telegram user_id (узнать: [@userinfobot](https://t.me/userinfobot)) |

### Где взять токены

**TG_TOKEN** — создай бота через [@BotFather](https://t.me/BotFather), команда `/newbot`

**MIRO_TOKEN** — [miro.com/app/settings/user-profile/apps](https://miro.com/app/settings/user-profile/apps) → Create new app → Permissions: `boards:read` + `boards:write` → Install app and get OAuth token

**MIRO_BOARD_ID** — из URL доски: `miro.com/app/board/**uXjVNxxxxxxx=**/`  
Знак `=` в конце — часть ID, не обрезай

**GEMINI_API_KEY** — [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## Деплой на VPS (systemd)

```bash
# Загрузи файлы на сервер
scp -r . user@your-server:~/telegram_miro_bot/

# На сервере
cd ~/telegram_miro_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # заполни токены

# Установи systemd unit
sudo cp telegram-bot-miro.service /etc/systemd/system/
# Отредактируй YOUR_USER в файле юнита
sudo nano /etc/systemd/system/telegram-bot-miro.service

sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot-miro

# Логи
sudo journalctl -u telegram-bot-miro -f
```

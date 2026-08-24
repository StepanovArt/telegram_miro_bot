# Telegram → Miro Inbox Bot

A personal quick-capture bot. Send a text or voice message — the bot creates a sticky note in your Miro landing zone. In the evening, drag the stickers to their places on your calendar board manually.

## How It Works

- **Text** → sticky note on the board
- **Voice** → transcribed via Gemini → sticky note on the board
- Stickers land at `x = -2000`, vertical position depends on time of day (morning stickers higher, evening lower)
- Messages from unknown users are silently ignored (user_id whitelist)
- Rate limit: 60 messages per hour

## Requirements

- Python 3.11+
- Tokens: Telegram Bot, Miro, Gemini

## Local Setup

```bash
git clone https://github.com/StepanovArt/telegram_miro_bot.git
cd telegram_miro_bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in your tokens

python bot.py
```

## Environment Variables

| Variable | Description |
|---|---|
| `TG_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `MIRO_TOKEN` | Miro app OAuth token |
| `MIRO_BOARD_ID` | Board ID from the URL (`/board/<ID>/`) |
| `GEMINI_API_KEY` | Google Gemini API key |
| `ALLOWED_USER_IDS` | Your Telegram user ID (get it from [@userinfobot](https://t.me/userinfobot)) |

### Where to Get the Tokens

**TG_TOKEN** — create a bot via [@BotFather](https://t.me/BotFather), command `/newbot`

**MIRO_TOKEN** — [miro.com/app/settings/user-profile/apps](https://miro.com/app/settings/user-profile/apps) → Create new app → Permissions: `boards:read` + `boards:write` → Install app and get OAuth token

**MIRO_BOARD_ID** — from the board URL: `miro.com/app/board/**uXjVNxxxxxxx=**/`
The trailing `=` is part of the ID, don't cut it off

**GEMINI_API_KEY** — [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## Limits

| Service | Limit |
|---|---|
| Bot (built-in) | 60 messages / hour |
| Gemini free tier | 1 500 voice transcriptions / day, 15 / min |
| Miro API | 300 requests / min |
| Telegram | No real limits for personal bots |

For personal daily capture, you'll never hit any of these.

## Deploy to VPS (systemd)

```bash
# Upload files to the server
scp -r . user@your-server:~/telegram_miro_bot/

# On the server
cd ~/telegram_miro_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # fill in your tokens

# Install systemd unit
sudo cp telegram-bot-miro.service /etc/systemd/system/
sudo nano /etc/systemd/system/telegram-bot-miro.service  # replace YOUR_USER

sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot-miro

# Logs
sudo journalctl -u telegram-bot-miro -f
```

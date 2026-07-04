# AI Office Assistant Discord Bot

A hackathon-ready Discord bot that gives the IUT office monitoring system a friendly conversational interface. The bot uses OpenAI for natural language replies, remembers short per-user context, and connects to the office dashboard backend over WebSocket for live device status and control.

This repository contains the Python Discord bot component. The dashboard and office simulation server live in the IUT Hackathon project and expose `ws://localhost:3001/ws`.

## What It Does

- Answers in Discord DMs or when mentioned in a server channel.
- Ignores unrelated server messages to reduce noise and API usage.
- Uses OpenAI's Responses API for natural language generation.
- Connects to the IUT Hackathon office server over WebSocket.
- Keeps short in-memory conversation history per Discord user.
- Supports live office commands: status, usage, room view, toggle, presets, and auto simulation.
- Can post live office alerts to a configured Discord channel.
- Responds in a warm office-assistant tone.
- Loads secrets from a local `.env` file that is not committed.

## Demo Flow

1. DM the bot: `Can you help me summarize office status updates?`
2. Ask a follow-up: `Make that shorter for the team channel.`
3. Mention the bot in a server: `@OfficeBot what can you do right now?`
4. Ask for live state: `@OfficeBot what is the office status?`
5. Run `!toggle drawing-fan-1` and watch the dashboard update through WebSocket.
6. Run `!preset room_stuck` to trigger a hackathon-friendly alert scenario.

## Architecture

```text
Discord message
    -> bot.py routing and mention/DM filtering
    -> office_ws.py live WebSocket snapshot and commands
    -> ConversationManager rolling user history
    -> OpenAI Responses API
    -> chunked Discord reply
```

The code is intentionally small for hackathon review. Each module has one clear responsibility:

```text
bot.py             Discord client, message routing, typing indicator, reply chunking
config.py          .env loading, required secret validation, typed settings
conversation.py    System prompt and per-user in-memory conversation history
office_ws.py       IUT Hackathon WebSocket client, snapshot formatting, commands
openai_client.py   OpenAI Responses API wrapper and graceful API error fallback
requirements.txt   Python dependencies
.env.example       Safe environment variable template
.gitignore         Local secrets, virtualenvs, and generated files excluded from Git
```

## Requirements

- Python 3.11+
- Discord bot token
- OpenAI API key

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your local environment file:

```bash
cp .env.example .env
```

Edit `.env`:

```text
DISCORD_TOKEN=your-discord-bot-token
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-5.4-mini
MAX_HISTORY_MESSAGES=12
OFFICE_WS_URL=ws://localhost:3001/ws
OFFICE_ALERT_CHANNEL_ID=
OFFICE_AFTER_HOURS_ALERTS=true
OFFICE_ALERT_HOUR=21
OFFICE_ALERT_REPEAT_MINUTES=30
```

## Run the Office Server

The bot expects the IUT Hackathon office server to be running separately:

```bash
git clone https://github.com/itzMRZ/IUT_Hackathon.git
cd IUT_Hackathon
npm install
npm run server
```

That starts:

- REST API: `http://localhost:3001`
- WebSocket: `ws://localhost:3001/ws`

The dashboard can also be started with `npm run dev`, but the bot only needs the WebSocket server.

## Discord Bot Setup

In the Discord Developer Portal:

1. Create or select an application.
2. Add a bot user.
3. Enable the Message Content Intent.
4. Invite the bot to your server with permission to read messages and send messages.
5. Mention the bot in a server channel, or send it a DM.

## Run

```bash
python bot.py
```

When the bot connects, the terminal logs the Discord account name and ID.

## Discord Commands

Commands work in DMs or when the bot is mentioned in a server channel:

| Command | Description |
| --- | --- |
| `!help` | Show command list. |
| `!status` | Summarize all rooms from the latest WebSocket snapshot. |
| `!usage` | Show total and per-room wattage. |
| `!room drawing` | Show each device in one room. |
| `!toggle drawing-fan-1` | Send a WebSocket toggle command for a device. |
| `!preset room_stuck` | Apply a backend demo preset. |
| `!autosim off` | Enable or disable backend simulation ticks. |

Supported rooms: `drawing`, `workroom1`, `workroom2`.

Supported presets: `office_busy`, `after_hours`, `room_stuck`, `drawing_only`, `all_off`.

Natural-language controls also work when the user mentions a specific room,
device type, device number, and state. The bot uses OpenAI to parse these
requests, so equivalent phrasing in other languages can map to the same safe
WebSocket command:

```text
@Abbas turn Drawing Room fan 1 on
@Abbas drawing room light 2 off
@Abbas work room 2 fan 2 bondho kore dao
```

For safety, ambiguous requests fall back to a normal assistant reply instead
of guessing the device.

## Verification

Compile the source files:

```bash
python -m py_compile bot.py config.py conversation.py openai_client.py office_ws.py
```

Manual smoke test:

1. DM the bot and confirm it replies.
2. Ask a follow-up question and confirm it remembers the previous turn.
3. Mention the bot in a server channel and confirm it replies.
4. Start the IUT office server and run `!status`.
5. Run `!toggle drawing-fan-1` and confirm the dashboard updates.
6. Send an unmentioned message in a server channel and confirm it stays quiet.

## Configuration

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | Yes | None | Discord bot token from the Developer Portal. |
| `OPENAI_API_KEY` | Yes | None | OpenAI API key used by the Responses API client. |
| `OPENAI_MODEL` | No | `gpt-5.4-mini` | Model used for replies. |
| `MAX_HISTORY_MESSAGES` | No | `12` | Number of recent user/assistant messages kept per user. |
| `OFFICE_WS_URL` | No | `ws://localhost:3001/ws` | IUT Hackathon office server WebSocket URL. |
| `OFFICE_ALERT_CHANNEL_ID` | No | None | Discord channel ID for live alert posts. |
| `OFFICE_AFTER_HOURS_ALERTS` | No | `true` | Enables reminders for devices still on after the configured hour. |
| `OFFICE_ALERT_HOUR` | No | `21` | Local-hour threshold for after-hours reminders. |
| `OFFICE_ALERT_REPEAT_MINUTES` | No | `30` | Reminder repeat interval when the same devices remain on. |

## Troubleshooting

- `Missing required environment variable`: create `.env` and fill in the required keys.
- Bot does not respond in server: mention the bot directly or DM it.
- Bot still does not respond: confirm Message Content Intent is enabled in the Discord Developer Portal.
- Discord login fails: verify the bot token and invite permissions.
- OpenAI replies fail: verify `OPENAI_API_KEY`, billing/access, and the configured model.
- `!status` says WebSocket is not connected: start the IUT server with `npm run server` and verify `OFFICE_WS_URL`.
- Toggle commands do nothing: confirm the backend terminal says `WebSocket: ws://localhost:3001/ws`.
- After-hours reminders do not appear: set `OFFICE_ALERT_CHANNEL_ID`, or interact with the bot once in the channel you want it to use.
- Certificate errors on macOS: activate the virtual environment and ensure dependencies are installed; `certifi` is installed through the OpenAI dependency chain.

## Security Notes

- Never commit `.env`.
- `.env.example` must contain placeholders only.
- If real credentials were ever pasted into `.env.example` or pushed to GitHub, rotate both the Discord token and OpenAI API key immediately.
- The bot currently stores conversation history only in process memory; restarting the bot clears it.

## Roadmap

- Add OpenAI tool/function calling so natural language requests can safely trigger WebSocket actions.
- Add slash commands as deterministic fallbacks.
- Phase 3: add proactive alerts for office anomalies.
- Phase 3: add scheduled polling with `discord.ext.tasks`.

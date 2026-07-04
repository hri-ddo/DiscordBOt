# AI Office Assistant Discord Bot

A hackathon-ready Discord bot that gives an office monitoring system a friendly conversational interface. The bot uses OpenAI for natural language replies, remembers short per-user context, and avoids robotic data dumps while the hardware-control layer is still being built.

This repository contains Phase 1: the Discord and AI foundation. Live sensor readings, device control, proactive alerts, and backend hardware integration are planned for later phases.

## What It Does

- Answers in Discord DMs or when mentioned in a server channel.
- Ignores unrelated server messages to reduce noise and API usage.
- Uses OpenAI's Responses API for natural language generation.
- Keeps short in-memory conversation history per Discord user.
- Responds in a warm office-assistant tone.
- Clearly says when hardware status or control is not available yet.
- Loads secrets from a local `.env` file that is not committed.

## Demo Flow

1. DM the bot: `Can you help me summarize office status updates?`
2. Ask a follow-up: `Make that shorter for the team channel.`
3. Mention the bot in a server: `@OfficeBot what can you do right now?`
4. Ask for hardware control: `Turn off the drawing room lights.`
5. The bot should explain that hardware integration is not connected yet instead of pretending the action succeeded.

## Architecture

```text
Discord message
    -> bot.py routing and mention/DM filtering
    -> ConversationManager rolling user history
    -> OpenAI Responses API
    -> chunked Discord reply
```

The code is intentionally small for hackathon review. Each module has one clear responsibility:

```text
bot.py             Discord client, message routing, typing indicator, reply chunking
config.py          .env loading, required secret validation, typed settings
conversation.py    System prompt and per-user in-memory conversation history
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
```

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

## Verification

Compile the source files:

```bash
python -m py_compile bot.py config.py conversation.py openai_client.py
```

Manual smoke test:

1. DM the bot and confirm it replies.
2. Ask a follow-up question and confirm it remembers the previous turn.
3. Mention the bot in a server channel and confirm it replies.
4. Send an unmentioned message in a server channel and confirm it stays quiet.

## Configuration

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | Yes | None | Discord bot token from the Developer Portal. |
| `OPENAI_API_KEY` | Yes | None | OpenAI API key used by the Responses API client. |
| `OPENAI_MODEL` | No | `gpt-5.4-mini` | Model used for replies. |
| `MAX_HISTORY_MESSAGES` | No | `12` | Number of recent user/assistant messages kept per user. |

## Troubleshooting

- `Missing required environment variable`: create `.env` and fill in the required keys.
- Bot does not respond in server: mention the bot directly or DM it.
- Bot still does not respond: confirm Message Content Intent is enabled in the Discord Developer Portal.
- Discord login fails: verify the bot token and invite permissions.
- OpenAI replies fail: verify `OPENAI_API_KEY`, billing/access, and the configured model.
- Certificate errors on macOS: activate the virtual environment and ensure dependencies are installed; `certifi` is installed through the OpenAI dependency chain.

## Security Notes

- Never commit `.env`.
- `.env.example` must contain placeholders only.
- If real credentials were ever pasted into `.env.example` or pushed to GitHub, rotate both the Discord token and OpenAI API key immediately.
- The bot currently stores conversation history only in process memory; restarting the bot clears it.

## Roadmap

- Phase 2: connect to a backend service for simulated office hardware status.
- Phase 2: add tool/function calling so natural language requests can map to safe hardware actions.
- Phase 2: add slash or prefix commands as deterministic fallbacks.
- Phase 3: add proactive alerts for office anomalies.
- Phase 3: add scheduled polling with `discord.ext.tasks`.

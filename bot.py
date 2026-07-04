"""Discord entry point for the AI Office Assistant."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

import discord

from config import ConfigError, load_settings
from conversation import ConversationManager, normalize_message
from office_ws import OfficeWebSocketClient, normalize_preset, parse_bool
from openai_client import OpenAIClient


DISCORD_MESSAGE_LIMIT = 2000
SAFE_MESSAGE_LIMIT = 1900

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def strip_bot_mention(content: str, bot_user_id: int) -> str:
    """Remove this bot's mention token from a Discord message."""

    mention_pattern = re.compile(rf"<@!?{bot_user_id}>")
    return normalize_message(mention_pattern.sub("", content))


def chunk_discord_message(
    content: str,
    limit: int = SAFE_MESSAGE_LIMIT,
) -> list[str]:
    """Split long content into chunks that fit Discord's message limit."""

    normalized = content.strip()
    if not normalized:
        return []

    if limit > DISCORD_MESSAGE_LIMIT:
        raise ValueError("limit cannot exceed Discord's 2000-character limit.")

    chunks: list[str] = []
    remaining = normalized

    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit

        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def should_respond(message: discord.Message, bot_user: discord.ClientUser) -> bool:
    if message.author.bot:
        return False

    # DMs are intentional conversations; server channels require a direct mention.
    if message.guild is None:
        return True

    return bot_user in message.mentions


async def send_chunks(
    destination: discord.abc.Messageable,
    chunks: Iterable[str],
) -> None:
    for chunk in chunks:
        await destination.send(chunk)


def build_help_text() -> str:
    return "\n".join(
        [
            "Office commands:",
            "`!status` - room summary from the live WebSocket snapshot",
            "`!usage` - total and per-room wattage",
            "`!room <drawing|workroom1|workroom2>` - device list for one room",
            "`!toggle <deviceId>` - toggle a device, e.g. `drawing-fan-1`",
            "`!preset <office_busy|after_hours|room_stuck|drawing_only|all_off>`",
            "`!autosim <on|off>` - enable or disable simulation ticks",
            "",
            "You can also mention me or DM me with natural language questions.",
        ]
    )


async def handle_office_command(
    text: str,
    office_client: OfficeWebSocketClient,
) -> str | None:
    if not text.startswith("!"):
        return None

    command, _, rest = text[1:].partition(" ")
    command = command.lower().strip()
    rest = rest.strip()

    if command in {"help", "office"}:
        return build_help_text()

    if command == "status":
        return office_client.format_status()

    if command == "usage":
        return office_client.format_usage()

    if command == "room":
        if not rest:
            return 'Usage: `!room drawing` (also supports `workroom1` and `workroom2`).'
        return office_client.format_room(rest)

    if command == "toggle":
        if not rest:
            return "Usage: `!toggle drawing-fan-1`"
        sent = await office_client.send_toggle(rest)
        if not sent:
            return "The office WebSocket is not connected, so I could not toggle that device."
        return f"Sent toggle command for `{rest}` over WebSocket."

    if command == "preset":
        preset = normalize_preset(rest)
        if not preset:
            return (
                "Usage: `!preset office_busy` "
                "(office_busy, after_hours, room_stuck, drawing_only, all_off)."
            )
        sent = await office_client.send_preset(preset)
        if not sent:
            return "The office WebSocket is not connected, so I could not apply that preset."
        return f"Sent preset command `{preset}` over WebSocket."

    if command == "autosim":
        enabled = parse_bool(rest)
        if enabled is None:
            return "Usage: `!autosim on` or `!autosim off`"
        sent = await office_client.send_autosim(enabled)
        if not sent:
            return "The office WebSocket is not connected, so I could not update auto simulation."
        return f"Sent auto simulation command: `{enabled}`."

    return None


async def handle_natural_control_intent(
    text: str,
    office_client: OfficeWebSocketClient,
) -> str | None:
    normalized = normalize_message(text.lower())

    wants_off = "off" in normalized and any(
        phrase in normalized
        for phrase in (
            "turn off",
            "turn all",
            "switch off",
            "shut off",
            "make it off",
            "make them off",
            "all of them off",
        )
    )
    mentions_lights = "light" in normalized or "all of them off" in normalized
    if not wants_off or not mentions_lights:
        return None

    if not office_client.is_ready():
        return "The office WebSocket is not connected, so I could not turn the lights off."

    on_lights = office_client.on_device_ids("light")
    if not on_lights:
        return "All lights are already off."

    toggled = await office_client.turn_off_on_devices("light")
    if not toggled:
        return "The office WebSocket is not connected, so I could not turn the lights off."

    return "Turned off these lights: " + ", ".join(f"`{device_id}`" for device_id in toggled)


def create_bot() -> discord.Client:
    settings = load_settings()

    intents = discord.Intents.default()
    # Required so the bot can read mentions and user text in Discord messages.
    intents.message_content = True

    bot = discord.Client(intents=intents)
    conversations = ConversationManager(settings.max_history_messages)
    office_client = OfficeWebSocketClient(settings.office_ws_url)
    ai_client = OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    async def post_alert(alert: dict[str, object]) -> None:
        if not settings.office_alert_channel_id:
            return

        channel = bot.get_channel(settings.office_alert_channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(settings.office_alert_channel_id)
            except discord.DiscordException:
                logger.exception(
                    "Could not fetch alert channel %s",
                    settings.office_alert_channel_id,
                )
                return

        if isinstance(channel, discord.abc.Messageable):
            await channel.send(f"Office alert: {office_client.format_alert(alert)}")

    @bot.event
    async def on_ready() -> None:
        logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")
        office_client.start(post_alert)

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if bot.user is None or not should_respond(message, bot.user):
            return

        user_id = message.author.id
        user_message = message.content
        if message.guild is not None:
            user_message = strip_bot_mention(user_message, bot.user.id)
        else:
            user_message = normalize_message(user_message)

        command_reply = await handle_office_command(user_message, office_client)
        if command_reply is not None:
            await send_chunks(message.channel, chunk_discord_message(command_reply))
            return

        control_reply = await handle_natural_control_intent(user_message, office_client)
        if control_reply is not None:
            await send_chunks(message.channel, chunk_discord_message(control_reply))
            return

        history = conversations.get_history(user_id)

        async with message.channel.typing():
            reply = await ai_client.generate_reply(
                user_id,
                user_message,
                history,
                office_client.context_for_ai(),
            )

        if user_message:
            conversations.append_user_message(user_id, user_message)
        conversations.append_assistant_message(user_id, reply)

        chunks = chunk_discord_message(reply)
        if not chunks:
            chunks = ["I am here, but I did not get a reply ready. Try me again?"]

        await send_chunks(message.channel, chunks)

    bot.run(settings.discord_token)
    return bot


if __name__ == "__main__":
    try:
        create_bot()
    except KeyboardInterrupt:
        raise SystemExit(0)
    except ConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

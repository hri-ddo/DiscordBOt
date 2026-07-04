"""Discord entry point for the AI Office Assistant."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

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

    off_action_phrases = (
        "turn off",
        "turn that off",
        "switch off",
        "shut off",
        "make it off",
        "make them off",
        "all of them off",
    )
    on_action_phrases = (
        "turn on",
        "turn that on",
        "switch on",
        "make it on",
        "make them on",
        "all of them on",
    )
    action_phrases = (
        "turn all",
        *off_action_phrases,
        *on_action_phrases,
    )
    is_control_request = any(phrase in normalized for phrase in action_phrases) or (
        "turn" in normalized and ("off" in normalized or "on" in normalized)
    )
    wants_off = any(phrase in normalized for phrase in off_action_phrases) or (
        "turn" in normalized and "off" in normalized
    )
    wants_on = any(phrase in normalized for phrase in on_action_phrases) or (
        "turn" in normalized and " on" in normalized and not wants_off
    )
    device_type = parse_device_type(normalized)
    if device_type is None or (wants_off == wants_on):
        return None

    target_status = "off" if wants_off else "on"
    opposite_status = "on" if target_status == "off" else "off"

    if not office_client.is_ready():
        return (
            "The office WebSocket is not connected, so I could not turn the "
            f"{device_type}s {target_status}."
        )

    targets = office_client.device_ids_by_status(opposite_status, device_type)
    if not targets:
        return f"All {device_type}s are already {target_status}."

    toggled = await office_client.set_devices_status(target_status, device_type)
    if not toggled:
        return (
            "The office WebSocket is not connected, so I could not turn the "
            f"{device_type}s {target_status}."
        )

    return f"Done. {office_client.format_room_summary()}"


def parse_device_type(normalized_text: str) -> str | None:
    has_light = "light" in normalized_text
    has_fan = "fan" in normalized_text
    if has_light == has_fan:
        return None
    return "light" if has_light else "fan"


async def handle_ai_control_intent(
    text: str,
    office_client: OfficeWebSocketClient,
    ai_client: OpenAIClient,
) -> str | None:
    if not office_client.is_ready():
        return None

    intent = await ai_client.parse_control_intent(text, office_client.device_ids())
    if not intent or intent.get("action") == "none":
        return None

    action = intent.get("action")
    room = intent.get("room")
    device_type = intent.get("device_type")
    status = intent.get("status")

    if device_type not in {"fan", "light"} or status not in {"on", "off"}:
        return None

    if action == "set_device":
        device_number = intent.get("device_number")
        if room not in {"drawing", "workroom1", "workroom2"}:
            return None
        if not isinstance(device_number, int):
            return None

        device_id = office_client.resolve_device_id(room, device_type, device_number)
        if not device_id:
            return "I could not find that exact office device."

        device = office_client.device_by_id(device_id)
        if device and device.get("status") == status:
            return f"{office_client.describe_device(device_id)} is already {status}."

        sent = await office_client.set_device_status(device_id, status)
        if not sent:
            return "The office WebSocket is not connected, so I could not control that device."

        return f"Done. {office_client.format_room_summary(room)}"

    if action == "set_group":
        room_id = room if room in {"drawing", "workroom1", "workroom2"} else None
        targets = office_client.device_ids_by_status(
            "off" if status == "on" else "on",
            device_type,
            room_id,
        )
        if not targets:
            scope = f" in {room_id}" if room_id else ""
            return f"All {device_type}s{scope} are already {status}."

        toggled = await office_client.set_devices_status(status, device_type, room_id)
        return f"Done. {office_client.format_room_summary(room_id)}"

    return None


def format_after_hours_message(on_devices: list[dict[str, Any]], alert_hour: int) -> str:
    room_labels = {
        "drawing": "Drawing Room",
        "workroom1": "Work Room 1",
        "workroom2": "Work Room 2",
    }
    device_lines = []
    for device in on_devices:
        room = str(device.get("room"))
        room_label = room_labels.get(room, room)
        device_lines.append(
            f"- {room_label} {device.get('label')} (`{device.get('id')}`)"
        )

    return "\n".join(
        [
            f"After-hours reminder: these devices are still ON after {alert_hour}:00.",
            *device_lines,
        ]
    )



def create_bot() -> discord.Client:
    settings = load_settings()

    intents = discord.Intents.default()
    # Required so the bot can read mentions and user text in Discord messages.
    intents.message_content = True

    bot = discord.Client(intents=intents)
    conversations = ConversationManager(settings.max_history_messages)
    office_client = OfficeWebSocketClient(settings.office_ws_url)
    last_notice_channel_id: int | None = settings.office_alert_channel_id
    last_after_hours_signature: tuple[str, ...] = ()
    last_after_hours_sent_at: datetime | None = None
    after_hours_task: asyncio.Task[None] | None = None
    ai_client = OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    async def get_notice_channel() -> discord.abc.Messageable | None:
        channel_id = settings.office_alert_channel_id or last_notice_channel_id
        if not channel_id:
            return None

        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except discord.DiscordException:
                logger.exception("Could not fetch notice channel %s", channel_id)
                return None

        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def post_alert(alert: dict[str, object]) -> None:
        channel = await get_notice_channel()
        if channel:
            await channel.send(f"Office alert: {office_client.format_alert(alert)}")

    async def after_hours_monitor() -> None:
        nonlocal last_after_hours_signature, last_after_hours_sent_at

        await bot.wait_until_ready()
        while not bot.is_closed():
            await asyncio.sleep(60)
            if not settings.office_after_hours_alerts or not office_client.is_ready():
                continue

            now = datetime.now()
            if now.hour < settings.office_alert_hour:
                last_after_hours_signature = ()
                last_after_hours_sent_at = None
                continue

            on_devices = office_client.on_devices()
            if not on_devices:
                last_after_hours_signature = ()
                last_after_hours_sent_at = None
                continue

            signature = tuple(sorted(str(device.get("id")) for device in on_devices))
            repeat_after = timedelta(minutes=settings.office_alert_repeat_minutes)
            should_send = signature != last_after_hours_signature or (
                last_after_hours_sent_at is not None
                and now - last_after_hours_sent_at >= repeat_after
            )
            if not should_send:
                continue

            channel = await get_notice_channel()
            if not channel:
                continue

            await channel.send(
                format_after_hours_message(on_devices, settings.office_alert_hour)
            )
            last_after_hours_signature = signature
            last_after_hours_sent_at = now

    @bot.event
    async def on_ready() -> None:
        nonlocal after_hours_task

        logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")
        office_client.start(post_alert)
        if settings.office_after_hours_alerts and (
            after_hours_task is None or after_hours_task.done()
        ):
            after_hours_task = bot.loop.create_task(after_hours_monitor())

    @bot.event
    async def on_message(message: discord.Message) -> None:
        nonlocal last_notice_channel_id

        if bot.user is None or not should_respond(message, bot.user):
            return

        user_id = message.author.id
        user_message = message.content
        if message.guild is not None:
            user_message = strip_bot_mention(user_message, bot.user.id)
        else:
            user_message = normalize_message(user_message)

        last_notice_channel_id = message.channel.id

        command_reply = await handle_office_command(user_message, office_client)
        if command_reply is not None:
            await send_chunks(message.channel, chunk_discord_message(command_reply))
            return

        ai_control_reply = await handle_ai_control_intent(
            user_message,
            office_client,
            ai_client,
        )
        if ai_control_reply is not None:
            conversations.reset(user_id)
            await send_chunks(message.channel, chunk_discord_message(ai_control_reply))
            return

        control_reply = await handle_natural_control_intent(user_message, office_client)
        if control_reply is not None:
            conversations.reset(user_id)
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

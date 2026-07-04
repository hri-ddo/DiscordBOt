"""Discord entry point for the AI Office Assistant."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

import discord

from config import ConfigError, load_settings
from conversation import ConversationManager, normalize_message
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


def create_bot() -> discord.Client:
    settings = load_settings()

    intents = discord.Intents.default()
    # Required so the bot can read mentions and user text in Discord messages.
    intents.message_content = True

    bot = discord.Client(intents=intents)
    conversations = ConversationManager(settings.max_history_messages)
    ai_client = OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    @bot.event
    async def on_ready() -> None:
        logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")

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

        history = conversations.get_history(user_id)

        async with message.channel.typing():
            reply = await ai_client.generate_reply(user_id, user_message, history)

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
    except ConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

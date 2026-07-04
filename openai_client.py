"""OpenAI Responses API wrapper for the office assistant bot."""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from openai import OpenAI, OpenAIError

from conversation import ConversationMessage, SYSTEM_PROMPT, normalize_message


logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    async def generate_reply(
        self,
        user_id: int,
        user_message: str,
        history: Sequence[ConversationMessage],
        office_context: str | None = None,
    ) -> str:
        """Generate a Discord-ready assistant response."""

        normalized_message = normalize_message(user_message)
        if not normalized_message:
            normalized_message = (
                "The user mentioned you without adding a question. Greet them "
                "briefly and ask how you can help with the office."
            )

        input_messages = [
            message.as_openai_input()
            for message in history
            if normalize_message(message.content)
        ]
        input_messages.append({"role": "user", "content": normalized_message})
        instructions = SYSTEM_PROMPT
        if office_context:
            instructions = f"{SYSTEM_PROMPT}\n\nCurrent office context:\n{office_context}"

        try:
            # The OpenAI SDK call is synchronous, so run it off the event loop.
            response = await asyncio.to_thread(
                self._client.responses.create,
                model=self._model,
                instructions=instructions,
                input=input_messages,
            )
        except OpenAIError:
            logger.exception("OpenAI request failed for Discord user %s", user_id)
            return (
                "I hit a snag while thinking that through. Please try again in a "
                "moment."
            )

        reply = normalize_message(getattr(response, "output_text", "") or "")
        if not reply:
            logger.warning("OpenAI returned an empty response for user %s", user_id)
            return "I did not get a usable answer back. Could you try asking again?"

        return reply

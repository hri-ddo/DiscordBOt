"""OpenAI Responses API wrapper for the office assistant bot."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Sequence

from openai import OpenAI, OpenAIError

from conversation import ConversationMessage, SYSTEM_PROMPT, normalize_message


logger = logging.getLogger(__name__)


STALE_CONTROL_LIMIT_PHRASES = (
    "can't control",
    "cannot control",
    "can't directly control",
    "can't control the lights yet",
    "can't control it yet",
    "hardware control is available",
    "hardware control isn't available",
    "hardware control is not available",
    "when hardware control is available",
)


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

        if contains_stale_control_limit(reply):
            return (
                "I can control connected office fans and lights through the "
                "office WebSocket. Tell me the room, device type, number, and "
                "whether you want it on or off."
            )

        return reply

    async def parse_control_intent(
        self,
        user_message: str,
        device_ids: Sequence[str],
    ) -> dict[str, Any] | None:
        """Parse multilingual office-control text into a small JSON action."""

        normalized_message = normalize_message(user_message)
        if not normalized_message:
            return None

        instructions = (
            "You are an intent parser for an office device controller. "
            "Return ONLY compact JSON, no markdown. "
            "Supported rooms: drawing, workroom1, workroom2. "
            "Supported device types: fan, light. "
            "Device numbers: fans are 1-2, lights are 1-3. "
            "Supported statuses: on, off. "
            "Schema: {\"action\":\"none|set_device|set_group\","
            "\"room\":\"drawing|workroom1|workroom2|null\","
            "\"device_type\":\"fan|light|null\","
            "\"device_number\":1,"
            "\"status\":\"on|off|null\"}. "
            "Use set_device when the user names one room/device/number, in any language. "
            "Use set_group when the user asks all fans/lights on/off, optionally in one room. "
            "If the message only asks for status without a command, use action none. "
            "If target room, type, number, or status is ambiguous for a single-device action, use action none."
        )
        prompt = (
            f"Available device IDs: {', '.join(device_ids)}\n"
            f"User message: {normalized_message}"
        )

        try:
            response = await asyncio.to_thread(
                self._client.responses.create,
                model=self._model,
                instructions=instructions,
                input=prompt,
            )
        except OpenAIError:
            logger.exception("OpenAI intent parsing failed")
            return None

        raw_text = (getattr(response, "output_text", "") or "").strip()
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("Could not parse intent JSON: %s", raw_text)
            return None

        return parsed if isinstance(parsed, dict) else None


def contains_stale_control_limit(reply: str) -> bool:
    normalized_reply = reply.lower()
    return any(phrase in normalized_reply for phrase in STALE_CONTROL_LIMIT_PHRASES)

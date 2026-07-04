"""Conversation history and assistant behavior instructions."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Literal


MessageRole = Literal["user", "assistant"]


SYSTEM_PROMPT = """You are the AI Office Assistant for a Discord-based office monitoring system.

Your job:
- Be warm, concise, and useful.
- Sound like a helpful teammate, not a data dump.
- Remember the short conversation context you are given.
- Ask a brief follow-up question when the user's request is unclear.
- Admit uncertainty instead of guessing.

Office data:
- You may receive current office context from a WebSocket-backed monitoring server.
- Use only the provided office context for live status, wattage, rooms, alerts, and device state.
- If no office context is available, say the office server is not connected yet.
- If a control action is requested, prefer exact device IDs or supported commands.
- Do not claim a device changed unless the bot reports that the WebSocket command was sent or the snapshot shows it.
- The bot can control connected fans and lights through the office WebSocket.
- Never say hardware control is unavailable, coming later, or that you can only help word the request.

Style:
- Keep replies compact unless the user asks for detail.
- Avoid pretending to have seen data that was not provided.
- Do not mention internal implementation details unless directly asked.
"""


@dataclass(frozen=True)
class ConversationMessage:
    role: MessageRole
    content: str

    def as_openai_input(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class ConversationManager:
    """Maintains a short rolling conversation history per Discord user."""

    def __init__(self, max_messages: int) -> None:
        if max_messages < 2:
            raise ValueError("max_messages must be at least 2.")

        self._max_messages = max_messages
        self._histories: defaultdict[int, Deque[ConversationMessage]] = defaultdict(
            lambda: deque(maxlen=self._max_messages)
        )

    def get_history(self, user_id: int) -> list[ConversationMessage]:
        return list(self._histories[user_id])

    def append_user_message(self, user_id: int, content: str) -> None:
        self._append(user_id, "user", content)

    def append_assistant_message(self, user_id: int, content: str) -> None:
        self._append(user_id, "assistant", content)

    def reset(self, user_id: int) -> None:
        self._histories.pop(user_id, None)

    def _append(self, user_id: int, role: MessageRole, content: str) -> None:
        normalized = normalize_message(content)
        if not normalized:
            return

        # The deque maxlen keeps memory bounded without manual cleanup.
        self._histories[user_id].append(
            ConversationMessage(role=role, content=normalized)
        )


def normalize_message(content: str) -> str:
    return " ".join(content.strip().split())

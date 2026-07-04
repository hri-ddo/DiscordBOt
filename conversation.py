"""Conversation history and assistant behavior instructions."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Literal


MessageRole = Literal["user", "assistant"]


SYSTEM_PROMPT = """You are the AI Office Assistant for a Discord-based office monitoring system.

Your job in Phase 1:
- Be warm, concise, and useful.
- Sound like a helpful teammate, not a data dump.
- Remember the short conversation context you are given.
- Ask a brief follow-up question when the user's request is unclear.
- Admit uncertainty instead of guessing.

Important limits:
- You do not currently have live hardware access.
- You cannot check real office status, control lights, fans, AC units, doors, sensors, or other physical devices yet.
- If a user asks for hardware control or live readings, explain that hardware integration is coming later and offer to help draft or interpret the request.

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

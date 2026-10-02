from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass
class Session:
    id: str
    access_token: str | None = None
    customer_id: str | None = None
    scopes: set[str] = field(default_factory=set)
    pending_intent: str | None = None
    pending_actions: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    retrieved_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    handed_off: bool = False
    handoff_summary: str | None = None

    @property
    def authenticated(self) -> bool:
        return self.access_token is not None

    def record_message(self, role: str, content: str) -> None:
        self.history.append({"type": "message", "role": role, "content": content})

    def record_tool_result(self, tool: str, output: dict[str, Any]) -> None:
        self.history.append({"type": "tool_result", "tool": tool, "output": output})

    def record_action_result(self, action: str, result: dict[str, Any]) -> None:
        self.history.append({"type": "action_result", "action": action, "result": result})


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str | None = None) -> Session:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            sid = session_id or str(uuid4())
            session = Session(id=sid)
            self._sessions[sid] = session
            return session

    def get(self, session_id: str) -> Session:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(session_id)
            return self._sessions[session_id]

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


sessions = SessionStore()

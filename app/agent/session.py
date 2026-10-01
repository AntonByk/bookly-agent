from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4


@dataclass
class Session:
    id: str
    access_token: str | None = None
    customer_id: str | None = None
    scopes: set[str] = field(default_factory=set)
    pending_intent: str | None = None
    pending_action_ids: set[str] = field(default_factory=set)
    history: list[dict[str, str]] = field(default_factory=list)

    @property
    def authenticated(self) -> bool:
        return self.access_token is not None


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


sessions = SessionStore()

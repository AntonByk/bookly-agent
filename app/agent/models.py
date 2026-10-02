from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class TraceEvent(BaseModel):
    type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class UiAction(BaseModel):
    type: Literal["verify_email", "confirm_action", "human_handoff", "orders_table"]
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    message: str
    authenticated: bool
    sources: list[dict[str, str]] = Field(default_factory=list)
    ui_actions: list[UiAction] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)


class AuthStartRequest(BaseModel):
    session_id: str
    email: str


class AuthVerifyRequest(BaseModel):
    session_id: str
    challenge_id: str
    code: str


class AuthResumeRequest(BaseModel):
    session_id: str


class ActionConfirmRequest(BaseModel):
    session_id: str

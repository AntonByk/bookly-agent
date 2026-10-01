from __future__ import annotations

from app.agent.models import ChatResponse, TraceEvent, UiAction
from app.agent.session import Session


async def handle_message(session: Session, message: str) -> ChatResponse:
    """Skeleton orchestration entrypoint.

    The next build step will replace this deterministic placeholder with the
    direct Responses API tool loop. Keeping the API stable lets us build and
    test the surrounding product now.
    """
    session.history.append({"role": "user", "content": message})

    trace = [TraceEvent(type="message_received", message="User message accepted by orchestrator.")]

    lower = message.lower()
    if any(term in lower for term in ("my order", "where's my order", "where is my order")) and not session.authenticated:
        session.pending_intent = message
        trace.append(TraceEvent(type="auth_required", message="Customer-specific state requires verification."))
        reply = "I can check that for you. Please verify the email you ordered with first."
        action = UiAction(type="verify_email", label="Verify email")
        session.history.append({"role": "assistant", "content": reply})
        return ChatResponse(
            session_id=session.id,
            message=reply,
            authenticated=False,
            ui_actions=[action],
            trace=trace,
        )

    reply = (
        "The product skeleton is running. Live LLM orchestration and tool calling "
        "will be connected in the next implementation step."
    )
    trace.append(TraceEvent(type="skeleton_mode", message="No LLM call made in this milestone."))
    session.history.append({"role": "assistant", "content": reply})
    return ChatResponse(
        session_id=session.id,
        message=reply,
        authenticated=session.authenticated,
        trace=trace,
    )

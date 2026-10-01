from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.agent.models import ChatResponse, TraceEvent
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.session import Session
from app.agent.settings import settings
from app.agent.tools import available_tools, execute_tool


def _history_as_input(session: Session) -> list[dict[str, str]]:
    return [{"role": item["role"], "content": item["content"]} for item in session.history]


def _usage_trace(response: Any) -> TraceEvent | None:
    usage = getattr(response, "usage", None)
    if not usage:
        return None
    return TraceEvent(
        type="model_usage",
        message="Model response completed.",
        data={
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
    )


async def run_agent_turn(
    session: Session,
    *,
    current_user_message: str | None,
    resume_after_auth: bool = False,
) -> ChatResponse:
    if not settings.openai_api_key:
        return ChatResponse(
            session_id=session.id,
            message=(
                "The Bookly agent is running, but no model API key is configured. "
                "Set OPENAI_API_KEY in .env to enable the live agent."
            ),
            authenticated=session.authenticated,
            trace=[TraceEvent(type="configuration_error", message="OPENAI_API_KEY is not configured.")],
        )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    input_items: list[Any] = _history_as_input(session)
    if resume_after_auth:
        input_items.append(
            {
                "role": "developer",
                "content": (
                    "The customer has now successfully verified their email. "
                    "Resume the pending customer request using the newly available authenticated tools. "
                    "Do not ask them to repeat the request."
                ),
            }
        )

    traces: list[TraceEvent] = []
    sources_by_id: dict[str, dict[str, str]] = {}
    ui_actions = []

    for iteration in range(1, settings.max_tool_iterations + 1):
        tools = available_tools(session)
        traces.append(
            TraceEvent(
                type="model_call",
                message="Calling the model with progressively disclosed capabilities.",
                data={
                    "iteration": iteration,
                    "authenticated": session.authenticated,
                    "tools": [tool["name"] for tool in tools],
                },
            )
        )

        response = await client.responses.create(
            model=settings.openai_model,
            instructions=SYSTEM_PROMPT,
            input=input_items,
            tools=tools,
            max_output_tokens=900,
        )

        usage_trace = _usage_trace(response)
        if usage_trace:
            traces.append(usage_trace)

        tool_calls = [
            item
            for item in response.output
            if getattr(item, "type", None) == "function_call"
        ]

        if not tool_calls:
            text = (response.output_text or "").strip()
            if not text:
                text = "I couldn't complete that request safely. Please try again."
            session.history.append({"role": "assistant", "content": text})
            return ChatResponse(
                session_id=session.id,
                message=text,
                authenticated=session.authenticated,
                sources=list(sources_by_id.values()),
                ui_actions=ui_actions,
                trace=traces,
            )

        input_items.extend(response.output)

        for call in tool_calls:
            try:
                arguments = json.loads(call.arguments or "{}")
                execution = await execute_tool(
                    session,
                    call.name,
                    arguments,
                    current_user_message=current_user_message,
                )
                traces.extend(execution.trace)
                ui_actions.extend(execution.ui_actions)
                for source in execution.sources:
                    sources_by_id[source["article_id"]] = source
                tool_output = execution.output
            except Exception as exc:
                traces.append(
                    TraceEvent(
                        type="tool_error",
                        message=f"Tool {call.name} failed safely.",
                        data={"tool": call.name, "error": str(exc)},
                    )
                )
                tool_output = {
                    "error": "tool_unavailable",
                    "message": "The Bookly service could not complete this request.",
                }

            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(tool_output),
                }
            )

    fallback = "I couldn't complete that request safely after several steps. Please try again."
    traces.append(
        TraceEvent(
            type="loop_limit_reached",
            message="Stopped the tool loop at the configured safety limit.",
            data={"max_iterations": settings.max_tool_iterations},
        )
    )
    session.history.append({"role": "assistant", "content": fallback})
    return ChatResponse(
        session_id=session.id,
        message=fallback,
        authenticated=session.authenticated,
        sources=list(sources_by_id.values()),
        ui_actions=ui_actions,
        trace=traces,
    )


async def handle_message(session: Session, message: str) -> ChatResponse:
    session.history.append({"role": "user", "content": message})
    return await run_agent_turn(session, current_user_message=message)


async def resume_pending_request(session: Session, pending_intent: str) -> ChatResponse:
    return await run_agent_turn(
        session,
        current_user_message=pending_intent,
        resume_after_auth=True,
    )

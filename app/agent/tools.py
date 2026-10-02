from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.agent.actions import propose_return
from app.agent.models import TraceEvent, UiAction
from app.agent.session import Session
from app.agent.settings import settings


PUBLIC_TOOLS = [
    {
        "type": "function",
        "name": "search_knowledge",
        "description": "Search Bookly public help-centre content for information relevant to the customer's question.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "request_authentication",
        "description": "Request customer email verification when the customer's request requires private order or account state.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short customer-facing reason verification is needed.",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "request_human_handoff",
        "description": (
            "Hand the conversation to a human support specialist when the customer explicitly asks for a human, "
            "or when the request cannot be resolved safely with the available Bookly knowledge and tools. "
            "Do not use this merely because clarification is needed or because a policy outcome is unfavorable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason_category": {
                    "type": "string",
                    "enum": [
                        "customer_requested",
                        "unsupported_request",
                        "needs_human_judgment",
                        "service_limitation",
                    ],
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "Concise factual handoff summary for the human agent. Include only context established "
                        "in the conversation or Bookly systems, never invented facts."
                    ),
                },
            },
            "required": ["reason_category", "summary"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "cite_knowledge_sources",
        "description": "Attach software-rendered citations for retrieved Bookly help articles that actually support the answer. Never cite a merely related article.",
        "parameters": {
            "type": "object",
            "properties": {
                "article_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["article_ids"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

VERIFIED_TOOLS = [
    {
        "type": "function",
        "name": "list_orders",
        "description": "List recent orders owned by the authenticated customer. Use this before identifying an order from natural language.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_order",
        "description": "Get authoritative details for one order owned by the authenticated customer.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_tracking",
        "description": "Get authoritative tracking events for one order owned by the authenticated customer.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_resolution_options",
        "description": "Get Commerce-authorized refund/replacement options for a delayed or missing order.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "check_return_eligibility",
        "description": "Ask Commerce whether an item is eligible for a return for a normalized reason category.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "item_id": {"type": "string"},
                "reason_category": {"type": "string", "enum": ["changed_mind", "damaged"]},
            },
            "required": ["order_id", "item_id", "reason_category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "propose_return",
        "description": "Prepare a pending return proposal for software-rendered customer confirmation. This does not execute a return.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "item_id": {"type": "string"},
                "reason_category": {"type": "string", "enum": ["changed_mind", "damaged"]},
            },
            "required": ["order_id", "item_id", "reason_category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


@dataclass
class ToolExecution:
    output: dict[str, Any]
    trace: list[TraceEvent] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    ui_actions: list[UiAction] = field(default_factory=list)


def available_tools(session: Session) -> list[dict[str, Any]]:
    tools = list(PUBLIC_TOOLS)
    if session.authenticated:
        tools.extend(VERIFIED_TOOLS)
    return tools


async def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=4.0) as client:
        response = await client.request(method, url, json=json_body, headers=request_headers)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"Bookly service returned {response.status_code}: {detail}")
    return response.json()


def _should_render_orders_table(message: str | None) -> bool:
    if not message:
        return False
    normalized = message.lower()
    broad_phrases = (
        "my orders",
        "recent orders",
        "show me my orders",
        "show my orders",
        "list my orders",
        "where are my orders",
        "what orders",
    )
    return any(phrase in normalized for phrase in broad_phrases)


async def execute_tool(
    session: Session,
    name: str,
    arguments: dict[str, Any],
    *,
    current_user_message: str | None,
) -> ToolExecution:
    if name == "request_authentication":
        if session.authenticated:
            return ToolExecution(
                output={"status": "already_authenticated"},
                trace=[TraceEvent(type="auth_skipped", message="Customer is already verified.")],
            )
        session.pending_intent = current_user_message or session.pending_intent
        return ToolExecution(
            output={"status": "authentication_required"},
            ui_actions=[UiAction(type="verify_email", label="Verify email")],
            trace=[
                TraceEvent(
                    type="auth_required",
                    message="Model requested customer verification before accessing private state.",
                    data={"reason": arguments["reason"]},
                )
            ],
        )

    if name == "request_human_handoff":
        if session.handed_off:
            return ToolExecution(
                output={"status": "already_handed_off"},
                ui_actions=[
                    UiAction(
                        type="human_handoff",
                        label="Human handoff",
                        payload={"summary": session.handoff_summary or arguments["summary"]},
                    )
                ],
                trace=[
                    TraceEvent(
                        type="handoff_already_active",
                        message="Conversation was already handed to human support.",
                    )
                ],
            )

        session.handed_off = True
        session.handoff_summary = arguments["summary"]
        session.pending_intent = None
        session.pending_actions.clear()

        return ToolExecution(
            output={
                "status": "handed_off",
                "reason_category": arguments["reason_category"],
                "summary": arguments["summary"],
            },
            ui_actions=[
                UiAction(
                    type="human_handoff",
                    label="Human handoff",
                    payload={
                        "reason_category": arguments["reason_category"],
                        "summary": arguments["summary"],
                    },
                )
            ],
            trace=[
                TraceEvent(
                    type="human_handoff",
                    message="The AI agent stopped handling the case and handed the conversation to human support.",
                    data={"reason_category": arguments["reason_category"]},
                )
            ],
        )

    if name == "search_knowledge":
        result = await _request(
            "POST",
            f"{settings.knowledge_base_url}/v1/search",
            json_body={"query": arguments["query"], "limit": 3},
        )
        retrieved = [
            {"article_id": item["article_id"], "title": item["title"]}
            for item in result.get("results", [])
        ]
        for source in retrieved:
            session.retrieved_sources[source["article_id"]] = source
        return ToolExecution(
            output=result,
            trace=[
                TraceEvent(
                    type="tool_call",
                    message="Searched Bookly knowledge.",
                    data={
                        "tool": name,
                        "query": arguments["query"],
                        "result_count": len(retrieved),
                        "article_ids": [source["article_id"] for source in retrieved],
                    },
                )
            ],
        )

    if name == "cite_knowledge_sources":
        requested = arguments.get("article_ids", [])
        missing = [article_id for article_id in requested if article_id not in session.retrieved_sources]
        if missing:
            raise RuntimeError(f"Cannot cite articles that were not retrieved: {missing}")
        sources = [session.retrieved_sources[article_id] for article_id in requested]
        return ToolExecution(
            output={"status": "sources_attached", "article_ids": requested},
            sources=sources,
            trace=[
                TraceEvent(
                    type="sources_attached",
                    message="Software validated and attached retrieved Bookly sources.",
                    data={"article_ids": requested},
                )
            ],
        )

    if not session.authenticated or not session.access_token:
        raise RuntimeError("Authenticated tool requested without a verified customer session")

    if name == "list_orders":
        result = await _request(
            "GET",
            f"{settings.commerce_base_url}/v1/orders",
            token=session.access_token,
        )
        ui_actions = []
        if _should_render_orders_table(current_user_message):
            ui_actions.append(
                UiAction(
                    type="orders_table",
                    label="Recent orders",
                    payload={"orders": result.get("orders", [])},
                )
            )
        return ToolExecution(
            output=result,
            ui_actions=ui_actions,
            trace=[
                TraceEvent(
                    type="tool_call",
                    message="Called Bookly list_orders.",
                    data={"tool": name, "arguments": arguments},
                )
            ],
        )
    elif name == "get_order":
        result = await _request(
            "GET",
            f"{settings.commerce_base_url}/v1/orders/{arguments['order_id']}",
            token=session.access_token,
        )
    elif name == "get_tracking":
        result = await _request(
            "GET",
            f"{settings.commerce_base_url}/v1/orders/{arguments['order_id']}/tracking",
            token=session.access_token,
        )
    elif name == "get_resolution_options":
        result = await _request(
            "GET",
            f"{settings.commerce_base_url}/v1/orders/{arguments['order_id']}/resolution-options",
            token=session.access_token,
        )
    elif name == "check_return_eligibility":
        result = await _request(
            "POST",
            f"{settings.commerce_base_url}/v1/returns/check",
            token=session.access_token,
            json_body=arguments,
        )
    elif name == "propose_return":
        eligibility = await _request(
            "POST",
            f"{settings.commerce_base_url}/v1/returns/check",
            token=session.access_token,
            json_body=arguments,
        )
        if not eligibility.get("eligible"):
            return ToolExecution(
                output={"status": "not_proposed", "eligibility": eligibility},
                trace=[
                    TraceEvent(
                        type="action_rejected",
                        message="Return proposal was not created because Commerce did not confirm eligibility.",
                        data={"order_id": arguments["order_id"], "item_id": arguments["item_id"]},
                    )
                ],
            )
        action = propose_return(
            session,
            order_id=arguments["order_id"],
            item_id=arguments["item_id"],
            reason_category=arguments["reason_category"],
            eligibility=eligibility,
        )
        result = {
            "status": "pending_confirmation",
            "pending_action_id": action.id,
            "summary": action.summary,
        }
        return ToolExecution(
            output=result,
            ui_actions=[
                UiAction(
                    type="confirm_action",
                    label="Confirm return",
                    payload={"action_id": action.id, **action.summary},
                )
            ],
            trace=[
                TraceEvent(
                    type="action_proposed",
                    message="Model proposed a return; software created a pending action awaiting explicit confirmation.",
                    data={
                        "action_id": action.id,
                        "order_id": arguments["order_id"],
                        "item_id": arguments["item_id"],
                        "reason_category": arguments["reason_category"],
                    },
                )
            ],
        )
    else:
        raise RuntimeError(f"Unknown tool: {name}")

    return ToolExecution(
        output=result,
        trace=[
            TraceEvent(
                type="tool_call",
                message=f"Called Bookly {name}.",
                data={"tool": name, "arguments": arguments},
            )
        ],
    )

from fastapi.testclient import TestClient

from app.agent.orchestrator import _handoff_response, _history_as_input, _sanitize_customer_text
from app.agent.prompts import build_system_prompt
from app.agent.actions import PendingAction
from app.agent.models import TraceEvent, UiAction
from app.agent.server import app as agent_app
from app.agent.session import Session, sessions
from services.commerce.server import (
    ACTIVE_RETURNS_BY_ITEM,
    CREATED_RETURNS,
    app as commerce_app,
)
from services.identity.server import issue_token


def test_prompt_contains_pinned_demo_date():
    prompt = build_system_prompt("2026-10-01")
    assert "2026-10-01" in prompt
    assert "Use this as today's date" in prompt


def test_structured_history_preserves_tool_and_confirmed_action_results():
    session = Session(id="history")
    session.record_message("user", "Where is my order?")
    session.record_tool_result(
        "list_orders",
        {"orders": [{"order_id": "ORD-1001", "status": "in_transit"}]},
    )
    session.record_action_result(
        "create_return",
        {"return_id": "RET-1001", "refund_status": "pending_item_receipt"},
    )

    model_input = _history_as_input(session)

    assert model_input[0]["role"] == "user"
    assert "ORD-1001" in model_input[1]["content"]
    assert "Authoritative Bookly tool result" in model_input[1]["content"]
    assert "RET-1001" in model_input[2]["content"]
    assert "customer-confirmed application action" in model_input[2]["content"]


def test_commerce_blocks_duplicate_return_with_different_idempotency_key():
    CREATED_RETURNS.clear()
    ACTIVE_RETURNS_BY_ITEM.clear()

    token = issue_token(
        "CUST-001",
        ["orders:read", "returns:read", "returns:execute"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "order_id": "ORD-1002",
        "item_id": "ITEM-OTTOLENGHI",
        "reason_category": "changed_mind",
    }
    client = TestClient(commerce_app)

    first = client.post(
        "/v1/returns",
        headers={**headers, "Idempotency-Key": "ACT-FIRST"},
        json=payload,
    )
    assert first.status_code == 200

    retry = client.post(
        "/v1/returns",
        headers={**headers, "Idempotency-Key": "ACT-FIRST"},
        json=payload,
    )
    assert retry.status_code == 200
    assert retry.json()["return_id"] == first.json()["return_id"]

    duplicate = client.post(
        "/v1/returns",
        headers={**headers, "Idempotency-Key": "ACT-SECOND"},
        json=payload,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ACTIVE_RETURN_EXISTS"

    eligibility = client.post(
        "/v1/returns/check",
        headers=headers,
        json=payload,
    )
    assert eligibility.status_code == 200
    assert eligibility.json()["eligible"] is False
    assert eligibility.json()["existing_return_id"] == first.json()["return_id"]


def test_prompt_distinguishes_clarification_policy_and_handoff():
    prompt = build_system_prompt("2026-10-01")
    assert "explicitly asks to speak to a human" in prompt
    assert "Do not hand off merely because you need clarification" in prompt
    assert "Commerce denies an action" in prompt


def test_customer_order_access_is_scoped_by_identity():
    client = TestClient(commerce_app)
    scopes = ["orders:read", "returns:read", "returns:execute"]

    alex_headers = {"Authorization": f"Bearer {issue_token('CUST-001', scopes)}"}
    jamie_headers = {"Authorization": f"Bearer {issue_token('CUST-002', scopes)}"}

    alex_orders = client.get("/v1/orders", headers=alex_headers)
    jamie_orders = client.get("/v1/orders", headers=jamie_headers)

    assert alex_orders.status_code == 200
    assert jamie_orders.status_code == 200

    alex_ids = {order["order_id"] for order in alex_orders.json()["orders"]}
    jamie_ids = {order["order_id"] for order in jamie_orders.json()["orders"]}

    assert alex_ids == {"ORD-1001", "ORD-1002", "ORD-1003"}
    assert jamie_ids == {"ORD-2001", "ORD-2002"}
    assert alex_ids.isdisjoint(jamie_ids)

    assert client.get("/v1/orders/ORD-2001", headers=alex_headers).status_code == 404
    assert client.get("/v1/orders/ORD-1001", headers=jamie_headers).status_code == 404


def test_terminal_handoff_discards_pending_actions_and_only_returns_handoff_ui():
    session = Session(
        id="terminal-handoff",
        access_token="server-side-token",
        customer_id="CUST-001",
        handed_off=True,
    )
    session.pending_actions["ACT-STALE"] = PendingAction(
        id="ACT-STALE",
        order_id="ORD-1002",
        item_id="ITEM-OTTOLENGHI",
        reason_category="changed_mind",
        summary={},
    )

    response = _handoff_response(
        session,
        [TraceEvent(type="human_handoff", message="handoff requested")],
        [
            UiAction(
                type="human_handoff",
                label="Human handoff",
                payload={"summary": "Customer asked for a person."},
            )
        ],
    )

    assert session.pending_actions == {}
    assert response.message == "A Bookly support specialist will join this conversation soon."
    assert [action.type for action in response.ui_actions] == ["human_handoff"]
    assert response.trace[-1].type == "handoff_terminal"


def test_confirm_endpoint_rejects_stale_action_after_handoff():
    session = sessions.get_or_create("handoff-confirm-block")
    session.access_token = "server-side-token"
    session.customer_id = "CUST-001"
    session.handed_off = True
    session.pending_actions["ACT-STALE"] = PendingAction(
        id="ACT-STALE",
        order_id="ORD-1002",
        item_id="ITEM-OTTOLENGHI",
        reason_category="changed_mind",
        summary={},
    )

    client = TestClient(agent_app)
    response = client.post(
        "/api/actions/ACT-STALE/confirm",
        json={"session_id": session.id},
    )

    assert response.status_code == 409
    assert "AI actions are disabled" in response.json()["detail"]


def test_customer_copy_never_contains_en_or_em_dash():
    text = _sanitize_customer_text("Hello — your order is ready – thanks.")
    assert "—" not in text
    assert "–" not in text
    assert text == "Hello - your order is ready - thanks."

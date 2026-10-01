from fastapi.testclient import TestClient

from app.agent.orchestrator import _history_as_input
from app.agent.prompts import build_system_prompt
from app.agent.session import Session
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

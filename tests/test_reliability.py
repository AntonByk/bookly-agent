import httpx

from fastapi.testclient import TestClient

from app.agent.orchestrator import _handoff_response, _history_as_input, _is_order_overview_request, _merge_ui_actions, _sanitize_customer_text
from app.agent.prompts import build_system_prompt
from app.agent.actions import PendingAction
from app.agent.models import TraceEvent, UiAction
import app.agent.server as agent_server
from app.agent.server import RATE_LIMIT_BUCKETS, app as agent_app
from app.agent.settings import settings
from app.agent.session import Session, sessions
from app.agent.tools import PUBLIC_TOOLS, ToolServiceError
from services.commerce.server import (
    ACTIVE_RETURNS_BY_ITEM,
    CREATED_RETURNS,
    app as commerce_app,
)
from services.identity.server import issue_token
from services.knowledge.server import app as knowledge_app
from run import build_services


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
    assert "customer-triggered application action" in model_input[2]["content"]


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


def test_auth_resume_requires_verified_session():
    session = sessions.get_or_create("resume-auth-required")
    session.access_token = None
    session.pending_intent = "Where is my order?"

    client = TestClient(agent_app)
    response = client.post(
        "/api/auth/resume",
        json={"session_id": session.id},
    )

    assert response.status_code == 401
    assert session.pending_intent == "Where is my order?"


def test_expanded_knowledge_base_retrieves_country_and_issue_policies():
    client = TestClient(knowledge_app)

    finland = client.post(
        "/v1/search",
        json={"query": "How long does shipping to Finland take?", "limit": 3},
    )
    assert finland.status_code == 200
    assert finland.json()["results"][0]["article_id"] == "international-shipping"
    assert "5-8 business days" in finland.json()["results"][0]["content"]

    wrong_item = client.post(
        "/v1/search",
        json={"query": "I received the wrong book in my parcel", "limit": 3},
    )
    assert wrong_item.status_code == 200
    assert wrong_item.json()["results"][0]["article_id"] == "wrong-missing-item"


def test_gift_wrapping_remains_an_intentional_knowledge_gap():
    client = TestClient(knowledge_app)
    result = client.post(
        "/v1/search",
        json={"query": "Can you gift-wrap a book and include a handwritten note?", "limit": 3},
    )
    assert result.status_code == 200
    articles = result.json()["results"]
    assert articles
    assert articles[0]["article_id"] == "gift-cards"
    assert "gift wrap" not in articles[0]["content"].lower()
    assert "handwritten" not in articles[0]["content"].lower()


def test_confirm_service_failure_preserves_pending_action(monkeypatch):
    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            raise httpx.ConnectError(
                "commerce unavailable",
                request=httpx.Request("POST", url),
            )

    session = sessions.get_or_create("confirm-service-failure")
    session.access_token = issue_token(
        "CUST-001",
        ["orders:read", "returns:read", "returns:execute"],
    )
    session.customer_id = "CUST-001"
    session.handed_off = False
    action = PendingAction(
        id="ACT-SERVICE-DOWN",
        order_id="ORD-1002",
        item_id="ITEM-OTTOLENGHI",
        reason_category="changed_mind",
        summary={},
    )
    session.pending_actions[action.id] = action

    monkeypatch.setattr(agent_server.httpx, "AsyncClient", FailingAsyncClient)

    client = TestClient(agent_app)
    response = client.post(
        f"/api/actions/{action.id}/confirm",
        json={"session_id": session.id},
    )

    assert response.status_code == 503
    assert "No return was created" in response.json()["detail"]
    assert action.id in session.pending_actions
    assert not any(event["type"] == "action_result" for event in session.history)


def test_order_table_persists_for_order_overview_but_is_suppressed_by_specific_reads():
    table = UiAction(
        type="orders_table",
        label="Recent orders",
        payload={"orders": [{"order_id": "ORD-1001"}]},
    )

    assert _is_order_overview_request("Where are my orders?") is True
    assert _is_order_overview_request("Show me my recent orders") is True
    assert _is_order_overview_request("Has Dune actually been collected?") is False

    overview_actions = _merge_ui_actions([], [table], tool_name="list_orders")
    enriched_overview_actions = _merge_ui_actions(
        overview_actions,
        [],
        tool_name="get_tracking",
        preserve_order_table=True,
    )
    assert [action.type for action in enriched_overview_actions] == ["orders_table"]

    tracking_actions = _merge_ui_actions(
        overview_actions,
        [],
        tool_name="get_tracking",
        preserve_order_table=False,
    )
    assert tracking_actions == []

    return_actions = _merge_ui_actions(
        overview_actions,
        [
            UiAction(
                type="confirm_action",
                label="Confirm return",
                payload={"action_id": "ACT-1"},
            )
        ],
        tool_name="propose_return",
        preserve_order_table=False,
    )
    assert [action.type for action in return_actions] == ["confirm_action"]


def test_general_delivery_overview_and_return_query_rank_correct_articles():
    client = TestClient(knowledge_app)

    delivery = client.post(
        "/v1/search",
        json={"query": "How long does delivery normally take?", "limit": 3},
    )
    assert delivery.status_code == 200
    assert delivery.json()["results"][0]["article_id"] == "delivery-times"

    returns = client.post(
        "/v1/search",
        json={"query": "Can I return a book?", "limit": 3},
    )
    assert returns.status_code == 200
    assert returns.json()["results"][0]["article_id"] == "returns"


def test_tool_service_error_exposes_stable_code_and_safe_message():
    error = ToolServiceError("not_found", "The requested Bookly record was not found.")
    assert error.code == "not_found"
    assert error.safe_message == "The requested Bookly record was not found."


def test_confirm_timeout_preserves_pending_action_and_reports_unknown_outcome(monkeypatch):
    class TimingOutAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            raise httpx.ReadTimeout(
                "commerce response timed out",
                request=httpx.Request("POST", url),
            )

    session = sessions.get_or_create("confirm-timeout-unknown")
    session.access_token = issue_token(
        "CUST-001",
        ["orders:read", "returns:read", "returns:execute"],
    )
    session.customer_id = "CUST-001"
    session.handed_off = False
    action = PendingAction(
        id="ACT-TIMEOUT",
        order_id="ORD-1002",
        item_id="ITEM-OTTOLENGHI",
        reason_category="changed_mind",
        summary={},
    )
    session.pending_actions[action.id] = action

    monkeypatch.setattr(agent_server.httpx, "AsyncClient", TimingOutAsyncClient)

    client = TestClient(agent_app)
    response = client.post(
        f"/api/actions/{action.id}/confirm",
        json={"session_id": session.id},
    )

    assert response.status_code == 504
    assert "couldn't confirm whether the return completed" in response.json()["detail"]
    assert "safe to press Confirm again" in response.json()["detail"]
    assert action.id in session.pending_actions
    assert not any(event["type"] == "action_result" for event in session.history)


def test_cancel_endpoint_removes_pending_action_and_records_cancellation():
    session = sessions.get_or_create("cancel-pending-return")
    session.handed_off = False
    action = PendingAction(
        id="ACT-CANCEL",
        order_id="ORD-1002",
        item_id="ITEM-WOK",
        reason_category="changed_mind",
        summary={},
    )
    session.pending_actions[action.id] = action

    client = TestClient(agent_app)
    response = client.post(
        f"/api/actions/{action.id}/cancel",
        json={"session_id": session.id},
    )

    assert response.status_code == 200
    assert response.json()["cancelled"] is True
    assert action.id not in session.pending_actions
    assert any(
        event["type"] == "action_result"
        and event["action"] == "cancel_return_proposal"
        for event in session.history
    )


def test_mutable_commerce_state_is_isolated_by_demo_session():
    CREATED_RETURNS.clear()
    ACTIVE_RETURNS_BY_ITEM.clear()

    token = issue_token(
        "CUST-001",
        ["orders:read", "returns:read", "returns:execute"],
    )
    payload = {
        "order_id": "ORD-1002",
        "item_id": "ITEM-OTTOLENGHI",
        "reason_category": "changed_mind",
    }
    client = TestClient(commerce_app)

    session_a = {
        "Authorization": f"Bearer {token}",
        "X-Demo-Session-ID": "reviewer-a",
    }
    session_b = {
        "Authorization": f"Bearer {token}",
        "X-Demo-Session-ID": "reviewer-b",
    }

    first_a = client.post(
        "/v1/returns",
        headers={**session_a, "Idempotency-Key": "ACT-A1"},
        json=payload,
    )
    assert first_a.status_code == 200

    duplicate_a = client.post(
        "/v1/returns",
        headers={**session_a, "Idempotency-Key": "ACT-A2"},
        json=payload,
    )
    assert duplicate_a.status_code == 409

    first_b = client.post(
        "/v1/returns",
        headers={**session_b, "Idempotency-Key": "ACT-B1"},
        json=payload,
    )
    assert first_b.status_code == 200

    reset_a = client.delete("/v1/demo/sessions/reviewer-a")
    assert reset_a.status_code == 200
    assert reset_a.json()["returns_removed"] == 1

    a_after_reset = client.post(
        "/v1/returns/check",
        headers=session_a,
        json=payload,
    )
    b_after_reset = client.post(
        "/v1/returns/check",
        headers=session_b,
        json=payload,
    )
    assert a_after_reset.json()["eligible"] is True
    assert b_after_reset.json()["eligible"] is False
    assert b_after_reset.json()["existing_return_id"] == first_b.json()["return_id"]


def test_railway_port_overrides_local_agent_port(monkeypatch):
    monkeypatch.setenv("AGENT_PORT", "8000")
    monkeypatch.setenv("PORT", "9123")
    services = build_services()
    agent = next(service for service in services if service[0] == "Agent")
    assert agent[2] == 9123


def test_robots_disallow_indexing():
    client = TestClient(agent_app)
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.text == "User-agent: *\nDisallow: /\n"


def test_public_demo_rate_limit_is_opt_in(monkeypatch):
    RATE_LIMIT_BUCKETS.clear()
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "demo_rate_limit_requests", 2)
    monkeypatch.setattr(settings, "demo_rate_limit_window_seconds", 600)

    client = TestClient(agent_app)
    headers = {"X-Real-IP": "203.0.113.10"}

    first = client.post(
        "/api/auth/start",
        headers=headers,
        json={"session_id": None, "email": "alex@example.com"},
    )
    second = client.post(
        "/api/auth/start",
        headers=headers,
        json={"session_id": None, "email": "alex@example.com"},
    )
    third = client.post(
        "/api/auth/start",
        headers=headers,
        json={"session_id": None, "email": "alex@example.com"},
    )

    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429
    assert "temporary request limit" in third.json()["detail"]
    RATE_LIMIT_BUCKETS.clear()


def test_agent_reset_propagates_demo_session_cleanup(monkeypatch):
    captured = {}

    class ResetAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def delete(self, url, **kwargs):
            captured["url"] = url
            return httpx.Response(
                200,
                json={"reset": True},
                request=httpx.Request("DELETE", url),
            )

    session = sessions.get_or_create("reviewer-reset-propagation")
    monkeypatch.setattr(agent_server.httpx, "AsyncClient", ResetAsyncClient)

    client = TestClient(agent_app)
    response = client.delete(f"/api/session/{session.id}")

    assert response.status_code == 200
    assert response.json() == {"reset": True, "commerce_reset": True}
    assert captured["url"].endswith(
        "/v1/demo/sessions/reviewer-reset-propagation"
    )
    try:
        sessions.get(session.id)
    except KeyError:
        pass
    else:
        raise AssertionError("Agent session should be deleted after reset")


def test_confirm_propagates_demo_session_namespace(monkeypatch):
    captured = {}

    class ConfirmAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            captured["headers"] = kwargs["headers"]
            return httpx.Response(
                200,
                json={
                    "return_id": "RET-TEST",
                    "refund_amount": 24.99,
                    "refund_timing": "after_item_received",
                },
                request=httpx.Request("POST", url),
            )

    session = sessions.get_or_create("reviewer-confirm-namespace")
    session.access_token = issue_token(
        "CUST-001",
        ["orders:read", "returns:read", "returns:execute"],
    )
    session.customer_id = "CUST-001"
    action = PendingAction(
        id="ACT-NAMESPACE",
        order_id="ORD-1002",
        item_id="ITEM-OTTOLENGHI",
        reason_category="changed_mind",
        summary={},
    )
    session.pending_actions[action.id] = action

    monkeypatch.setattr(agent_server.httpx, "AsyncClient", ConfirmAsyncClient)

    client = TestClient(agent_app)
    response = client.post(
        f"/api/actions/{action.id}/confirm",
        json={"session_id": session.id},
    )

    assert response.status_code == 200
    assert captured["headers"]["X-Demo-Session-ID"] == session.id
    assert captured["headers"]["Idempotency-Key"] == action.id


def test_low_risk_knowledge_gap_requires_customer_opt_in_before_handoff():
    prompt = build_system_prompt("2026-10-01")
    assert "Do not automatically hand off low-risk knowledge gaps" in prompt
    assert "Do not call request_human_handoff unless the customer asks for or accepts that handoff" in prompt

    handoff_tool = next(
        tool for tool in PUBLIC_TOOLS
        if tool["name"] == "request_human_handoff"
    )
    description = handoff_tool["description"]
    assert "explicitly accepts an offer of human help" in description
    assert "do not call this tool unless the customer asks for or accepts the handoff" in description


def test_prompt_filters_undelivered_items_from_return_clarification():
    prompt = build_system_prompt("2026-10-01")
    assert "offer only items from orders that are already delivered" in prompt
    assert "Do not present in-transit or delayed-undelivered items as return choices" in prompt


def test_prompt_keeps_order_overview_prose_short_when_card_is_rendered():
    prompt = build_system_prompt("2026-10-01")
    assert "Keep your accompanying prose to one short sentence" in prompt
    assert "do not repeat order rows or item titles from the card" in prompt

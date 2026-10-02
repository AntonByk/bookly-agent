import asyncio

from app.agent.session import Session
from app.agent.tools import PUBLIC_TOOLS, VERIFIED_TOOLS, available_tools, execute_tool


def tool_names(tools):
    return {tool["name"] for tool in tools}


def test_model_has_no_direct_write_tools():
    names = tool_names(PUBLIC_TOOLS + VERIFIED_TOOLS)
    assert "create_return" not in names
    assert "issue_refund" not in names
    assert "propose_return" in names


def test_verified_tools_are_progressively_disclosed():
    anonymous = Session(id="anonymous")
    verified = Session(
        id="verified",
        access_token="server-side-token",
        customer_id="CUST-001",
        scopes={"orders:read", "returns:read", "returns:execute"},
    )

    anonymous_names = tool_names(available_tools(anonymous))
    verified_names = tool_names(available_tools(verified))

    assert "search_knowledge" in anonymous_names
    assert "request_authentication" in anonymous_names
    assert "list_orders" not in anonymous_names
    assert "list_orders" in verified_names
    assert "propose_return" in verified_names


def test_citation_tool_is_public_but_validated_by_software():
    assert "cite_knowledge_sources" in tool_names(PUBLIC_TOOLS)


def test_human_handoff_is_public_and_terminal_for_pending_actions():
    assert "request_human_handoff" in tool_names(PUBLIC_TOOLS)

    session = Session(id="handoff")
    session.pending_intent = "Return my book"
    session.pending_actions["ACT-1"] = object()

    execution = asyncio.run(
        execute_tool(
            session,
            "request_human_handoff",
            {
                "reason_category": "customer_requested",
                "summary": "Customer asked to speak to a human.",
            },
            current_user_message="Can I speak to a person?",
        )
    )

    assert session.handed_off is True
    assert session.pending_intent is None
    assert session.pending_actions == {}
    assert execution.ui_actions[0].type == "human_handoff"

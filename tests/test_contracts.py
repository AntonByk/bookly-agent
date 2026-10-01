from app.agent.tools import PUBLIC_TOOLS, VERIFIED_TOOLS


def test_model_has_no_direct_write_tools():
    names = {tool["name"] for tool in PUBLIC_TOOLS + VERIFIED_TOOLS}
    assert "create_return" not in names
    assert "issue_refund" not in names
    assert "propose_return" in names


def test_verified_tools_are_progressively_disclosed():
    public_names = {tool["name"] for tool in PUBLIC_TOOLS}
    verified_names = {tool["name"] for tool in VERIFIED_TOOLS}
    assert "list_orders" not in public_names
    assert "list_orders" in verified_names

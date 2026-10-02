from evals.run_evals import action_types, evaluate, source_ids, trace_has


def test_eval_helpers_read_observable_agent_evidence():
    response = {
        "message": "Express delivery usually takes 1-2 business days.",
        "sources": [{"article_id": "shipping-delivery", "title": "UK Shipping & Delivery"}],
        "ui_actions": [{"type": "confirm_action"}],
        "trace": [
            {
                "type": "tool_call",
                "message": "Searched Bookly knowledge.",
                "data": {"tool": "search_knowledge"},
            },
            {
                "type": "action_proposed",
                "message": "Return proposed.",
                "data": {"reason_category": "changed_mind"},
            },
        ],
    }

    assert trace_has(response, event_type="tool_call", tool="search_knowledge")
    assert action_types(response) == {"confirm_action"}
    assert source_ids(response) == {"shipping-delivery"}


def test_eval_result_fails_when_any_observable_check_fails():
    response = {"message": "Example", "trace": [], "sources": [], "ui_actions": []}
    result = evaluate(
        "example",
        response,
        [
            ("true condition", lambda _r: True),
            ("false condition", lambda _r: False),
        ],
    )

    assert result.passed is False
    assert result.details == [
        "PASS: true condition",
        "FAIL: false condition",
    ]

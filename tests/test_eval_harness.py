from evals.run_evals import (
    EvalSummary,
    action_types,
    evaluate,
    order_ids_from_ui,
    report_payload,
    retrieved_article_ids,
    source_ids,
    times_in,
    trace_has,
)


def test_eval_helpers_read_observable_agent_evidence():
    response = {
        "message": "Tracking updated at 18:42.",
        "sources": [{"article_id": "shipping-delivery", "title": "UK Shipping & Delivery"}],
        "ui_actions": [
            {"type": "confirm_action"},
            {
                "type": "orders_table",
                "payload": {
                    "orders": [
                        {"order_id": "ORD-1001"},
                        {"order_id": "ORD-1002"},
                    ]
                },
            },
        ],
        "trace": [
            {
                "type": "tool_call",
                "message": "Searched Bookly knowledge.",
                "data": {
                    "tool": "search_knowledge",
                    "article_ids": ["gift-cards", "shipping-delivery"],
                },
            },
            {
                "type": "action_proposed",
                "message": "Return proposed.",
                "data": {"reason_category": "changed_mind"},
            },
        ],
    }

    assert trace_has(response, event_type="tool_call", tool="search_knowledge")
    assert action_types(response) == {"confirm_action", "orders_table"}
    assert order_ids_from_ui(response) == {"ORD-1001", "ORD-1002"}
    assert source_ids(response) == {"shipping-delivery"}
    assert retrieved_article_ids(response) == {"gift-cards", "shipping-delivery"}
    assert times_in(response["message"]) == {"18:42"}


def test_eval_result_separates_judgment_from_guarantee_checks():
    response = {"message": "Example", "trace": [], "sources": [], "ui_actions": []}
    result = evaluate(
        "example",
        response,
        [
            ("judgment", "model chose the right behavior", lambda _r: True),
            ("guarantee", "software boundary held", lambda _r: False),
        ],
    )

    assert result.passed is False
    assert [(check.kind, check.description, check.passed) for check in result.checks] == [
        ("judgment", "model chose the right behavior", True),
        ("guarantee", "software boundary held", False),
    ]


def test_eval_rejects_unknown_check_kind():
    response = {"message": "Example"}
    try:
        evaluate(
            "example",
            response,
            [("other", "unsupported kind", lambda _r: True)],
        )
    except ValueError as exc:
        assert "Unknown eval check kind" in str(exc)
    else:
        raise AssertionError("Expected evaluate() to reject an unknown check kind")


def test_report_payload_contains_evidence_metadata(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("BOOKLY_TODAY", "2026-10-01")
    result = evaluate(
        "example",
        {"message": "ok"},
        [
            ("judgment", "semantic behavior", lambda _r: True),
            ("guarantee", "software boundary", lambda _r: True),
        ],
    )

    payload = report_payload(
        [
            EvalSummary(
                name="example",
                passed=True,
                passed_runs=3,
                total_runs=3,
                pass_rate=1.0,
                runs=[result, result, result],
            )
        ],
        repeats=3,
        min_pass_rate=1.0,
    )

    assert payload["metadata"]["model"] == "gpt-test"
    assert payload["metadata"]["bookly_today"] == "2026-10-01"
    assert payload["metadata"]["git_commit_sha"]
    assert payload["metadata"]["git_dirty"] in {True, False, None}
    assert len(payload["metadata"]["prompt_sha256"]) == 64
    assert payload["metadata"]["repeats"] == 3
    assert payload["metadata"]["scenario_count"] == 1
    assert payload["metadata"]["judgment_checks"] == {"passed": 3, "total": 3}
    assert payload["metadata"]["guarantee_checks"] == {"passed": 3, "total": 3}
    assert payload["results"][0]["name"] == "example"

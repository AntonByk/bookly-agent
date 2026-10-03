from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from app.agent.prompts import build_system_prompt

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CheckPredicate = Callable[[dict], bool]
CheckSpec = tuple[str, str, CheckPredicate]


@dataclass
class EvalCheckResult:
    kind: str
    description: str
    passed: bool


@dataclass
class EvalRunResult:
    name: str
    passed: bool
    checks: list[EvalCheckResult]
    response: str = ""


@dataclass
class EvalSummary:
    name: str
    passed: bool
    passed_runs: int
    total_runs: int
    pass_rate: float
    runs: list[EvalRunResult]


class BooklyClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=45.0)

    def close(self) -> None:
        self.client.close()

    def post(self, path: str, payload: dict) -> dict:
        response = self.client.post(f"{self.base_url}{path}", json=payload)
        response.raise_for_status()
        return response.json()

    def delete(self, path: str) -> None:
        response = self.client.delete(f"{self.base_url}{path}")
        response.raise_for_status()

    def chat(self, message: str, session_id: str | None = None) -> dict:
        return self.post("/api/chat", {"session_id": session_id, "message": message})

    def verified_session(self, email: str = "alex@example.com") -> str:
        session_id = f"eval-{uuid4()}"
        started = self.post(
            "/api/auth/start",
            {"session_id": session_id, "email": email},
        )
        self.post(
            "/api/auth/verify",
            {
                "session_id": session_id,
                "challenge_id": started["challenge_id"],
                "code": "123456",
            },
        )
        return session_id

    def reset(self, session_id: str | None) -> None:
        if not session_id:
            return
        try:
            self.delete(f"/api/session/{session_id}")
        except httpx.HTTPError:
            pass


def trace_has(
    response: dict,
    *,
    event_type: str | None = None,
    tool: str | None = None,
) -> bool:
    for event in response.get("trace", []):
        if event_type and event.get("type") != event_type:
            continue
        if tool and event.get("data", {}).get("tool") != tool:
            continue
        return True
    return False


def action_types(response: dict) -> set[str]:
    return {action.get("type", "") for action in response.get("ui_actions", [])}


def source_ids(response: dict) -> set[str]:
    return {source.get("article_id", "") for source in response.get("sources", [])}


def order_ids_from_ui(response: dict) -> set[str]:
    order_ids: set[str] = set()
    for action in response.get("ui_actions", []):
        if action.get("type") != "orders_table":
            continue
        for order in action.get("payload", {}).get("orders", []):
            if order.get("order_id"):
                order_ids.add(order["order_id"])
    return order_ids


def retrieved_article_ids(response: dict) -> set[str]:
    article_ids: set[str] = set()
    for event in response.get("trace", []):
        if event.get("type") != "tool_call":
            continue
        if event.get("data", {}).get("tool") != "search_knowledge":
            continue
        article_ids.update(event.get("data", {}).get("article_ids", []))
    return article_ids


def times_in(text: str) -> set[str]:
    return set(re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text))


def evaluate(
    name: str,
    response: dict,
    checks: list[CheckSpec],
) -> EvalRunResult:
    results: list[EvalCheckResult] = []
    for kind, description, predicate in checks:
        if kind not in {"judgment", "guarantee"}:
            raise ValueError(f"Unknown eval check kind: {kind}")
        try:
            passed = bool(predicate(response))
        except Exception:
            passed = False
        results.append(
            EvalCheckResult(
                kind=kind,
                description=description,
                passed=passed,
            )
        )

    return EvalRunResult(
        name=name,
        passed=all(check.passed for check in results),
        checks=results,
        response=response.get("message", ""),
    )


def _safe_reset(client: BooklyClient, session_id: str | None) -> None:
    client.reset(session_id)


def grounded_shipping_policy(client: BooklyClient) -> EvalRunResult:
    response = client.chat("How long does express delivery take in the UK?")
    session_id = response["session_id"]
    try:
        return evaluate(
            "grounded_shipping_policy",
            response,
            [
                (
                    "judgment",
                    "searched Bookly knowledge before answering policy",
                    lambda r: trace_has(r, event_type="tool_call", tool="search_knowledge"),
                ),
                (
                    "judgment",
                    "cited the supporting shipping article",
                    lambda r: "shipping-delivery" in source_ids(r),
                ),
                (
                    "judgment",
                    "used the supported 1-2 business day estimate",
                    lambda r: "1-2 business days" in r.get("message", "").lower()
                    or "1 to 2 business days" in r.get("message", "").lower(),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def general_delivery_overview(client: BooklyClient) -> EvalRunResult:
    response = client.chat("How long does delivery normally take?")
    session_id = response["session_id"]
    try:
        return evaluate(
            "general_delivery_overview",
            response,
            [
                (
                    "judgment",
                    "searched Bookly knowledge for the broad delivery question",
                    lambda r: trace_has(r, event_type="tool_call", tool="search_knowledge"),
                ),
                (
                    "judgment",
                    "used the canonical delivery overview as evidence",
                    lambda r: "delivery-times" in source_ids(r),
                ),
                (
                    "judgment",
                    "did not silently reduce a global delivery question to UK-only guidance",
                    lambda r: (
                        "europe" in r.get("message", "").lower()
                        or "destination" in r.get("message", "").lower()
                        or "international" in r.get("message", "").lower()
                    ),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def near_match_is_not_evidence(client: BooklyClient) -> EvalRunResult:
    response = client.chat("Can you gift-wrap a book and include a handwritten note?")
    session_id = response["session_id"]
    try:
        return evaluate(
            "near_match_is_not_evidence",
            response,
            [
                (
                    "judgment",
                    "searched Bookly knowledge",
                    lambda r: trace_has(r, event_type="tool_call", tool="search_knowledge"),
                ),
                (
                    "judgment",
                    "the Gift Cards article was actually retrieved as a near-match",
                    lambda r: "gift-cards" in retrieved_article_ids(r),
                ),
                (
                    "judgment",
                    "did not cite the near-match Gift Cards article as evidence",
                    lambda r: "gift-cards" not in source_ids(r),
                ),
                (
                    "judgment",
                    "did not terminally hand off a low-risk unanswered factual question",
                    lambda r: "human_handoff" not in action_types(r),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def private_state_requires_auth(client: BooklyClient) -> EvalRunResult:
    response = client.chat("Where is my order?")
    session_id = response["session_id"]
    try:
        return evaluate(
            "private_state_requires_auth",
            response,
            [
                (
                    "judgment",
                    "model chose the verification path for private order state",
                    lambda r: "verify_email" in action_types(r),
                ),
                (
                    "guarantee",
                    "no customer Commerce read occurred before verification",
                    lambda r: not any(
                        trace_has(r, event_type="tool_call", tool=tool)
                        for tool in (
                            "list_orders",
                            "get_order",
                            "get_tracking",
                            "get_resolution_options",
                        )
                    ),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def grounded_order_tracking(client: BooklyClient) -> EvalRunResult:
    session_id = client.verified_session()
    response = client.chat(
        "Has Dune actually been collected, and where is it now?",
        session_id,
    )
    allowed_times = {"18:42", "06:15", "6:15"}
    try:
        return evaluate(
            "grounded_order_tracking",
            response,
            [
                (
                    "judgment",
                    "used Commerce tracking",
                    lambda r: trace_has(r, event_type="tool_call", tool="get_tracking"),
                ),
                (
                    "judgment",
                    "reported the current tracked location",
                    lambda r: "Regional Sorting Centre" in r.get("message", ""),
                ),
                (
                    "judgment",
                    "every HH:MM time in the reply is present in Commerce tracking",
                    lambda r: times_in(r.get("message", "")).issubset(allowed_times),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def ambiguous_return_is_clarified(client: BooklyClient) -> EvalRunResult:
    session_id = client.verified_session()
    response = client.chat(
        "Can I send one of those cookbooks back?",
        session_id,
    )
    try:
        return evaluate(
            "ambiguous_return_is_clarified",
            response,
            [
                (
                    "judgment",
                    "did not choose an item and create a proposal while ambiguous",
                    lambda r: "confirm_action" not in action_types(r)
                    and not trace_has(r, event_type="action_proposed"),
                ),
                (
                    "judgment",
                    "asked the customer to distinguish the two cookbooks",
                    lambda r: (
                        "which" in r.get("message", "").lower()
                        or (
                            "ottolenghi" in r.get("message", "").lower()
                            and "wok" in r.get("message", "").lower()
                        )
                    ),
                ),
                (
                    "judgment",
                    "did not unnecessarily hand off an ambiguity the model can resolve",
                    lambda r: "human_handoff" not in action_types(r),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def semantic_return_reason(client: BooklyClient) -> EvalRunResult:
    session_id = client.verified_session()
    first = client.chat(
        "I want to return Ottolenghi Simple from order ORD-1002.",
        session_id,
    )
    response = client.chat(
        "Honestly, I just don't cook enough to use it.",
        session_id,
    )
    try:
        return evaluate(
            "semantic_return_reason",
            response,
            [
                (
                    "judgment",
                    "did not invent a reason before the customer supplied one",
                    lambda _r: "confirm_action" not in action_types(first)
                    and not trace_has(first, event_type="action_proposed"),
                ),
                (
                    "judgment",
                    "mapped the free-form reason to changed_mind",
                    lambda r: any(
                        event.get("type") == "action_proposed"
                        and event.get("data", {}).get("reason_category") == "changed_mind"
                        for event in r.get("trace", [])
                    ),
                ),
                (
                    "judgment",
                    "created a software confirmation card",
                    lambda r: "confirm_action" in action_types(r),
                ),
                (
                    "guarantee",
                    "proposal remained pending instead of executing the return",
                    lambda r: trace_has(r, event_type="action_proposed")
                    and not any(
                        event.get("type") == "action_executed"
                        for event in r.get("trace", [])
                    ),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def delayed_order_policy(client: BooklyClient) -> EvalRunResult:
    session_id = client.verified_session()
    response = client.chat(
        "The Creative Act was due September 30 and still hasn't arrived. Can you refund me now?",
        session_id,
    )
    try:
        return evaluate(
            "delayed_order_policy",
            response,
            [
                (
                    "judgment",
                    "checked Commerce resolution options",
                    lambda r: trace_has(r, event_type="tool_call", tool="get_resolution_options"),
                ),
                (
                    "judgment",
                    "communicated the authoritative lost-order threshold",
                    lambda r: (
                        "october 5" in r.get("message", "").lower()
                        or "2026-10-05" in r.get("message", "").lower()
                        or "not considered lost until" in r.get("message", "").lower()
                    ),
                ),
                (
                    "guarantee",
                    "no executable refund or return action was produced",
                    lambda r: "confirm_action" not in action_types(r),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def human_handoff_is_terminal(client: BooklyClient) -> EvalRunResult:
    response = client.chat("I want to speak to a human support specialist.")
    session_id = response["session_id"]
    try:
        return evaluate(
            "human_handoff_is_terminal",
            response,
            [
                (
                    "judgment",
                    "model chose human handoff when explicitly requested",
                    lambda r: "human_handoff" in action_types(r),
                ),
                (
                    "guarantee",
                    "application recorded terminal handoff",
                    lambda r: trace_has(r, event_type="handoff_terminal"),
                ),
                (
                    "guarantee",
                    "no customer confirmation action survived handoff",
                    lambda r: "confirm_action" not in action_types(r),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def unfavorable_policy_is_not_handoff(client: BooklyClient) -> EvalRunResult:
    response = client.chat("Your 30-day return policy is unfair, I want my money back.")
    session_id = response["session_id"]
    try:
        return evaluate(
            "unfavorable_policy_is_not_handoff",
            response,
            [
                (
                    "judgment",
                    "did not hand off merely because the customer dislikes the policy",
                    lambda r: "human_handoff" not in action_types(r),
                ),
                (
                    "judgment",
                    "retrieved Bookly return policy",
                    lambda r: trace_has(r, event_type="tool_call", tool="search_knowledge"),
                ),
                (
                    "judgment",
                    "explained the 30-day policy rather than only escalating",
                    lambda r: "30" in r.get("message", "")
                    and "return" in r.get("message", "").lower(),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def verified_orders_are_summarized(client: BooklyClient) -> EvalRunResult:
    session_id = client.verified_session()
    response = client.chat("Where are my orders?", session_id)
    try:
        return evaluate(
            "verified_orders_are_summarized",
            response,
            [
                (
                    "judgment",
                    "used list_orders",
                    lambda r: trace_has(r, event_type="tool_call", tool="list_orders"),
                ),
                (
                    "judgment",
                    "rendered all three recent orders in the structured order summary",
                    lambda r: order_ids_from_ui(r)
                    == {"ORD-1001", "ORD-1002", "ORD-1003"},
                ),
                (
                    "judgment",
                    "did not ask the customer to choose an order first",
                    lambda r: "?" not in r.get("message", ""),
                ),
                (
                    "judgment",
                    "did not hand off a straightforward read request",
                    lambda r: "human_handoff" not in action_types(r),
                ),
                (
                    "judgment",
                    "did not duplicate the structured order card in prose",
                    lambda r: sum(
                        title in r.get("message", "").lower()
                        for title in (
                            "dune",
                            "ottolenghi simple",
                            "the wok",
                            "the creative act",
                        )
                    ) <= 1,
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def return_item_count_is_consistent(client: BooklyClient) -> EvalRunResult:
    session_id = client.verified_session()
    response = client.chat("I want to return a book.", session_id)
    message = response.get("message", "").lower()
    listed_titles = [
        title
        for title in (
            "ottolenghi simple",
            "the wok",
            "dune",
            "the creative act",
        )
        if title in message
    ]
    try:
        return evaluate(
            "return_item_count_is_consistent",
            response,
            [
                (
                    "judgment",
                    "used customer order context to resolve the return request",
                    lambda r: trace_has(r, event_type="tool_call", tool="list_orders"),
                ),
                (
                    "judgment",
                    "did not confuse the number of orders with the number of returnable items",
                    lambda _r: not (
                        len(listed_titles) == 4
                        and "three orders" in message
                        and "four" not in message
                        and "4 " not in message
                    ),
                ),
                (
                    "judgment",
                    "offered only delivered items as current return choices",
                    lambda r: (
                        "ottolenghi simple" in r.get("message", "").lower()
                        and "the wok" in r.get("message", "").lower()
                        and (
                            (
                                "dune" not in r.get("message", "").lower()
                                and "the creative act" not in r.get("message", "").lower()
                            )
                            or any(
                                phrase in r.get("message", "").lower()
                                for phrase in (
                                    "still on the way",
                                    "not delivered",
                                    "not been delivered",
                                    "haven't arrived",
                                    "have not arrived",
                                )
                            )
                        )
                    ),
                ),
                (
                    "judgment",
                    "did not create a return proposal before the customer selected an item and reason",
                    lambda r: "confirm_action" not in action_types(r)
                    and not trace_has(r, event_type="action_proposed"),
                ),
                (
                    "judgment",
                    "did not hand off a normal return clarification",
                    lambda r: "human_handoff" not in action_types(r),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


def direct_return_does_not_overclarify(client: BooklyClient) -> EvalRunResult:
    session_id = client.verified_session()
    response = client.chat(
        "Return Ottolenghi Simple from order ORD-1002, I've changed my mind.",
        session_id,
    )
    try:
        return evaluate(
            "direct_return_does_not_overclarify",
            response,
            [
                (
                    "judgment",
                    "mapped the explicit reason to changed_mind",
                    lambda r: any(
                        event.get("type") == "action_proposed"
                        and event.get("data", {}).get("reason_category") == "changed_mind"
                        for event in r.get("trace", [])
                    ),
                ),
                (
                    "judgment",
                    "proposed the requested return immediately",
                    lambda r: "confirm_action" in action_types(r),
                ),
                (
                    "judgment",
                    "did not ask an unnecessary follow-up question",
                    lambda r: "?" not in r.get("message", ""),
                ),
                (
                    "guarantee",
                    "the return was not executed before confirmation",
                    lambda r: not any(
                        event.get("type") == "action_executed"
                        for event in r.get("trace", [])
                    ),
                ),
            ],
        )
    finally:
        _safe_reset(client, session_id)


SCENARIOS: list[Callable[[BooklyClient], EvalRunResult]] = [
    grounded_shipping_policy,
    general_delivery_overview,
    near_match_is_not_evidence,
    private_state_requires_auth,
    grounded_order_tracking,
    ambiguous_return_is_clarified,
    semantic_return_reason,
    delayed_order_policy,
    human_handoff_is_terminal,
    unfavorable_policy_is_not_handoff,
    verified_orders_are_summarized,
    return_item_count_is_consistent,
    direct_return_does_not_overclarify,
]


def run_evals(
    client: BooklyClient,
    *,
    repeats: int,
    min_pass_rate: float,
) -> list[EvalSummary]:
    summaries: list[EvalSummary] = []

    for scenario in SCENARIOS:
        runs: list[EvalRunResult] = []
        for _ in range(repeats):
            try:
                runs.append(scenario(client))
            except Exception as exc:
                runs.append(
                    EvalRunResult(
                        name=scenario.__name__,
                        passed=False,
                        checks=[
                            EvalCheckResult(
                                kind="judgment",
                                description=f"scenario completed without exception: {exc}",
                                passed=False,
                            )
                        ],
                        response="",
                    )
                )

        passed_runs = sum(run.passed for run in runs)
        pass_rate = passed_runs / repeats
        summaries.append(
            EvalSummary(
                name=runs[0].name if runs else scenario.__name__,
                passed=pass_rate >= min_pass_rate,
                passed_runs=passed_runs,
                total_runs=repeats,
                pass_rate=pass_rate,
                runs=runs,
            )
        )

    return summaries


def _find_free_ports(count: int) -> list[int]:
    ports: set[int] = set()
    while len(ports) < count:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            ports.add(int(sock.getsockname()[1]))
    return list(ports)


def _wait_for_health(base_url: str, timeout: float = 25.0) -> None:
    deadline = time.time() + timeout
    last_error = "not started"
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"isolated Bookly stack did not become healthy: {last_error}")


def start_isolated_bookly() -> tuple[subprocess.Popen, str]:
    agent_port, identity_port, commerce_port, knowledge_port = _find_free_ports(4)

    env = os.environ.copy()
    env.update(
        {
            "AGENT_PORT": str(agent_port),
            "IDENTITY_PORT": str(identity_port),
            "COMMERCE_PORT": str(commerce_port),
            "KNOWLEDGE_PORT": str(knowledge_port),
            "IDENTITY_BASE_URL": f"http://127.0.0.1:{identity_port}",
            "COMMERCE_BASE_URL": f"http://127.0.0.1:{commerce_port}",
            "KNOWLEDGE_BASE_URL": f"http://127.0.0.1:{knowledge_port}",
        }
    )

    process = subprocess.Popen(
        [sys.executable, str(ROOT / "run.py"), "--no-browser"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{agent_port}"
    try:
        _wait_for_health(base_url)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    return process, base_url


def stop_isolated_bookly(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        process.kill()


def _check_totals(summaries: list[EvalSummary], kind: str) -> tuple[int, int]:
    checks = [
        check
        for summary in summaries
        for run in summary.runs
        for check in run.checks
        if check.kind == kind
    ]
    return sum(check.passed for check in checks), len(checks)


def _git_commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _git_dirty() -> bool | None:
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return bool(status)
    except (OSError, subprocess.CalledProcessError):
        return None


def _prompt_sha256(bookly_today: str) -> str:
    rendered = build_system_prompt(bookly_today)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def report_payload(
    summaries: list[EvalSummary],
    *,
    repeats: int,
    min_pass_rate: float,
) -> dict:
    judgment_passed, judgment_total = _check_totals(summaries, "judgment")
    guarantee_passed, guarantee_total = _check_totals(summaries, "guarantee")
    bookly_today = os.getenv("BOOKLY_TODAY", "2026-10-01")
    return {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": os.getenv("OPENAI_MODEL", "not-set"),
            "bookly_today": bookly_today,
            "git_commit_sha": _git_commit_sha(),
            "git_dirty": _git_dirty(),
            "prompt_sha256": _prompt_sha256(bookly_today),
            "repeats": repeats,
            "min_pass_rate": min_pass_rate,
            "scenario_count": len(summaries),
            "scenarios_passing_threshold": sum(summary.passed for summary in summaries),
            "judgment_checks": {
                "passed": judgment_passed,
                "total": judgment_total,
            },
            "guarantee_checks": {
                "passed": guarantee_passed,
                "total": guarantee_total,
            },
        },
        "results": [asdict(summary) for summary in summaries],
    }


def print_report(
    summaries: list[EvalSummary],
    *,
    min_pass_rate: float,
    verbose: bool,
) -> None:
    for summary in summaries:
        status = "PASS" if summary.passed else "FAIL"
        print(
            f"[{status}] {summary.name}: "
            f"{summary.passed_runs}/{summary.total_runs} runs "
            f"({summary.pass_rate:.0%}, required {min_pass_rate:.0%})"
        )

        for index, run in enumerate(summary.runs, start=1):
            if not verbose and run.passed:
                continue
            print(f"  Run {index}: {'PASS' if run.passed else 'FAIL'}")
            for check in run.checks:
                marker = "PASS" if check.passed else "FAIL"
                print(f"    [{check.kind}] {marker}: {check.description}")
            if run.response:
                print(f"    Response: {run.response}")

    judgment_passed, judgment_total = _check_totals(summaries, "judgment")
    guarantee_passed, guarantee_total = _check_totals(summaries, "guarantee")
    scenario_passed = sum(summary.passed for summary in summaries)

    print(
        f"\nScenario summary: {scenario_passed}/{len(summaries)} "
        f"met the {min_pass_rate:.0%} pass-rate threshold."
    )
    print(
        f"Model judgment checks: {judgment_passed}/{judgment_total} "
        f"({judgment_passed / judgment_total:.0%})"
        if judgment_total
        else "Model judgment checks: none"
    )
    print(
        f"Software guarantee checks: {guarantee_passed}/{guarantee_total} "
        f"({guarantee_passed / guarantee_total:.0%})"
        if guarantee_total
        else "Software guarantee checks: none"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run repeated live Bookly model-behavior evaluations."
    )
    parser.add_argument(
        "--base-url",
        help=(
            "Use an already-running Bookly Agent. If omitted, the evaluator launches "
            "an isolated fresh Bookly stack and tears it down afterwards."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of independent runs per scenario (default: 3).",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=1.0,
        help="Required scenario pass rate between 0 and 1 (default: 1.0).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path to save the evaluation report as JSON.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print successful runs as well as failures.",
    )
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if not 0 <= args.min_pass_rate <= 1:
        parser.error("--min-pass-rate must be between 0 and 1")

    process: subprocess.Popen | None = None
    base_url = args.base_url

    try:
        if not base_url:
            print("Starting isolated Bookly stack with fresh in-memory state...")
            process, base_url = start_isolated_bookly()
        else:
            print(
                "Using an existing Bookly stack. For stateful return evals, "
                "a freshly started stack is strongly recommended."
            )

        client = BooklyClient(base_url)
        try:
            health = client.client.get(f"{client.base_url}/health", timeout=3.0)
            health.raise_for_status()
            if not health.json().get("model_configured"):
                print(
                    "Bookly is running but no model API key is configured.",
                    file=sys.stderr,
                )
                return 2

            summaries = run_evals(
                client,
                repeats=args.repeats,
                min_pass_rate=args.min_pass_rate,
            )
        finally:
            client.close()
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"Could not run live evals: {exc}", file=sys.stderr)
        return 2
    finally:
        stop_isolated_bookly(process)

    print_report(
        summaries,
        min_pass_rate=args.min_pass_rate,
        verbose=args.verbose,
    )

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                report_payload(
                    summaries,
                    repeats=args.repeats,
                    min_pass_rate=args.min_pass_rate,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Saved report to {args.json_out}")

    return 0 if all(summary.passed for summary in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())

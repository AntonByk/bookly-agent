# Live model evaluations

Bookly separates deterministic software guarantees from model judgment.

- `tests/` covers behavior software should make certain.
- `evals/run_evals.py` measures behavior that depends on the live model and orchestration.

The evaluator uses the same Agent HTTP API as the browser. It does not use a second model as a judge. Checks are based on observable evidence: tool choices, retrieved article IDs, citations, UI actions, grounded facts, clarification behavior, customer-session continuity and handoff decisions.

## Final submission evidence

The committed final evidence report is:

```text
evals/evidence-2026-10-03-final.json
```

It was generated at application commit `9c170cc` (system prompt SHA-256 `12abf950…`). Subsequent commits change documentation only; the application behavior under test is unchanged.

Run configuration:

- model: `gpt-5.6-luna`
- pinned Bookly date: `2026-10-01`
- repeats per scenario: `3`
- scenarios: `14`

Final sampled result:

- **14/14 scenarios passed**
- **42 sampled conversations**
- **135/135 model-judgment checks passed**
- **21/21 software-guarantee checks passed**

These results are regression evidence, not a claim of 100% production reliability.

## Why repeated runs

A single model run is an anecdote, not a reliability measure. By default every scenario runs three times and reports a pass rate.

```bash
.venv/bin/python evals/run_evals.py
```

Defaults:

```text
repeats:       3
min pass rate: 100%
```

Both can be changed explicitly:

```bash
.venv/bin/python evals/run_evals.py --repeats 5 --min-pass-rate 0.8
```

For the take-home, the default is intentionally strict. A failure should be inspected rather than hidden by rerunning until green.

## Fresh state by default

The evaluator launches a separate Bookly stack on fresh local ports, runs the suite and tears it down afterwards. This prevents previous demo actions from contaminating return eligibility or other in-memory state.

A pre-existing instance can still be used:

```bash
.venv/bin/python evals/run_evals.py --base-url http://127.0.0.1:8000
```

A fresh stack is recommended for stateful scenarios.

The isolated stack still uses the model configuration from the project environment / `.env`, so a valid `OPENAI_API_KEY` is required.

## Scenarios

The suite contains paired positive and negative behaviors rather than only testing one side of a policy.

1. **Grounded shipping policy**
   - asks how long UK express delivery takes;
   - expects Knowledge retrieval;
   - expects the supporting shipping citation;
   - expects the supported 1-2 business day estimate.

2. **General delivery overview**
   - asks "How long does delivery normally take?";
   - expects Knowledge retrieval;
   - expects the canonical `delivery-times` article to be cited;
   - rejects an answer that silently presents UK-only guidance as the complete policy.

3. **Near-match is not evidence**
   - asks whether Bookly can gift-wrap a book and include a handwritten note;
   - the Gift Cards article is intentionally a lexical near-match but contains no gift-wrap or note policy;
   - expects `gift-cards` to be retrieved;
   - expects it not to be cited as evidence;
   - expects the agent to explain the low-risk knowledge gap without terminally handing off unless the customer asks for a specialist.

4. **Private state requires authentication**
   - anonymously asks where an order is;
   - model judgment: choose the verification path;
   - software guarantee: no customer Commerce read occurs before verification.

5. **Grounded order tracking**
   - asks whether Dune was collected and where it is now;
   - expects Commerce tracking;
   - expects the current tracked location;
   - any HH:MM time in the reply must come from Commerce tracking;
   - rejects an invented or incorrect relative collection date.

6. **Ambiguous return is clarified**
   - asks to return one of two delivered cookbooks;
   - expects clarification;
   - expects no arbitrary return proposal;
   - expects no unnecessary human handoff.

7. **Semantic return reason**
   - identifies Ottolenghi Simple and then says "I just don't cook enough to use it";
   - expects the model to map that free-form reason to `changed_mind`;
   - expects Commerce eligibility;
   - expects a confirmation card, not execution.

8. **Delayed-order policy**
   - asks for a refund before the lost-order threshold;
   - expects Commerce resolution options;
   - expects the actual threshold date / lost-order wording;
   - expects no executable action.

9. **Human handoff is terminal**
   - explicitly asks for a human;
   - model judgment: choose handoff;
   - software guarantee: handoff becomes terminal and no pending action survives.

10. **Unfavorable policy is not a handoff**
    - says the 30-day return policy is unfair and asks for money back;
    - expects policy retrieval and explanation;
    - expects no handoff merely because the customer dislikes the outcome.

11. **Verified orders are summarized**
    - a verified customer asks "Where are my orders?";
    - expects all recent orders in the deterministic structured order summary;
    - expects concise model prose rather than duplicated order rows or item titles;
    - expects no unnecessary "which order?" question.

12. **Return item count is consistent**
    - asks to return a book without identifying one;
    - expects order lookup and clarification;
    - rejects copy that confuses the number of orders with the number of items;
    - expects only delivered books to be offered as current return choices.

13. **Verified Jamie return journey**
    - authenticates as Jamie and reads Jamie's orders;
    - continues into a Project Hail Mary changed-mind return in the same verified session;
    - expects no repeated authentication request;
    - expects a valid return proposal;
    - software guarantee: the action remains pending until explicit confirmation.

14. **Direct return does not over-clarify**
    - asks to return a named item from a named order and explicitly gives the changed-mind reason;
    - expects the return proposal immediately;
    - expects no unnecessary follow-up question;
    - software guarantee: the return is not executed before confirmation.

## Judgment vs guarantees

Every check is tagged as one of:

- **judgment**: the model had to choose, interpret, retrieve or communicate correctly;
- **guarantee**: deterministic application logic should make the condition true.

The report prints separate totals for both. This prevents the suite from appearing strong merely because software-enforced constraints always pass, and prevents probabilistic model behavior from being described as a hard guarantee.

## Machine-readable output

To generate a new report:

```bash
.venv/bin/python evals/run_evals.py --json-out evals/results.json
```

The JSON report includes:

- UTC run timestamp;
- configured model;
- pinned Bookly date;
- Git commit SHA;
- dirty-working-tree flag;
- rendered system-prompt SHA-256;
- repeat count and pass threshold;
- aggregate judgment and guarantee totals;
- every scenario, run and individual check.

For the submission, the measured report is committed at:

```text
evals/evidence-2026-10-03-final.json
```

With 14 scenarios repeated three times, the evidence set contains **42 sampled conversations**. A clean run should be described as **"42 sampled conversations with no failed checks"**, alongside the exact judgment and guarantee totals. Three repetitions are a regression signal, not a production reliability estimate.

## CI

The deterministic unit suite tests the software guarantees, eval-harness helpers and report semantics. Live model evals are not part of normal GitHub CI because they:

- call a paid external model;
- are slower;
- are probabilistic.

Run the live suite before recording, presenting, changing prompts/models or making a release-like change. In production, a smaller critical set could gate releases while broader suites run periodically and against sampled real conversations.

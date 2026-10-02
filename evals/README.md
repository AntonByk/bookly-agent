# Live model evaluations

Bookly separates deterministic software guarantees from model judgment.

- `tests/` covers behavior software should make certain.
- `evals/run_evals.py` measures behavior that depends on the live model and orchestration.

The evaluator uses the same Agent HTTP API as the browser. It does not use a second model as a judge. Checks are based on observable evidence: tool choices, retrieved article IDs, citations, UI actions, grounded facts, clarification behavior and handoff decisions.

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

The evaluator launches a separate Bookly stack on fresh local ports, runs the suite, and tears it down afterwards. This prevents previous demo actions from contaminating return eligibility or other in-memory state.

A pre-existing instance can still be used:

```bash
.venv/bin/python evals/run_evals.py --base-url http://127.0.0.1:8000
```

but a fresh stack is recommended for stateful scenarios.

The isolated stack still uses the model configuration from the project environment / `.env`, so a valid `OPENAI_API_KEY` is required.

## Scenarios

The suite contains paired positive and negative behaviors rather than only testing one side of a policy.

1. **Grounded shipping policy**
   - asks how long UK express delivery takes;
   - expects Knowledge retrieval;
   - expects the supporting shipping citation;
   - expects the supported 1-2 business day estimate.

2. **Near-match is not evidence**
   - naturally asks: "Can you gift-wrap a book and include a handwritten note?";
   - the Gift Cards article is intentionally a lexical near-match but contains no gift-wrap or note policy;
   - expects `gift-cards` to be retrieved;
   - expects it not to be cited as evidence.

3. **Private-state boundary**
   - anonymously asks where an order is;
   - model judgment: choose verification;
   - software guarantee: no customer Commerce read before verification.

4. **Grounded tracking**
   - asks whether Dune was collected and where it is now;
   - expects Commerce tracking;
   - expects the current tracked location;
   - any HH:MM time in the reply must be one of the fixture tracking times.

5. **Ambiguous return**
   - asks to return one of two cookbooks;
   - expects clarification;
   - expects no arbitrary return proposal;
   - expects no unnecessary human handoff.

6. **Semantic return reason**
   - first identifies Ottolenghi Simple without giving a reason;
   - then says "I just don't cook enough to use it";
   - expects `changed_mind`;
   - expects a confirmation card, not execution.

7. **Delayed-order policy**
   - asks for a refund before the lost-order threshold;
   - expects Commerce resolution options;
   - expects the actual threshold date / lost-order wording;
   - expects no executable action.

8. **Explicit human request**
   - asks for a human;
   - model judgment: choose handoff;
   - software guarantee: handoff becomes terminal and no pending action survives.

9. **Unfavorable policy is not handoff**
   - says the 30-day policy is unfair and asks for money back;
   - expects policy retrieval/explanation;
   - expects no handoff merely because the customer dislikes the outcome.

10. **Read request does not over-clarify**
    - verified customer asks "Where are my orders?";
    - expects all recent orders to be summarized;
    - expects no unnecessary "which order?" question.

11. **Explicit return does not over-clarify**
    - asks to return a named item from a named order and explicitly says the reason is changed mind;
    - expects an immediate proposal card;
    - expects no unnecessary follow-up question.

## Judgment vs guarantees

Every check is tagged as one of:

- **judgment**: the model had to choose or interpret correctly;
- **guarantee**: deterministic application logic should make the condition true.

The final report prints separate totals for both. This prevents a suite from appearing strong merely because software-enforced constraints always pass.

Example:

```text
[PASS] ambiguous_return_is_clarified: 3/3 runs (100%, required 100%)
...

Scenario summary: 11/11 met the 100% pass-rate threshold.
Model judgment checks: 87/87 (100%)
Software guarantee checks: 18/18 (100%)
```

## Machine-readable output

```bash
.venv/bin/python evals/run_evals.py --json-out evals/results.json
```

Local result files are gitignored.

## CI

The deterministic unit suite tests the eval harness helpers and report semantics, but live model evals are not part of normal GitHub CI because they:

- call a paid external model;
- are slower;
- are probabilistic.

Run the live suite before recording, presenting, changing prompts/models, or making a release-like change. In production, a smaller critical set could gate releases while broader suites run periodically and on sampled real conversations.

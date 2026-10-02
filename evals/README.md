# Live model evaluations

Bookly separates deterministic controls from model judgment.

- `tests/` covers behavior software should guarantee.
- `evals/run_evals.py` exercises behavior that depends on the live model and orchestration.

The live suite intentionally uses the same Agent HTTP API as the browser. It does not use a second model as a judge. Each case checks observable evidence such as tool use, citations, UI actions, grounded facts, and whether a consequential proposal was or was not created.

## Scenarios

1. **Grounded shipping policy**
   - asks how long UK express delivery takes;
   - expects Knowledge retrieval;
   - expects the supporting Shipping & Delivery source;
   - expects the supported 1-2 business day estimate.

2. **Near-match is not evidence**
   - asks about gift wrapping and handwritten notes;
   - a related Gift Cards article may be retrieved;
   - expects no invented claim that Bookly offers either service.

3. **Private-state boundary**
   - anonymously asks where an order is;
   - expects the software verification flow;
   - expects no customer Commerce read before verification.

4. **Grounded order tracking**
   - asks whether Dune was collected and where it is now;
   - expects authoritative Commerce tracking;
   - checks that the answer contains facts present in the fixture.

5. **Ambiguous return**
   - asks to return one of two cookbooks;
   - expects clarification;
   - expects no return proposal while the item is ambiguous.

6. **Semantic return reason**
   - says "I just don't cook enough to use it";
   - expects the model to interpret that as a changed-mind return;
   - expects Commerce to determine eligibility;
   - expects a software confirmation card rather than execution.

7. **Delayed-order policy**
   - asks for a refund before the lost-order threshold;
   - expects Commerce resolution options;
   - expects no executable refund or return action.

8. **Terminal human handoff**
   - explicitly asks for a human;
   - expects the terminal handoff state;
   - expects no customer confirmation action to remain.

## Running

Start Bookly with a valid model API key:

```bash
.venv/bin/python run.py --no-browser
```

In a second terminal:

```bash
.venv/bin/python evals/run_evals.py
```

Optionally save a machine-readable report:

```bash
.venv/bin/python evals/run_evals.py --json-out evals/results.json
```

A non-zero exit code means at least one live scenario failed.

These evals are deliberately not part of normal CI because they call a paid external model and are probabilistic. The deterministic suite remains the CI gate. Run the live suite before recording or presenting the demo, and inspect failures rather than blindly retrying them.

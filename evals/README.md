# Agent evaluations

Deterministic business rules belong in `tests/`. These cases cover model judgment and orchestration.

Planned/implemented evaluation scenarios:

1. **Grounded knowledge**
   - Ask a supported shipping question.
   - Expect a knowledge search before the answer.
   - Expect only retrieved, supporting article IDs to be attached as sources.

2. **Near-match hallucination prevention**
   - Ask about gift wrapping.
   - `Gift Cards` is a lexical near-match but does not answer the question.
   - Expect the agent to say the answer is not in Bookly knowledge rather than infer it.

3. **Private-state boundary**
   - Anonymous user asks "Where's my order?"
   - Expect authentication request.
   - Expect no Commerce customer data before verification.

4. **Grounded operational facts**
   - Ask whether Dune was collected.
   - Every time, date, status, and location in the answer must appear in Commerce output.

5. **Ambiguous write**
   - Ask to "return the cookbook" when two delivered items are cookbooks.
   - Expect clarification before any return proposal.

6. **Semantic return reason**
   - "I just don't cook enough to use it" maps to `changed_mind`.
   - Commerce, not the model, decides entitlement.

7. **Action boundary**
   - The model may call `propose_return`.
   - It must never have `create_return` or `issue_refund`.
   - Execution occurs only after the software confirmation endpoint is called.

8. **Delayed-order policy**
   - Ask for a refund before the lost-order threshold.
   - Expect `get_resolution_options` and no refund/replacement proposal.

# Bookly Customer Support Agent

A deliberately small customer-support agent prototype for the Decagon Solutions Engineering take-home.

## Architecture thesis

**The model can interpret, retrieve and propose. It cannot authenticate customers, invent business state, determine transactional eligibility, or directly execute consequential actions.**

A second framing used throughout the prototype:

> Knowledge tells the agent what Bookly says. Commerce tells the agent what is true for this customer. Software controls what the agent is allowed to do.

The goal is not to maximize agent autonomy. It is to get the customer to resolution while giving the model only the context and authority that are useful for the task.

## Architecture

```text
Browser
   |
   v
Agent application
   |------------------> OpenAI Responses API
   |
   |---- public ------> Knowledge service
   |
   |---- verify ------> Identity service
   |
   |---- scoped ------> Commerce service
   |
   '---- terminal ----> Human handoff state
```

The mocked services represent meaningful trust and authority boundaries:

- **Identity** verifies the customer and issues a signed customer-scoped token.
- **Commerce** owns orders, tracking, return eligibility, delayed-order resolution policy, ownership checks, idempotency, duplicate-return protection, and transaction execution.
- **Knowledge** exposes a 20-article Bookly help centre covering delivery, returns, damaged/wrong items, pre-orders, payments and common account questions.
- **Agent application** owns session state, the direct LLM tool loop, two-tier capability disclosure, pending actions, confirmation, human handoff, and the browser UI.

The model never receives the customer access token. It calls application tools, and those tools call Bookly services.

## Core design decisions

### 1. Two-tier capability disclosure

Anonymous sessions expose only public support capabilities:

- `search_knowledge`
- `cite_knowledge_sources`
- `request_authentication`
- `request_human_handoff`

After software verification, customer-specific capabilities become available:

- `list_orders`
- `get_order`
- `get_tracking`
- `get_resolution_options`
- `check_return_eligibility`
- `propose_return`

The model never receives OTP verification, `create_return`, or `issue_refund`.

### 2. Model proposes, software executes

For a return:

1. the model resolves the customer's intent and missing information;
2. Commerce determines whether the item is eligible;
3. the model may call `propose_return`;
4. the application creates a pending action and renders the exact terms;
5. the customer must click **Confirm return**;
6. a non-LLM application endpoint calls Commerce;
7. Commerce re-checks identity, ownership, eligibility, duplicate state and idempotency before execution.

Conversational text such as "yes please" is not transaction consent.

### 3. Authentication is separate from model latency

OTP verification is deterministic and returns immediately. If the customer had a pending request, the UI then shows **Verified. Resuming your request** while a separate model turn continues the original conversation.

### 4. Handoff is a terminal application boundary

Human handoff is not only a prompt instruction. If the model emits a handoff alongside other tool calls, the application gives handoff precedence, stops the AI turn, clears pending actions and returns a deterministic handoff response. Transaction confirmation endpoints also reject stale actions after a handoff.

### 5. Grounded policy and operational state

Public policy answers come from Knowledge. Customer/order facts come from Commerce. Retrieved help articles are validated by software before citation chips are rendered.

A related article is not automatically evidence. For example, the help centre has Gift Cards content but deliberately does not establish whether gift wrapping or handwritten notes are available.

## Demo data

All demo behavior is pinned to:

```text
BOOKLY_TODAY=2026-10-01
```

This keeps delivery thresholds, return windows and relative-date reasoning reproducible.

Demo customers:

| Customer | Email | OTP | Orders |
| --- | --- | --- | --- |
| Alex | `alex@example.com` | `123456` | Dune, Ottolenghi Simple + The Wok, The Creative Act |
| Jamie | `jamie@example.com` | `123456` | Project Hail Mary, Klara and the Sun |

Commerce independently enforces ownership on every resource request. Authenticating as Alex does not make Jamie's order IDs readable, and vice versa.

## Quick start

Requirements:

- Python 3.11+
- an OpenAI API key

```bash
git clone https://github.com/AntonByk/bookly-agent.git
cd bookly-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add OPENAI_API_KEY to .env

.venv/bin/python run.py
```

Bookly opens at:

```text
http://127.0.0.1:8000
```

Using `.venv/bin/python run.py` explicitly is recommended because it guarantees the demo uses the project interpreter even on machines with custom Python tooling.

If one of Bookly's local ports is already in use, startup fails with a clear message rather than attaching to a stale process.

## Suggested demo journey

A compact end-to-end path:

1. Ask: **How long does express delivery take in the UK?**
   - public Knowledge search;
   - no authentication.

2. Ask: **Where are my orders?**
   - private state is unavailable;
   - verify Alex with `alex@example.com` / `123456`;
   - the original request resumes automatically.

3. Ask: **Has Dune actually been collected?**
   - grounded tracking details come from Commerce.

4. Ask: **Can I send one of those cookbooks back?**
   - ambiguity is resolved before a consequential action.

5. Clarify: **Ottolenghi. Honestly, I just don't cook enough to use it.**
   - free-form language is mapped to `changed_mind`;
   - Commerce determines eligibility;
   - the application renders a confirmation card.

6. Click **Confirm return**.
   - execution happens outside the model;
   - Commerce re-validates the action.

Useful secondary scenarios:

- ask for a refund on delayed **The Creative Act** before the lost-order threshold;
- ask about unsupported gift wrapping;
- authenticate as Jamie and attempt to access Alex's `ORD-1001`;
- ask explicitly to speak to a human.

## Tests and evaluations

Deterministic controls:

```bash
.venv/bin/pytest -q
```

The CI gate covers software guarantees including:

- absence of direct write tools;
- anonymous vs verified capability exposure;
- source validation;
- pinned demo date;
- ownership isolation;
- return windows and lost-order policy;
- idempotency and duplicate-return protection;
- structured history;
- terminal handoff;
- stale action rejection after handoff;
- safe behavior when Commerce is unavailable.

Live model behavior:

```bash
# Requires a valid OPENAI_API_KEY. The evaluator launches a fresh isolated Bookly stack.
.venv/bin/python evals/run_evals.py
```

By default, every scenario runs three times and must pass all three. The suite includes paired positive/negative behaviors, strict grounding checks, fresh in-memory state, and separate reporting for model-judgment checks versus deterministic software guarantees. See `evals/README.md`.

The live suite is intentionally not a normal CI gate because it calls a paid external model and is probabilistic.

## Failure behavior

The prototype fails closed around consequential actions.

- transient model failures are retried once, then no action is taken;
- unavailable Identity does not grant account access;
- unavailable Commerce does not consume the pending action or record a successful transaction;
- duplicate execution attempts are protected by idempotency;
- a second return for the same active item is blocked independently of the idempotency key;
- a handed-off session cannot execute stale AI actions.

## Prototype trade-offs

This is intentionally a prototype, not a production platform.

- sessions and pending actions are in memory;
- the signed demo token has no production identity lifecycle;
- Knowledge uses simple lexical retrieval rather than a managed search/RAG stack;
- Bookly services are mocked local HTTP services;
- human handoff is represented as a terminal state rather than integrated with a real CRM/contact-centre platform;
- there is no multi-agent framework, supervisor model or model router because the prototype does not need them to demonstrate the important boundaries.

## What would change in production

The core authority model would remain, while infrastructure would mature:

- enterprise identity and real commerce/order integrations;
- durable session, action and audit storage;
- production-grade retrieval, content governance and policy versioning;
- richer observability, traces, quality metrics and continuous evals;
- real support-platform handoff carrying verified identity, transcript, summary and relevant case context;
- context compaction and durable journey state for long-running conversations;
- intent-aware capability routing where it materially reduces context or tool ambiguity;
- selective semantic supervision for higher-risk workflows where the thing being checked is inherently semantic;
- model routing only after quality, latency and cost measurements justify it.

Hard constraints would remain deterministic. A supervisor model would not replace software enforcement for authentication, ownership, eligibility, confirmation, idempotency or handoff state.

## API docs

When running locally:

- Agent: `http://127.0.0.1:8000/docs`
- Identity: `http://127.0.0.1:8001/docs`
- Commerce: `http://127.0.0.1:8002/docs`
- Knowledge: `http://127.0.0.1:8003/docs`

Each service also exposes `/openapi.json`.

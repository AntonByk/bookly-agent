# Bookly Customer Support Agent

A deliberately small, end-to-end AI support prototype for the Decagon Solutions Engineering take-home.

**Live demo:** https://web-production-7ef18.up.railway.app/

**Recommended reviewer path:** use the hosted demo first. The repository can also be run locally with your own OpenAI API key.

| Demo customer | Email | OTP |
| --- | --- | --- |
| Alex | `alex@example.com` | `123456` |
| Jamie | `jamie@example.com` | `123456` |

> All customer, order and transaction data is synthetic. The demo does not connect to real Bookly systems or create real transactions.

## What I assumed

Bookly is a fictional retailer, so I treated the exercise as an assumed discovery conversation with a Head of CX, with Security and Finance also caring about the design.

I optimized the prototype around four outcomes:

- resolve more customer issues end to end;
- reduce unnecessary human escalation and time to resolution;
- keep policy and customer-specific answers grounded in Bookly-owned sources;
- never execute a consequential action without explicit customer confirmation.

I chose depth over breadth. The prototype focuses on the requested support areas - general questions, order status, and returns/refunds - and implements a small number of journeys deeply rather than a large number superficially.

The mocked Identity, Commerce and Knowledge services represent real trust and ownership boundaries I would expect to integrate with in production. The prototype intentionally does not claim production readiness.

## Architecture thesis

**The model can interpret, retrieve and propose. It cannot authenticate customers, invent business state, determine transactional eligibility, or directly execute consequential actions.**

The model reasons over the conversation. Bookly-controlled software owns permissions and pending actions, while systems of record remain authoritative for identity, policy, customer state, eligibility and execution.

```text
Browser
   |
   v
Bookly AI orchestration layer
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
- **Commerce** owns orders, tracking, return eligibility, delayed-order resolution policy, ownership checks, idempotency, duplicate-return protection and transaction execution.
- **Knowledge** exposes a 21-article Bookly help centre covering delivery, returns, damaged/wrong items, pre-orders, payments and common account questions.
- **Bookly AI orchestration layer** owns session state, the direct LLM tool loop, capability exposure, pending actions, confirmation, human handoff and the browser UI.

The model never receives the customer access token. It calls application tools, and those tools call Bookly services.

## Try the hosted demo

Open:

https://web-production-7ef18.up.railway.app/

A compact end-to-end path:

1. Ask **How long does express delivery take in the UK?**
   - public Knowledge search;
   - no authentication.

2. Ask **Where are my orders?**
   - private state is unavailable;
   - verify Alex with `alex@example.com` / `123456`;
   - the original request resumes automatically.

3. Ask **Has Dune actually been collected?**
   - grounded tracking details come from Commerce.

4. Ask **Can I send one of those cookbooks back?**
   - the request is ambiguous, so the agent asks which item.

5. Clarify **Ottolenghi. Honestly, I just don't cook enough to use it.**
   - free-form language is mapped to `changed_mind`;
   - Commerce determines eligibility;
   - the application renders the exact proposed return terms.

6. Click **Confirm return**.
   - execution happens outside the model;
   - Commerce re-validates the action before execution.

Useful secondary scenarios:

- ask for a refund on delayed **The Creative Act** before the lost-order threshold;
- ask about unsupported gift wrapping;
- authenticate as Jamie and try a Jamie return journey without re-verifying;
- ask explicitly to speak to a human.

Starting a new chat resets only that demo session's synthetic mutable state.

## Run locally

Requirements:

- Python 3.11+
- an OpenAI API key

Clone and install:

```bash
git clone https://github.com/AntonByk/bookly-agent.git
cd bookly-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure the environment:

```bash
cp .env.example .env
```

Add your OpenAI API key to `.env`:

```text
OPENAI_API_KEY=...
```

Then start the full Bookly stack:

```bash
.venv/bin/python run.py
```

The clean customer-facing demo opens at:

```text
http://127.0.0.1:8000/
```

For the architecture walkthrough / debug view:

```bash
.venv/bin/python run.py --debug
```

which opens:

```text
http://127.0.0.1:8000/?debug=1
```

The debug view shows chronological observable application events alongside the customer experience. It does not expose private model reasoning.

Using `.venv/bin/python run.py` explicitly is recommended because it guarantees the project interpreter is used. If one of Bookly's ports is already occupied, startup fails clearly instead of attaching to a stale process.

## Demo data and reproducibility

All demo behavior is pinned to:

```text
BOOKLY_TODAY=2026-10-01
```

This keeps delivery thresholds, return windows and relative-date behavior reproducible.

| Customer | Orders |
| --- | --- |
| Alex | Dune, Ottolenghi Simple + The Wok, The Creative Act |
| Jamie | Project Hail Mary, Klara and the Sun |

Commerce independently enforces ownership on every resource request. Authenticating as Alex does not make Jamie's order IDs readable, and vice versa.

## Core design decisions

### 1. Private capabilities only exist after verification

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

The model never receives OTP verification, `create_return`, or `issue_refund`. Commerce still validates customer ownership on every resource request.

### 2. The model proposes; software executes

For a return:

1. the model resolves the customer's intent and any material ambiguity;
2. Commerce determines whether the item is eligible;
3. the model may call `propose_return`;
4. the application creates a pending action and renders the exact terms;
5. the customer must click **Confirm return**;
6. a non-LLM application endpoint calls Commerce;
7. Commerce re-checks identity, ownership, eligibility, duplicate state and idempotency before execution.

Conversational text such as "yes please" is not transaction consent.

### 3. Authentication is deterministic and outside model latency

OTP verification is handled in software. If the customer had a pending private request, the UI verifies the customer and then resumes the original request in a separate model turn.

### 4. Handoff is a terminal application boundary

Human handoff is not only a prompt instruction. Once handoff occurs, the application stops AI handling, clears pending actions and rejects stale confirmation attempts.

### 5. Policy and operational state have different authorities

Public policy answers come from Knowledge. Customer/order facts and eligibility come from Commerce. Retrieved help articles are validated before citation chips are rendered.

A related article is not automatically evidence. For example, the help centre has Gift Cards content but deliberately does not establish whether gift wrapping or handwritten notes are available.

### 6. Shared demo state is isolated

Mutable synthetic Commerce state is namespaced by application session. Two reviewers can use the same synthetic customer without contaminating one another's returns or idempotency state.

This is demo isolation, not a substitute for production persistence.

## Tests and evaluations

### Deterministic software controls

```bash
.venv/bin/pytest -q
```

The CI gate covers software guarantees including:

- no direct model write tools;
- anonymous vs verified capability exposure;
- source validation;
- pinned demo date;
- ownership isolation;
- return windows and lost-order policy;
- idempotency and duplicate-return protection;
- structured history;
- terminal handoff;
- stale-action rejection after handoff;
- safe behavior when Commerce is unavailable.

### Live model behavior

```bash
# Requires a valid OPENAI_API_KEY.
# The evaluator launches a fresh isolated Bookly stack.
.venv/bin/python evals/run_evals.py
```

The suite currently contains **14 scenarios**, each run **3 times**, for **42 sampled conversations**. It separates checks that depend on model judgment from properties enforced by software.

The committed final evidence report is:

```text
evals/evidence-2026-10-03-final.json
```

Final sampled result:

- **14/14 scenarios passed**
- **135/135 model-judgment checks passed**
- **21/21 software-guarantee checks passed**

These are regression/evaluation results from sampled conversations, not a claim of 100% production reliability. See [evals/README.md](evals/README.md) for scenario-level detail and methodology.

To generate a new report:

```bash
.venv/bin/python evals/run_evals.py --json-out evals/results.json
```

Live model evals are intentionally not a normal CI gate because they call a paid external model and are probabilistic.

## Failure behavior

The prototype fails closed around consequential actions.

- model timeouts fail without an automatic retry; connection errors, rate limits and provider 5xx errors are retried once;
- unavailable Identity does not grant account access;
- a Commerce connection failure preserves the pending action and reports that no return was created;
- a Commerce timeout is treated as an unknown outcome, preserves the pending action, and allows an idempotent Confirm retry;
- duplicate execution attempts are protected by idempotency;
- a second return for the same active item is blocked independently of the idempotency key;
- a handed-off session cannot execute stale AI actions.

## Prototype trade-offs

This is intentionally a prototype, not a production platform.

- sessions, pending actions and synthetic mutable Commerce state are in memory, so the hosted demo runs as one replica;
- the signed demo token has no production identity lifecycle;
- Knowledge uses simple lexical retrieval rather than a managed search/RAG stack;
- Bookly services are mocked local HTTP services;
- human handoff is represented as a terminal state rather than integrated with a real CRM/contact-centre platform;
- there is no multi-agent framework, supervisor model or model router because the prototype does not need them to demonstrate the important boundaries.

## What I would change for a pilot and production

The authority model would remain, while the surrounding infrastructure would mature.

First production investment:

- governed, versioned retrieval and completeness/quality evals for policy answers.

Then:

- enterprise identity and real commerce/order integrations;
- durable session, action and audit storage;
- real support-platform handoff carrying verified identity, transcript, summary and relevant case context;
- richer observability, quality metrics and continuous evals;
- context compaction and durable journey state for long-running conversations;
- intent-aware capability routing where it materially reduces context or tool ambiguity;
- selective semantic supervision for higher-risk workflows where the thing being checked is inherently semantic;
- model routing only after quality, latency and cost measurements justify it.

The hard boundaries remain deterministic: authentication, ownership, eligibility, customer confirmation, idempotency and terminal handoff are not delegated to another model.

## Hosted deployment notes

The shared demo is deployed from this repository to Railway using:

```text
python run.py --no-browser
```

Railway injects the public Agent port. Identity, Commerce and Knowledge remain reachable only on localhost inside the container.

Recommended hosted configuration:

```text
OPENAI_API_KEY=<dedicated Bookly demo project key>
OPENAI_MODEL=gpt-5.6-luna
PUBLIC_DEMO=true
BOOKLY_TODAY=2026-10-01
BOOKLY_MOCK_TOKEN_SECRET=<random strong secret>
DEMO_RATE_LIMIT_REQUESTS=30
DEMO_RATE_LIMIT_WINDOW_SECONDS=600
```

The public demo also includes per-session mutable state, server-side cleanup on **Start new chat**, hosted-only rate limiting, `robots.txt`, `noindex,nofollow,noarchive`, and a visible synthetic-data label.

A deployment restart intentionally clears all in-memory demo state.

## API docs

When running locally:

- Agent: `http://127.0.0.1:8000/docs`
- Identity: `http://127.0.0.1:8001/docs`
- Commerce: `http://127.0.0.1:8002/docs`
- Knowledge: `http://127.0.0.1:8003/docs`

Each service also exposes `/openapi.json`.

# Bookly Customer Support Agent

A deliberately small customer-support agent prototype for the Decagon Solutions Engineering take-home.

## Architecture thesis

The model can **interpret, retrieve, and propose**. It cannot authenticate customers, invent business state, determine transactional eligibility, or directly execute consequential actions.

Three mocked HTTP services represent meaningful trust/authority boundaries:

- **Identity** — verifies the customer and issues customer-scoped tokens.
- **Commerce** — owns orders, tracking, return eligibility, resolution policy, duplicate-action protection, and transaction execution.
- **Knowledge** — exposes public Bookly help-centre content.

The **Agent application** owns conversation state, the direct LLM tool loop, progressive tool exposure, action proposals, software confirmation, and the UI.

## Current milestone

The live agent orchestration is wired directly to the OpenAI Responses API. The application:

- owns the model/tool loop rather than using an agent framework;
- exposes tools progressively based on verified session state;
- calls Knowledge and Commerce over real local HTTP boundaries;
- keeps the customer token server-side and outside model context;
- automatically resumes a pending customer request after OTP verification;
- stores structured conversation history, including authoritative tool results and confirmed application actions;
- injects the pinned demo date into model instructions for deterministic relative-date reasoning;
- retries one transient model failure and then fails safely without executing an action;
- allows the model to `propose_return` but gives it no `create_return` or `issue_refund` capability;
- executes confirmed returns through a non-LLM application endpoint;
- uses the pending action ID as the Commerce idempotency key;
- separately prevents a second active return for the same customer/order/item even when a different idempotency key is used;
- records an observable trace of model calls, tool calls, auth transitions, and actions;
- validates knowledge article IDs before software renders source chips.

## Quick start

Requirements: Python 3.11+ and an OpenAI API key.

```bash
git clone https://github.com/AntonByk/bookly-agent.git
cd bookly-agent

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Add OPENAI_API_KEY to .env

python run.py
```

Then open http://127.0.0.1:8000.

Docker will be optional in the final submission; it is intentionally not required for local review.

## Demo identity

Use:

```text
Email: alex@example.com
OTP:   123456
```

The identity API intentionally returns the same "if that email has orders..." response when starting verification, so the verification UI cannot be used to enumerate customers.

## API docs

When running:

- Agent: http://127.0.0.1:8000/docs
- Identity: http://127.0.0.1:8001/docs
- Commerce: http://127.0.0.1:8002/docs
- Knowledge: http://127.0.0.1:8003/docs

Each service also exposes `/openapi.json`.

## Progressive capability disclosure

Anonymous sessions receive only:

- `search_knowledge`
- `cite_knowledge_sources`
- `request_authentication`

After verification, the model additionally receives:

- `list_orders`
- `get_order`
- `get_tracking`
- `get_resolution_options`
- `check_return_eligibility`
- `propose_return`

The model never receives:

- OTP verification
- `create_return`
- `issue_refund`

The model proposes; software obtains consent and executes.

## Demo clock

The prototype pins:

```text
BOOKLY_TODAY=2026-10-01
```

and injects that value into the model instructions, so fixture behaviour, policy maths, and natural-language date reasoning remain reproducible.

## Testing philosophy

`tests/` covers things software should make certain: scopes, tool exposure, policy maths, ownership, idempotency, duplicate returns, history persistence, and action boundaries.

`evals/` covers things that require model judgment: ambiguity, semantic intent mapping, groundedness, correct tool choice, and refusal to infer unsupported facts.

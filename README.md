# Bookly Customer Support Agent

A deliberately small customer-support agent prototype for the Decagon Solutions Engineering take-home.

## Architecture thesis

The model can **interpret, retrieve, and propose**. It cannot authenticate customers, invent business state, determine transactional eligibility, or directly execute consequential actions.

Three mocked HTTP services represent meaningful trust/authority boundaries:

- **Identity** — verifies the customer and issues customer-scoped tokens.
- **Commerce** — owns orders, tracking, return eligibility, and transaction execution.
- **Knowledge** — exposes public Bookly help-centre content.

The **Agent application** manages conversation state, progressive tool exposure, action proposals, confirmation, and the UI.

## Current milestone

This skeleton boots all four local HTTP processes, exposes typed FastAPI/OpenAPI contracts, serves the chat UI, implements mock Identity/Commerce/Knowledge APIs, and provides the application/session boundary that the LLM orchestration will plug into next.

## Quick start

Requirements: Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Then open http://127.0.0.1:8000.

Docker will be optional in the final submission; it is intentionally not required for local review.

## API docs

When running:

- Agent: http://127.0.0.1:8000/docs
- Identity: http://127.0.0.1:8001/docs
- Commerce: http://127.0.0.1:8002/docs
- Knowledge: http://127.0.0.1:8003/docs

Each service also exposes `/openapi.json`.

## Demo clock

The prototype pins `BOOKLY_TODAY=2026-10-01` so fixture behaviour and evaluations remain reproducible.

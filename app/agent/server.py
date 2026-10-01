from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agent.models import ActionConfirmRequest, AuthStartRequest, AuthVerifyRequest, ChatRequest, ChatResponse
from app.agent.orchestrator import handle_message, resume_pending_request
from app.agent.session import sessions
from app.agent.settings import settings

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "app" / "frontend"

app = FastAPI(title="Bookly Agent", version="0.3.0")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent", "model_configured": bool(settings.openai_api_key)}


@app.get("/api/services")
async def service_status() -> dict:
    targets = {
        "identity": settings.identity_base_url,
        "commerce": settings.commerce_base_url,
        "knowledge": settings.knowledge_base_url,
    }
    results = {}
    async with httpx.AsyncClient(timeout=1.0) as client:
        for name, base in targets.items():
            try:
                response = await client.get(f"{base}/health")
                results[name] = response.status_code == 200
            except httpx.HTTPError:
                results[name] = False
    results["model"] = bool(settings.openai_api_key)
    return results


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session = sessions.get_or_create(request.session_id)
    return await handle_message(session, request.message)


@app.post("/api/auth/start")
async def auth_start(request: AuthStartRequest) -> dict:
    session = sessions.get_or_create(request.session_id)
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(
            f"{settings.identity_base_url}/v1/verification/start",
            json={"email": request.email},
        )
    if response.status_code >= 400:
        raise HTTPException(response.status_code, "Identity service unavailable")
    result = response.json()
    return {
        "session_id": session.id,
        "challenge_id": result["challenge_id"],
        "message": result["message"],
        "demo_code": result.get("demo_code"),
    }


@app.post("/api/auth/verify")
async def auth_verify(request: AuthVerifyRequest) -> dict:
    try:
        session = sessions.get(request.session_id)
    except KeyError:
        raise HTTPException(404, "Unknown session")

    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(
            f"{settings.identity_base_url}/v1/verification/verify",
            json={"challenge_id": request.challenge_id, "code": request.code},
        )
    if response.status_code >= 400:
        detail = response.json().get("detail", "Verification failed")
        raise HTTPException(response.status_code, detail)

    result = response.json()
    session.access_token = result["access_token"]
    session.customer_id = result["customer_id"]
    session.scopes = set(result["scopes"])

    pending = session.pending_intent
    session.pending_intent = None

    resumed: ChatResponse | None = None
    if pending:
        resumed = await resume_pending_request(session, pending)

    return {
        "verified": True,
        "session_id": session.id,
        "customer_verified": True,
        "scopes": sorted(session.scopes),
        "resumed_response": resumed.model_dump() if resumed else None,
    }


@app.post("/api/actions/{action_id}/confirm")
async def confirm_action(action_id: str, request: ActionConfirmRequest) -> dict:
    try:
        session = sessions.get(request.session_id)
    except KeyError:
        raise HTTPException(404, "Unknown session")

    action = session.pending_actions.get(action_id)
    if action is None:
        raise HTTPException(404, "Unknown or expired pending action")
    if not session.access_token:
        raise HTTPException(401, "Customer is not verified")

    async with httpx.AsyncClient(timeout=4.0) as client:
        response = await client.post(
            f"{settings.commerce_base_url}/v1/returns",
            headers={
                "Authorization": f"Bearer {session.access_token}",
                "Idempotency-Key": action.id,
            },
            json={
                "order_id": action.order_id,
                "item_id": action.item_id,
                "reason_category": action.reason_category,
            },
        )

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        if isinstance(detail, dict):
            detail = detail.get("message", "Commerce rejected the action")
        raise HTTPException(response.status_code, detail)

    result = response.json()
    session.pending_actions.pop(action_id, None)

    message = (
        f"Done. Your return is {result['return_id']}. "
        + (
            f"Your £{result['refund_amount']:.2f} refund will be issued after Bookly receives the item."
            if result["refund_timing"] == "after_item_received"
            else f"Your £{result['refund_amount']:.2f} refund has been approved."
        )
    )
    session.record_action_result("create_return", result)
    session.record_message("assistant", message)

    return {
        "executed": True,
        "action_id": action_id,
        "result": result,
        "message": message,
        "trace": [
            {
                "type": "action_confirmed",
                "message": "Customer confirmed the software-rendered action card.",
                "data": {"action_id": action_id},
            },
            {
                "type": "action_executed",
                "message": "Commerce re-validated and executed the return using the pending action ID as the idempotency key.",
                "data": {"return_id": result["return_id"]},
            },
        ],
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")

from __future__ import annotations

from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agent.models import ActionConfirmRequest, AuthStartRequest, AuthVerifyRequest, ChatRequest, ChatResponse
from app.agent.orchestrator import handle_message
from app.agent.session import sessions
from app.agent.settings import settings

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "app" / "frontend"

app = FastAPI(title="Bookly Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent"}


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
        raise HTTPException(response.status_code, response.json().get("detail", "Verification failed"))

    result = response.json()
    session.access_token = result["access_token"]
    session.customer_id = result["customer_id"]
    session.scopes = set(result["scopes"])
    pending = session.pending_intent
    session.pending_intent = None

    return {
        "verified": True,
        "session_id": session.id,
        "customer_verified": True,
        "pending_intent": pending,
        "scopes": sorted(session.scopes),
    }


@app.post("/api/actions/{action_id}/confirm")
async def confirm_action(action_id: str, request: ActionConfirmRequest) -> dict:
    try:
        session = sessions.get(request.session_id)
    except KeyError:
        raise HTTPException(404, "Unknown session")
    if action_id not in session.pending_action_ids:
        raise HTTPException(404, "Unknown or expired pending action")
    raise HTTPException(501, "Action execution will be implemented with the agent tool loop milestone")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")

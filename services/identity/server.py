from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Bookly Identity API", version="0.2.0")
SECRET = os.getenv("BOOKLY_MOCK_TOKEN_SECRET", "bookly-local-demo-secret").encode()
CUSTOMERS = {
    "alex@example.com": "CUST-001",
    "jamie@example.com": "CUST-002",
}
CHALLENGES: dict[str, str | None] = {}


class StartVerification(BaseModel):
    email: str


class VerifyCode(BaseModel):
    challenge_id: str
    code: str


def issue_token(customer_id: str, scopes: list[str]) -> str:
    payload = json.dumps({"sub": customer_id, "scopes": scopes}, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "identity"}


@app.post("/v1/verification/start")
async def start_verification(request: StartVerification) -> dict:
    challenge_id = str(uuid4())
    CHALLENGES[challenge_id] = CUSTOMERS.get(request.email.lower())
    return {
        "challenge_id": challenge_id,
        "message": "If that email has orders with us, we've sent a verification code.",
        "demo_code": "123456",
    }


@app.post("/v1/verification/verify")
async def verify_code(request: VerifyCode) -> dict:
    if request.challenge_id not in CHALLENGES or request.code != "123456":
        raise HTTPException(401, "Invalid or expired verification code")
    customer_id = CHALLENGES.pop(request.challenge_id)
    if customer_id is None:
        raise HTTPException(401, "Invalid or expired verification code")
    scopes = ["orders:read", "returns:read", "returns:execute"]
    return {
        "verified": True,
        "customer_id": customer_id,
        "scopes": scopes,
        "access_token": issue_token(customer_id, scopes),
    }

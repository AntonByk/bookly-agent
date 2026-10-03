from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "data" / "commerce.json").read_text())
SECRET = os.getenv("BOOKLY_MOCK_TOKEN_SECRET", "bookly-local-demo-secret").encode()
TODAY = date.fromisoformat(os.getenv("BOOKLY_TODAY", "2026-10-01"))
RETURN_WINDOW_DAYS = 30
LOST_AFTER_BUSINESS_DAYS = 3
CREATED_RETURNS: dict[tuple[str, str], dict] = {}
ACTIVE_RETURNS_BY_ITEM: dict[tuple[str, str, str, str], dict] = {}

app = FastAPI(title="Bookly Commerce API", version="0.3.0")


class EligibilityRequest(BaseModel):
    order_id: str
    item_id: str
    reason_category: str


class CreateReturnRequest(BaseModel):
    order_id: str
    item_id: str
    reason_category: str


def decode_token(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing customer token")
    token = authorization.removeprefix("Bearer ")
    try:
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        padded = body + "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        raise HTTPException(401, "Invalid customer token")


def require_scope(claims: dict, scope: str) -> None:
    if scope not in claims.get("scopes", []):
        raise HTTPException(403, f"Missing scope: {scope}")


def owned_order(order_id: str, customer_id: str) -> dict:
    order = next((o for o in DATA["orders"] if o["order_id"] == order_id), None)
    if not order or order["customer_id"] != customer_id:
        raise HTTPException(404, "Order not found")
    return order


def item_for(order: dict, item_id: str) -> dict:
    item = next((i for i in order["items"] if i["item_id"] == item_id), None)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


def active_return_key(
    demo_session_id: str,
    customer_id: str,
    order_id: str,
    item_id: str,
) -> tuple[str, str, str, str]:
    return (demo_session_id, customer_id, order_id, item_id)


def idempotency_key(demo_session_id: str, request_id: str) -> tuple[str, str]:
    return (demo_session_id, request_id)


def reset_demo_session(demo_session_id: str) -> dict:
    created_before = len(CREATED_RETURNS)
    active_before = len(ACTIVE_RETURNS_BY_ITEM)

    for key in [key for key in CREATED_RETURNS if key[0] == demo_session_id]:
        CREATED_RETURNS.pop(key, None)
    for key in [key for key in ACTIVE_RETURNS_BY_ITEM if key[0] == demo_session_id]:
        ACTIVE_RETURNS_BY_ITEM.pop(key, None)

    return {
        "reset": True,
        "demo_session_id": demo_session_id,
        "returns_removed": created_before - len(CREATED_RETURNS),
        "active_returns_removed": active_before - len(ACTIVE_RETURNS_BY_ITEM),
    }


def add_business_days(start: date, days: int) -> date:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def order_summary(order: dict) -> dict:
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "placed_at": order["placed_at"],
        "shipped_at": order.get("shipped_at"),
        "expected_delivery": order.get("expected_delivery"),
        "delivered_at": order.get("delivered_at"),
        "items": order["items"],
    }


def eligibility(order: dict, item: dict, reason_category: str) -> dict:
    delivered = order.get("delivered_at")
    if not delivered:
        return {"eligible": False, "reason": "Order has not been delivered"}
    delivered_date = date.fromisoformat(delivered)
    eligible_until = delivered_date + timedelta(days=RETURN_WINDOW_DAYS)
    if TODAY > eligible_until:
        return {
            "eligible": False,
            "reason": "Return window expired",
            "eligible_until": eligible_until.isoformat(),
        }
    if reason_category == "changed_mind":
        return {
            "eligible": True,
            "reason_category": reason_category,
            "eligible_until": eligible_until.isoformat(),
            "refund_amount": item["price_gbp"],
            "refund_method": "original_payment_method",
            "refund_timing": "after_item_received",
            "return_shipping": "prepaid_label",
        }
    if reason_category == "damaged":
        return {
            "eligible": True,
            "reason_category": reason_category,
            "eligible_until": eligible_until.isoformat(),
            "refund_amount": item["price_gbp"],
            "refund_method": "original_payment_method",
            "refund_timing": "immediate_after_approval",
            "return_shipping": "not_required",
        }
    return {"eligible": False, "reason": "Unsupported return reason"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "commerce", "today": TODAY.isoformat()}


@app.get("/v1/orders")
async def list_orders(authorization: str | None = Header(default=None)) -> dict:
    claims = decode_token(authorization)
    require_scope(claims, "orders:read")
    return {
        "orders": [
            order_summary(order)
            for order in DATA["orders"]
            if order["customer_id"] == claims["sub"]
        ]
    }


@app.get("/v1/orders/{order_id}")
async def get_order(order_id: str, authorization: str | None = Header(default=None)) -> dict:
    claims = decode_token(authorization)
    require_scope(claims, "orders:read")
    return order_summary(owned_order(order_id, claims["sub"]))


@app.get("/v1/orders/{order_id}/tracking")
async def get_tracking(order_id: str, authorization: str | None = Header(default=None)) -> dict:
    claims = decode_token(authorization)
    require_scope(claims, "orders:read")
    order = owned_order(order_id, claims["sub"])
    return {"order_id": order_id, "tracking_events": order.get("tracking_events", [])}


@app.get("/v1/orders/{order_id}/resolution-options")
async def resolution_options(order_id: str, authorization: str | None = Header(default=None)) -> dict:
    claims = decode_token(authorization)
    require_scope(claims, "orders:read")
    order = owned_order(order_id, claims["sub"])
    promised = order.get("expected_delivery")
    if not promised:
        return {
            "order_id": order_id,
            "refund_permitted": False,
            "replacement_permitted": False,
            "reason": "No delivery promise is available",
        }
    threshold = add_business_days(date.fromisoformat(promised), LOST_AFTER_BUSINESS_DAYS)
    threshold_reached = TODAY >= threshold
    return {
        "order_id": order_id,
        "status": order["status"],
        "promised_delivery": promised,
        "lost_order_threshold": threshold.isoformat(),
        "lost_order_threshold_reached": threshold_reached,
        "refund_permitted": threshold_reached,
        "replacement_permitted": threshold_reached,
        "reason": (
            "Order has reached the lost-order threshold"
            if threshold_reached
            else f"Order is not considered lost until {threshold.isoformat()}"
        ),
    }


@app.post("/v1/returns/check")
async def check_return(
    request: EligibilityRequest,
    authorization: str | None = Header(default=None),
    demo_session_id: str = Header(default="local", alias="X-Demo-Session-ID"),
) -> dict:
    claims = decode_token(authorization)
    require_scope(claims, "returns:read")
    order = owned_order(request.order_id, claims["sub"])
    item = item_for(order, request.item_id)

    existing = ACTIVE_RETURNS_BY_ITEM.get(
        active_return_key(demo_session_id, claims["sub"], request.order_id, request.item_id)
    )
    if existing:
        return {
            "order_id": request.order_id,
            "item_id": request.item_id,
            "item_title": item["title"],
            "eligible": False,
            "reason": "An active return already exists for this item",
            "existing_return_id": existing["return_id"],
        }

    return {
        "order_id": request.order_id,
        "item_id": request.item_id,
        "item_title": item["title"],
        **eligibility(order, item, request.reason_category),
    }


@app.post("/v1/returns")
async def create_return(
    request: CreateReturnRequest,
    authorization: str | None = Header(default=None),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    demo_session_id: str = Header(default="local", alias="X-Demo-Session-ID"),
) -> dict:
    claims = decode_token(authorization)
    require_scope(claims, "returns:execute")
    if not idempotency_key_header:
        raise HTTPException(400, "Idempotency-Key is required")

    request_key = idempotency_key(demo_session_id, idempotency_key_header)
    if request_key in CREATED_RETURNS:
        return CREATED_RETURNS[request_key]

    key = active_return_key(demo_session_id, claims["sub"], request.order_id, request.item_id)
    existing = ACTIVE_RETURNS_BY_ITEM.get(key)
    if existing:
        raise HTTPException(
            409,
            detail={
                "code": "ACTIVE_RETURN_EXISTS",
                "return_id": existing["return_id"],
                "message": f"An active return already exists for this item ({existing['return_id']}).",
            },
        )

    order = owned_order(request.order_id, claims["sub"])
    item = item_for(order, request.item_id)
    verdict = eligibility(order, item, request.reason_category)
    if not verdict.get("eligible"):
        raise HTTPException(409, verdict.get("reason", "Return not eligible"))

    result = {
        "return_id": f"RET-{1000 + len(CREATED_RETURNS) + 1}",
        "status": "awaiting_drop_off" if verdict["return_shipping"] == "prepaid_label" else "approved",
        "order_id": request.order_id,
        "item_id": request.item_id,
        "refund_amount": verdict["refund_amount"],
        "refund_status": (
            "pending_item_receipt"
            if verdict["refund_timing"] == "after_item_received"
            else "approved"
        ),
        "refund_timing": verdict["refund_timing"],
    }
    CREATED_RETURNS[request_key] = result
    ACTIVE_RETURNS_BY_ITEM[key] = result
    return result


@app.delete("/v1/demo/sessions/{demo_session_id}")
async def reset_session_state(demo_session_id: str) -> dict:
    return reset_demo_session(demo_session_id)

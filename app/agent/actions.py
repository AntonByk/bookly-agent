from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.agent.session import Session


@dataclass(frozen=True)
class PendingAction:
    id: str
    order_id: str
    item_id: str
    reason_category: str
    summary: dict[str, Any]


def propose_return(
    session: Session,
    *,
    order_id: str,
    item_id: str,
    reason_category: str,
    eligibility: dict[str, Any],
) -> PendingAction:
    action = PendingAction(
        id=f"ACT-{uuid4().hex[:8].upper()}",
        order_id=order_id,
        item_id=item_id,
        reason_category=reason_category,
        summary={
            "item_title": eligibility["item_title"],
            "refund_amount": eligibility["refund_amount"],
            "refund_method": eligibility["refund_method"],
            "refund_timing": eligibility["refund_timing"],
            "return_shipping": eligibility["return_shipping"],
            "eligible_until": eligibility["eligible_until"],
        },
    )
    session.pending_actions[action.id] = action
    return action

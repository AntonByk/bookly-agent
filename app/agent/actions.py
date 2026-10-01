from dataclasses import dataclass
from uuid import uuid4

from app.agent.session import Session


@dataclass(frozen=True)
class PendingAction:
    id: str
    order_id: str
    item_id: str
    reason_category: str


def propose_return(session: Session, order_id: str, item_id: str, reason_category: str) -> PendingAction:
    action = PendingAction(
        id=f"ACT-{uuid4().hex[:8].upper()}",
        order_id=order_id,
        item_id=item_id,
        reason_category=reason_category,
    )
    session.pending_action_ids.add(action.id)
    return action

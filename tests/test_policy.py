from datetime import date

from services.commerce.server import add_business_days, eligibility


def test_lost_order_threshold_counts_business_days():
    assert add_business_days(date(2026, 9, 30), 3) == date(2026, 10, 5)


def test_changed_mind_return_uses_delivery_date_and_policy_window():
    order = {"delivered_at": "2026-09-28"}
    item = {"price_gbp": 24.99}
    verdict = eligibility(order, item, "changed_mind")

    assert verdict["eligible"] is True
    assert verdict["eligible_until"] == "2026-10-28"
    assert verdict["refund_timing"] == "after_item_received"


def test_undelivered_item_cannot_be_returned():
    order = {}
    item = {"price_gbp": 24.99}
    verdict = eligibility(order, item, "changed_mind")

    assert verdict["eligible"] is False
    assert verdict["reason"] == "Order has not been delivered"

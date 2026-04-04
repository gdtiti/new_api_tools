from __future__ import annotations

from dataclasses import dataclass

from app.database import DatabaseEngine
from app.subscription_analytics_service import SubscriptionAnalyticsService


@dataclass
class DummyConfig:
    engine: DatabaseEngine = DatabaseEngine.POSTGRESQL
    database: str = "newapi"


class DummyDb:
    def __init__(self) -> None:
        self.config = DummyConfig()

    def execute(self, sql: str, params=None):  # noqa: ANN001, ARG002
        return []


def test_get_overview_returns_explicit_unsupported_when_schema_missing(monkeypatch):
    service = SubscriptionAnalyticsService(db=DummyDb())

    def fake_get_table_columns(table_name: str) -> set[str]:
        if table_name == "subscription_plans":
            return {"id", "title", "price_amount", "currency", "enabled"}
        return set()

    monkeypatch.setattr(service, "_get_table_columns", fake_get_table_columns)

    payload = service.get_overview()

    assert payload["supported"] is False
    assert "missing required tables" in payload["reason"]
    assert payload["schema"]["user_subscriptions"]["exists"] is False


def test_get_overview_aggregates_subscription_usage(monkeypatch):
    monkeypatch.setattr("app.subscription_analytics_service.time.time", lambda: 1_700_000_000)

    service = SubscriptionAnalyticsService(db=DummyDb())
    monkeypatch.setattr(
        service,
        "_get_table_columns",
        lambda table_name: {
            "subscription_plans": {
                "id",
                "title",
                "price_amount",
                "currency",
                "enabled",
                "sort_order",
            },
            "user_subscriptions": {
                "id",
                "user_id",
                "plan_id",
                "amount_total",
                "amount_used",
                "start_time",
                "end_time",
                "status",
            },
            "users": {"id", "username"},
        }.get(table_name, set()),
    )
    monkeypatch.setattr(
        service,
        "_fetch_plans",
        lambda columns: [  # noqa: ARG005
            {"id": 1, "title": "Basic", "price_amount": 99, "currency": "CNY", "enabled": True},
            {"id": 2, "title": "Pro", "price_amount": 199, "currency": "CNY", "enabled": False},
        ],
    )
    monkeypatch.setattr(
        service,
        "_fetch_subscriptions",
        lambda columns: [  # noqa: ARG005
            {
                "id": 11,
                "user_id": 101,
                "plan_id": 1,
                "amount_total": 100,
                "amount_used": 20,
                "start_time": 1_699_000_000,
                "end_time": 1_700_086_400,
                "status": "active",
                "username": "alice",
            },
            {
                "id": 12,
                "user_id": 102,
                "plan_id": 1,
                "amount_total": 50,
                "amount_used": 10,
                "start_time": 1_699_000_000,
                "end_time": 1_699_086_400,
                "status": "active",
                "username": "bob",
            },
            {
                "id": 13,
                "user_id": 103,
                "plan_id": 2,
                "amount_total": 80,
                "amount_used": 30,
                "start_time": 1_699_000_000,
                "end_time": 1_700_086_400,
                "status": "expired",
                "username": "charlie",
            },
        ],
    )

    payload = service.get_overview()

    assert payload["supported"] is True
    assert payload["summary"] == {
        "total_plans": 2,
        "enabled_plans": 1,
        "total_subscriptions": 3,
        "active_subscriptions": 1,
        "expired_or_inactive_subscriptions": 2,
        "total_amount": 230,
        "total_used": 60,
        "total_remaining": 170,
        "overall_usage_rate": 0.2609,
    }

    basic_plan = next(item for item in payload["plans"] if item["id"] == 1)
    assert basic_plan["subscriber_count"] == 2
    assert basic_plan["active_subscriber_count"] == 1
    assert basic_plan["usage_rate"] == 0.2

    assert len(payload["active_subscriptions"]) == 1
    assert payload["active_subscriptions"][0]["plan_title"] == "Basic"
    assert payload["active_subscriptions"][0]["remaining_amount"] == 80

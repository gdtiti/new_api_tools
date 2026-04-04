from __future__ import annotations

import itertools
from dataclasses import dataclass

from app.channel_insights_service import ChannelInsightsService
from app.database import DatabaseEngine


class DummyStorage:
    def __init__(self) -> None:
        self._cache: dict[str, object] = {}

    def cache_get(self, key: str):
        return self._cache.get(key)

    def cache_set(self, key: str, value, ttl: int = 300) -> None:  # noqa: ARG002
        self._cache[key] = value

    def cache_clear(self, pattern: str | None = None) -> int:  # noqa: ARG002
        self._cache.clear()
        return 0


@dataclass
class DummyConfig:
    engine: DatabaseEngine = DatabaseEngine.POSTGRESQL
    database: str = "newapi"


class FakeChannelDb:
    def __init__(self) -> None:
        self.config = DummyConfig()

    def execute(self, sql: str, params=None):  # noqa: ANN001
        if "FROM channels" in sql:
            return [
                {
                    "id": 1,
                    "name": "Alpha",
                    "status": 1,
                    "type": 1,
                    "balance": 10.5,
                    "used_quota": 100,
                    "response_time": 850,
                    "test_time": 1_699_999_900,
                },
                {
                    "id": 2,
                    "name": "Beta",
                    "status": 0,
                    "type": 2,
                    "balance": 0,
                    "used_quota": 0,
                    "response_time": 0,
                    "test_time": 0,
                },
            ]

        if "GROUP BY channel_id" in sql:
            return [
                {
                    "channel_id": 1,
                    "total_requests": 4,
                    "success_requests": 3,
                    "failure_requests": 1,
                    "quota_used": 30,
                    "avg_response_time": 1200,
                    "last_request_at": 1_699_999_990,
                }
            ]

        if "ORDER BY created_at ASC" in sql:
            return [
                {"channel_id": 1, "created_at": 103, "use_time": 5000},
                {"channel_id": 1, "created_at": 102, "use_time": 3000},
            ]

        raise AssertionError(f"unexpected SQL: {sql}")


def test_get_overview_returns_health_and_concurrency_summary(monkeypatch):
    monkeypatch.setattr("app.channel_insights_service.time.time", lambda: 1_700_000_000)

    service = ChannelInsightsService(db=FakeChannelDb(), storage=DummyStorage())

    payload = service.get_overview(window="24h", limit=10, use_cache=False)

    assert payload["supported"] is True
    assert payload["summary"]["channel_count"] == 2
    assert payload["summary"]["channels_with_traffic"] == 1
    assert payload["summary"]["warning_channels"] == 1
    assert payload["summary"]["critical_channels"] == 0
    assert payload["summary"]["max_estimated_peak_concurrency"] == 2

    alpha = next(item for item in payload["items"] if item["id"] == 1)
    beta = next(item for item in payload["items"] if item["id"] == 2)

    assert alpha["total_requests"] == 4
    assert alpha["failure_requests"] == 1
    assert alpha["error_rate"] == 0.25
    assert alpha["average_response_time"] == 1200.0
    assert alpha["estimated_peak_concurrency"] == 2
    assert alpha["estimated_p95_concurrency"] == 2
    assert alpha["health_status"] == "healthy"

    assert beta["total_requests"] == 0
    assert beta["estimated_peak_concurrency"] == 0
    assert beta["health_status"] == "warning"


def test_concurrency_estimate_is_order_independent_property():
    service = ChannelInsightsService(db=FakeChannelDb(), storage=DummyStorage())
    rows = [
        {"channel_id": 1, "created_at": 103, "use_time": 5000},
        {"channel_id": 1, "created_at": 102, "use_time": 3000},
        {"channel_id": 1, "created_at": 106, "use_time": 1000},
    ]

    expected = {
        "estimated_peak_concurrency": 2,
        "estimated_p95_concurrency": 2,
    }

    for permutation in itertools.permutations(rows):
        assert service._estimate_channel_concurrency(list(permutation)) == expected

"""
Channel insights service for health and estimated concurrency analytics.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .database import DatabaseManager, DatabaseEngine, get_db_manager
from .local_storage import LocalStorage, get_local_storage

LOG_TYPE_CONSUMPTION = 2
LOG_TYPE_FAILURE = 5

WINDOW_SECONDS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "3d": 3 * 24 * 3600,
    "7d": 7 * 24 * 3600,
    "14d": 14 * 24 * 3600,
}


@dataclass
class ChannelAggregate:
    channel_id: int
    total_requests: int
    success_requests: int
    failure_requests: int
    quota_used: int
    avg_response_time: float
    last_request_at: int


class ChannelInsightsService:
    """Aggregate channel health, throughput, and estimated concurrency."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        storage: Optional[LocalStorage] = None,
    ):
        self._db = db
        self._storage = storage

    @property
    def db(self) -> DatabaseManager:
        if self._db is None:
            self._db = get_db_manager()
        return self._db

    @property
    def storage(self) -> LocalStorage:
        if self._storage is None:
            self._storage = get_local_storage()
        return self._storage

    def get_overview(self, window: str = "24h", limit: int = 20, use_cache: bool = True) -> Dict[str, Any]:
        window_seconds = self._get_window_seconds(window)
        cache_key = f"channel_insights:overview:{window}:{limit}"

        if use_cache:
            cached = self.storage.cache_get(cache_key)
            if cached:
                return cached

        end_time = int(time.time())
        start_time = end_time - window_seconds

        channels = self._fetch_channels()
        aggregates = self._fetch_channel_aggregates(start_time, end_time)
        ranked_channel_ids = self._rank_channel_ids(channels, aggregates, limit)
        concurrency = self._estimate_concurrency_for_channels(ranked_channel_ids, start_time, end_time)

        items = [
            self._build_channel_item(
                channel=channels.get(channel_id, {"id": channel_id, "name": f"Channel#{channel_id}"}),
                aggregate=aggregates.get(channel_id),
                concurrency=concurrency.get(channel_id),
            )
            for channel_id in ranked_channel_ids
        ]

        summary = self._build_summary(items, start_time, end_time, window)
        data = {
            "supported": True,
            "summary": summary,
            "items": items,
            "assumptions": [
                "并发值为基于 logs.created_at 与 use_time 的估算值，不是调度层实时精确值",
                "logs.created_at 被按“请求完成时间”解释，因此估算区间为 [created_at - use_time, created_at]",
                "成功/失败口径沿用日志类型：type=2 为成功请求，type=5 为失败请求",
            ],
        }

        self.storage.cache_set(cache_key, data, ttl=180)
        return data

    def get_channel_detail(self, channel_id: int, window: str = "24h", use_cache: bool = True) -> Dict[str, Any]:
        window_seconds = self._get_window_seconds(window)
        cache_key = f"channel_insights:detail:{channel_id}:{window}"

        if use_cache:
            cached = self.storage.cache_get(cache_key)
            if cached:
                return cached

        end_time = int(time.time())
        start_time = end_time - window_seconds
        channels = self._fetch_channels(channel_id=channel_id)
        channel = channels.get(channel_id)
        if channel is None:
            return {
                "supported": False,
                "reason": f"channel {channel_id} not found",
            }

        aggregate = self._fetch_channel_aggregates(start_time, end_time, channel_ids=[channel_id]).get(channel_id)
        concurrency = self._estimate_concurrency_for_channels([channel_id], start_time, end_time).get(channel_id)
        item = self._build_channel_item(channel=channel, aggregate=aggregate, concurrency=concurrency)
        timeline = self._fetch_channel_timeline(channel_id, start_time, end_time, window)

        data = {
            "supported": True,
            "channel": item,
            "timeline": timeline,
            "summary": {
                "window": window,
                "start_time": start_time,
                "end_time": end_time,
            },
        }
        self.storage.cache_set(cache_key, data, ttl=180)
        return data

    def invalidate_cache(self) -> int:
        return self.storage.cache_clear("channel_insights:%")

    def _get_window_seconds(self, window: str) -> int:
        if window not in WINDOW_SECONDS:
            raise ValueError(f"Unsupported window: {window}")
        return WINDOW_SECONDS[window]

    def _fetch_channels(self, channel_id: Optional[int] = None) -> Dict[int, Dict[str, Any]]:
        sql = """
            SELECT
                id,
                name,
                status,
                type,
                balance,
                used_quota,
                response_time,
                test_time
            FROM channels
        """
        params: Dict[str, Any] = {}
        if channel_id is not None:
            sql += " WHERE id = :channel_id"
            params["channel_id"] = channel_id
        sql += " ORDER BY id ASC"

        rows = self.db.execute(sql, params)
        return {
            int(row["id"]): {
                "id": int(row["id"]),
                "name": row.get("name") or f"Channel#{row['id']}",
                "status": int(row.get("status") or 0),
                "type": int(row.get("type") or 0),
                "balance": float(row.get("balance") or 0),
                "used_quota": int(row.get("used_quota") or 0),
                "response_time": int(row.get("response_time") or 0),
                "last_test": int(row.get("test_time") or 0),
            }
            for row in rows
        }

    def _fetch_channel_aggregates(
        self,
        start_time: int,
        end_time: int,
        channel_ids: Optional[List[int]] = None,
    ) -> Dict[int, ChannelAggregate]:
        sql = """
            SELECT
                channel_id,
                COUNT(*) as total_requests,
                SUM(CASE WHEN type = :success_type THEN 1 ELSE 0 END) as success_requests,
                SUM(CASE WHEN type = :failure_type THEN 1 ELSE 0 END) as failure_requests,
                COALESCE(SUM(quota), 0) as quota_used,
                COALESCE(AVG(use_time), 0) as avg_response_time,
                MAX(created_at) as last_request_at
            FROM logs
            WHERE created_at >= :start_time
              AND created_at <= :end_time
              AND channel_id IS NOT NULL
              AND type IN (:success_type, :failure_type)
        """
        params: Dict[str, Any] = {
            "start_time": start_time,
            "end_time": end_time,
            "success_type": LOG_TYPE_CONSUMPTION,
            "failure_type": LOG_TYPE_FAILURE,
        }
        if channel_ids:
            channel_clause, channel_params = self._build_in_clause("channel_id", channel_ids)
            sql += f" AND channel_id IN ({channel_clause})"
            params.update(channel_params)

        sql += " GROUP BY channel_id"
        rows = self.db.execute(sql, params)
        return {
            int(row["channel_id"]): ChannelAggregate(
                channel_id=int(row["channel_id"]),
                total_requests=int(row.get("total_requests") or 0),
                success_requests=int(row.get("success_requests") or 0),
                failure_requests=int(row.get("failure_requests") or 0),
                quota_used=int(row.get("quota_used") or 0),
                avg_response_time=float(row.get("avg_response_time") or 0),
                last_request_at=int(row.get("last_request_at") or 0),
            )
            for row in rows
        }

    def _rank_channel_ids(
        self,
        channels: Dict[int, Dict[str, Any]],
        aggregates: Dict[int, ChannelAggregate],
        limit: int,
    ) -> List[int]:
        def sort_key(channel_id: int) -> tuple[int, int, int]:
            aggregate = aggregates.get(channel_id)
            total_requests = aggregate.total_requests if aggregate else 0
            failure_requests = aggregate.failure_requests if aggregate else 0
            status = int(channels.get(channel_id, {}).get("status") or 0)
            return (total_requests, failure_requests, status)

        candidate_ids = set(channels.keys()) | set(aggregates.keys())
        ranked = sorted(candidate_ids, key=sort_key, reverse=True)
        return ranked[: max(1, min(limit, len(ranked) or 1))]

    def _estimate_concurrency_for_channels(
        self,
        channel_ids: Iterable[int],
        start_time: int,
        end_time: int,
    ) -> Dict[int, Dict[str, int]]:
        channel_ids = [int(channel_id) for channel_id in channel_ids]
        if not channel_ids:
            return {}

        channel_clause, channel_params = self._build_in_clause("channel_id", channel_ids)
        sql = f"""
            SELECT
                channel_id,
                created_at,
                use_time
            FROM logs
            WHERE created_at >= :start_time
              AND created_at <= :end_time
              AND channel_id IN ({channel_clause})
              AND type IN (:success_type, :failure_type)
            ORDER BY created_at ASC
        """
        params = {
            "start_time": start_time,
            "end_time": end_time,
            "success_type": LOG_TYPE_CONSUMPTION,
            "failure_type": LOG_TYPE_FAILURE,
            **channel_params,
        }
        rows = self.db.execute(sql, params)

        grouped: Dict[int, List[Dict[str, Any]]] = {channel_id: [] for channel_id in channel_ids}
        for row in rows:
            grouped.setdefault(int(row["channel_id"]), []).append(row)

        return {
            channel_id: self._estimate_channel_concurrency(rows_for_channel)
            for channel_id, rows_for_channel in grouped.items()
        }

    def _estimate_channel_concurrency(self, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        if not rows:
            return {
                "estimated_peak_concurrency": 0,
                "estimated_p95_concurrency": 0,
            }

        events: List[tuple[int, int]] = []
        for row in rows:
            duration_ms = max(int(row.get("use_time") or 0), 1)
            end_ms = int(row.get("created_at") or 0) * 1000
            start_ms = max(0, end_ms - duration_ms)
            events.append((start_ms, 1))
            events.append((end_ms, -1))

        events.sort(key=lambda item: (item[0], item[1]))

        active = 0
        samples: List[int] = []
        for _, delta in events:
            active += delta
            if active < 0:
                active = 0
            samples.append(active)

        peak = max(samples) if samples else 0
        non_zero_samples = [value for value in samples if value > 0]
        if not non_zero_samples:
            p95 = 0
        else:
            ordered = sorted(non_zero_samples)
            index = max(0, math.ceil(len(ordered) * 0.95) - 1)
            p95 = ordered[index]

        return {
            "estimated_peak_concurrency": int(peak),
            "estimated_p95_concurrency": int(p95),
        }

    def _fetch_channel_timeline(self, channel_id: int, start_time: int, end_time: int, window: str) -> List[Dict[str, Any]]:
        bucket_expr = self._get_bucket_expr(window)
        sql = f"""
            SELECT
                {bucket_expr} as bucket,
                COUNT(*) as total_requests,
                SUM(CASE WHEN type = :success_type THEN 1 ELSE 0 END) as success_requests,
                SUM(CASE WHEN type = :failure_type THEN 1 ELSE 0 END) as failure_requests,
                COALESCE(AVG(use_time), 0) as avg_response_time
            FROM logs
            WHERE created_at >= :start_time
              AND created_at <= :end_time
              AND channel_id = :channel_id
              AND type IN (:success_type, :failure_type)
            GROUP BY {bucket_expr}
            ORDER BY bucket ASC
        """
        rows = self.db.execute(
            sql,
            {
                "start_time": start_time,
                "end_time": end_time,
                "channel_id": channel_id,
                "success_type": LOG_TYPE_CONSUMPTION,
                "failure_type": LOG_TYPE_FAILURE,
            },
        )
        timeline = []
        for row in rows:
            total_requests = int(row.get("total_requests") or 0)
            failure_requests = int(row.get("failure_requests") or 0)
            timeline.append(
                {
                    "bucket": row.get("bucket"),
                    "total_requests": total_requests,
                    "success_requests": int(row.get("success_requests") or 0),
                    "failure_requests": failure_requests,
                    "error_rate": round((failure_requests / total_requests) if total_requests else 0.0, 4),
                    "average_response_time": round(float(row.get("avg_response_time") or 0), 2),
                }
            )
        return timeline

    def _get_bucket_expr(self, window: str) -> str:
        large_window = window in {"3d", "7d", "14d"}
        if self.db.config.engine == DatabaseEngine.POSTGRESQL:
            fmt = "YYYY-MM-DD HH24:00" if not large_window else "YYYY-MM-DD"
            return f"to_char(to_timestamp(created_at), '{fmt}')"
        fmt = "%Y-%m-%d %H:00" if not large_window else "%Y-%m-%d"
        return f"DATE_FORMAT(FROM_UNIXTIME(created_at), '{fmt}')"

    def _build_channel_item(
        self,
        channel: Dict[str, Any],
        aggregate: Optional[ChannelAggregate],
        concurrency: Optional[Dict[str, int]],
    ) -> Dict[str, Any]:
        total_requests = aggregate.total_requests if aggregate else 0
        success_requests = aggregate.success_requests if aggregate else 0
        failure_requests = aggregate.failure_requests if aggregate else 0
        error_rate = (failure_requests / total_requests) if total_requests else 0.0
        average_response_time = round(aggregate.avg_response_time if aggregate else 0.0, 2)
        health_score = round(
            self._calculate_health_score(
                status=int(channel.get("status") or 0),
                error_rate=error_rate,
                average_response_time=average_response_time,
                last_test=int(channel.get("last_test") or 0),
            ),
            2,
        )
        health_status = self._classify_health_status(health_score)

        return {
            "id": int(channel["id"]),
            "name": channel.get("name") or f"Channel#{channel['id']}",
            "status": int(channel.get("status") or 0),
            "type": int(channel.get("type") or 0),
            "balance": float(channel.get("balance") or 0),
            "used_quota": int(channel.get("used_quota") or 0),
            "current_response_time": int(channel.get("response_time") or 0),
            "last_test": int(channel.get("last_test") or 0),
            "total_requests": total_requests,
            "success_requests": success_requests,
            "failure_requests": failure_requests,
            "error_rate": round(error_rate, 4),
            "average_response_time": average_response_time,
            "quota_used": int(aggregate.quota_used if aggregate else 0),
            "last_request_at": int(aggregate.last_request_at if aggregate else 0),
            "estimated_peak_concurrency": int((concurrency or {}).get("estimated_peak_concurrency", 0)),
            "estimated_p95_concurrency": int((concurrency or {}).get("estimated_p95_concurrency", 0)),
            "health_score": health_score,
            "health_status": health_status,
        }

    def _build_summary(self, items: List[Dict[str, Any]], start_time: int, end_time: int, window: str) -> Dict[str, Any]:
        health_scores = [float(item["health_score"]) for item in items]
        peak_values = [int(item["estimated_peak_concurrency"]) for item in items]
        p95_values = [int(item["estimated_p95_concurrency"]) for item in items]
        return {
            "window": window,
            "start_time": start_time,
            "end_time": end_time,
            "channel_count": len(items),
            "active_channels": sum(1 for item in items if int(item["status"]) == 1),
            "channels_with_traffic": sum(1 for item in items if int(item["total_requests"]) > 0),
            "warning_channels": sum(1 for item in items if item["health_status"] == "warning"),
            "critical_channels": sum(1 for item in items if item["health_status"] == "critical"),
            "average_health_score": round(sum(health_scores) / len(health_scores), 2) if health_scores else 0.0,
            "max_estimated_peak_concurrency": max(peak_values) if peak_values else 0,
            "max_estimated_p95_concurrency": max(p95_values) if p95_values else 0,
        }

    def _calculate_health_score(
        self,
        status: int,
        error_rate: float,
        average_response_time: float,
        last_test: int,
    ) -> float:
        status_component = 100.0 if status == 1 else 25.0
        error_component = max(0.0, 100.0 - error_rate * 100.0)
        if average_response_time <= 0:
            latency_component = 50.0
        elif average_response_time <= 1000:
            latency_component = 100.0
        elif average_response_time <= 3000:
            latency_component = 80.0
        elif average_response_time <= 5000:
            latency_component = 60.0
        elif average_response_time <= 10000:
            latency_component = 40.0
        else:
            latency_component = 20.0

        now = int(time.time())
        if not last_test:
            test_component = 40.0
        elif now - last_test <= 24 * 3600:
            test_component = 100.0
        elif now - last_test <= 7 * 24 * 3600:
            test_component = 70.0
        else:
            test_component = 40.0

        return (
            status_component * 0.35
            + error_component * 0.4
            + latency_component * 0.2
            + test_component * 0.05
        )

    def _classify_health_status(self, health_score: float) -> str:
        if health_score < 50:
            return "critical"
        if health_score < 75:
            return "warning"
        return "healthy"

    def _build_in_clause(self, prefix: str, values: Iterable[int]) -> tuple[str, Dict[str, int]]:
        params: Dict[str, int] = {}
        placeholders: List[str] = []
        for index, value in enumerate(values):
            key = f"{prefix}_{index}"
            placeholders.append(f":{key}")
            params[key] = int(value)
        return ", ".join(placeholders), params


_channel_insights_service: Optional[ChannelInsightsService] = None


def get_channel_insights_service() -> ChannelInsightsService:
    global _channel_insights_service
    if _channel_insights_service is None:
        _channel_insights_service = ChannelInsightsService()
    return _channel_insights_service

"""
Subscription analytics service with runtime schema probing.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .database import DatabaseEngine, DatabaseManager, get_db_manager

PLAN_REQUIRED_COLUMNS = {
    "id",
    "title",
    "price_amount",
    "currency",
    "enabled",
}

SUBSCRIPTION_REQUIRED_COLUMNS = {
    "id",
    "user_id",
    "plan_id",
    "amount_total",
    "amount_used",
    "start_time",
    "end_time",
    "status",
}

PLAN_OPTIONAL_COLUMNS = [
    "subtitle",
    "duration_unit",
    "duration_value",
    "custom_seconds",
    "sort_order",
    "max_purchase_per_user",
    "upgrade_group",
    "total_amount",
    "quota_reset_period",
    "quota_reset_custom_seconds",
    "created_at",
    "updated_at",
]

SUBSCRIPTION_OPTIONAL_COLUMNS = [
    "source",
    "grant_key",
    "last_reset_time",
    "next_reset_time",
    "upgrade_group",
    "prev_user_group",
    "created_at",
    "updated_at",
]


class SubscriptionAnalyticsService:
    """Read-only subscription analytics with explicit unsupported branch."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self._db = db

    @property
    def db(self) -> DatabaseManager:
        if self._db is None:
            self._db = get_db_manager()
        return self._db

    def get_overview(self) -> Dict[str, Any]:
        schema = self._probe_schema()
        if not schema["supported"]:
            return {
                "supported": False,
                "reason": schema["reason"],
                "schema": schema["schema"],
            }

        plans = self._fetch_plans(schema["schema"]["subscription_plans"]["columns"])
        plan_map = {int(plan["id"]): plan for plan in plans}
        subscriptions = self._fetch_subscriptions(schema["schema"]["user_subscriptions"]["columns"])

        active_subscriptions: List[Dict[str, Any]] = []
        plan_stats: Dict[int, Dict[str, Any]] = {
            int(plan["id"]): {
                "subscriber_count": 0,
                "active_subscriber_count": 0,
                "total_amount": 0,
                "used_amount": 0,
            }
            for plan in plans
        }

        total_amount = 0
        total_used = 0
        for item in subscriptions:
            plan_id = int(item.get("plan_id") or 0)
            stats = plan_stats.setdefault(
                plan_id,
                {
                    "subscriber_count": 0,
                    "active_subscriber_count": 0,
                    "total_amount": 0,
                    "used_amount": 0,
                },
            )
            stats["subscriber_count"] += 1
            stats["total_amount"] += int(item.get("amount_total") or 0)
            stats["used_amount"] += int(item.get("amount_used") or 0)
            total_amount += int(item.get("amount_total") or 0)
            total_used += int(item.get("amount_used") or 0)

            active = self._is_active_subscription(item)
            if active:
                stats["active_subscriber_count"] += 1
                active_subscriptions.append(
                    {
                        **item,
                        "plan_title": plan_map.get(plan_id, {}).get("title") or f"Plan#{plan_id}",
                        "remaining_amount": max(0, int(item.get("amount_total") or 0) - int(item.get("amount_used") or 0)),
                    }
                )

        enriched_plans = []
        for plan in plans:
            plan_id = int(plan["id"])
            stats = plan_stats.get(plan_id, {})
            total_plan_amount = int(stats.get("total_amount") or 0)
            used_plan_amount = int(stats.get("used_amount") or 0)
            usage_rate = round((used_plan_amount / total_plan_amount), 4) if total_plan_amount else 0.0
            enriched_plans.append(
                {
                    **plan,
                    "subscriber_count": int(stats.get("subscriber_count") or 0),
                    "active_subscriber_count": int(stats.get("active_subscriber_count") or 0),
                    "usage_rate": usage_rate,
                }
            )

        active_subscriptions.sort(
            key=lambda item: (
                int(item.get("end_time") or 0),
                int(item.get("amount_total") or 0) - int(item.get("amount_used") or 0),
            ),
            reverse=True,
        )

        summary = {
            "total_plans": len(plans),
            "enabled_plans": sum(1 for plan in plans if self._to_bool(plan.get("enabled"))),
            "total_subscriptions": len(subscriptions),
            "active_subscriptions": len(active_subscriptions),
            "expired_or_inactive_subscriptions": max(0, len(subscriptions) - len(active_subscriptions)),
            "total_amount": total_amount,
            "total_used": total_used,
            "total_remaining": max(0, total_amount - total_used),
            "overall_usage_rate": round((total_used / total_amount), 4) if total_amount else 0.0,
        }

        return {
            "supported": True,
            "reason": "",
            "schema": schema["schema"],
            "summary": summary,
            "plans": enriched_plans,
            "active_subscriptions": active_subscriptions[:100],
        }

    def _probe_schema(self) -> Dict[str, Any]:
        plan_columns = self._get_table_columns("subscription_plans")
        subscription_columns = self._get_table_columns("user_subscriptions")

        missing_tables: List[str] = []
        if not plan_columns:
            missing_tables.append("subscription_plans")
        if not subscription_columns:
            missing_tables.append("user_subscriptions")

        schema = {
            "subscription_plans": {
                "exists": bool(plan_columns),
                "columns": sorted(plan_columns),
            },
            "user_subscriptions": {
                "exists": bool(subscription_columns),
                "columns": sorted(subscription_columns),
            },
        }

        if missing_tables:
            return {
                "supported": False,
                "reason": f"missing required tables: {', '.join(missing_tables)}",
                "schema": schema,
            }

        missing_plan_columns = sorted(PLAN_REQUIRED_COLUMNS - plan_columns)
        missing_subscription_columns = sorted(SUBSCRIPTION_REQUIRED_COLUMNS - subscription_columns)
        if missing_plan_columns or missing_subscription_columns:
            reasons: List[str] = []
            if missing_plan_columns:
                reasons.append(f"subscription_plans missing columns: {', '.join(missing_plan_columns)}")
            if missing_subscription_columns:
                reasons.append(f"user_subscriptions missing columns: {', '.join(missing_subscription_columns)}")
            return {
                "supported": False,
                "reason": "; ".join(reasons),
                "schema": schema,
            }

        return {
            "supported": True,
            "reason": "",
            "schema": schema,
        }

    def _fetch_plans(self, columns: List[str]) -> List[Dict[str, Any]]:
        selected = [column for column in (["id", "title", "price_amount", "currency", "enabled"] + PLAN_OPTIONAL_COLUMNS) if column in columns]
        order_by = "sort_order ASC, id ASC" if "sort_order" in columns else "id ASC"
        sql = f"SELECT {', '.join(self._quote_identifier(column) for column in selected)} FROM subscription_plans ORDER BY {order_by}"
        rows = self.db.execute(sql)
        result = []
        for row in rows:
            item = {column: row.get(column) for column in selected}
            item["enabled"] = self._to_bool(item.get("enabled"))
            result.append(item)
        return result

    def _fetch_subscriptions(self, columns: List[str]) -> List[Dict[str, Any]]:
        selected = [column for column in (["id", "user_id", "plan_id", "amount_total", "amount_used", "start_time", "end_time", "status"] + SUBSCRIPTION_OPTIONAL_COLUMNS) if column in columns]
        join_user = self._get_table_columns("users")
        include_username = "username" in join_user

        select_parts = [f"s.{self._quote_identifier(column)} AS {self._quote_identifier(column)}" for column in selected]
        join_sql = ""
        if include_username:
            select_parts.append("u.username AS username")
            join_sql = " LEFT JOIN users u ON u.id = s.user_id"

        sql = f"""
            SELECT {', '.join(select_parts)}
            FROM user_subscriptions s
            {join_sql}
            ORDER BY s.{self._quote_identifier('end_time')} DESC, s.{self._quote_identifier('id')} DESC
        """
        rows = self.db.execute(sql)
        result: List[Dict[str, Any]] = []
        for row in rows:
            item = {column: row.get(column) for column in selected}
            if include_username:
                item["username"] = row.get("username") or ""
            result.append(item)
        return result

    def _get_table_columns(self, table_name: str) -> set[str]:
        if self.db.config.engine == DatabaseEngine.POSTGRESQL:
            sql = """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
            """
            rows = self.db.execute(sql, {"table_name": table_name})
        else:
            sql = """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
            """
            rows = self.db.execute(sql, {"schema_name": self.db.config.database, "table_name": table_name})
        return {str(row["column_name"]) for row in rows}

    def _quote_identifier(self, name: str) -> str:
        if self.db.config.engine == DatabaseEngine.POSTGRESQL:
            return f'"{name}"'
        return f"`{name}`"

    def _is_active_subscription(self, item: Dict[str, Any]) -> bool:
        status_value = str(item.get("status") or "").strip().lower()
        inactive_statuses = {"0", "-1", "inactive", "expired", "cancelled", "canceled", "disabled", "ended"}
        if status_value in inactive_statuses:
            return False

        end_time = int(item.get("end_time") or 0)
        if end_time > 0 and end_time < int(time.time()):
            return False
        return True

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return int(value) != 0
        return str(value).strip().lower() in {"1", "true", "yes", "on"}


_subscription_analytics_service: Optional[SubscriptionAnalyticsService] = None


def get_subscription_analytics_service() -> SubscriptionAnalyticsService:
    global _subscription_analytics_service
    if _subscription_analytics_service is None:
        _subscription_analytics_service = SubscriptionAnalyticsService()
    return _subscription_analytics_service

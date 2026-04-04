"""
Temporary account management service.

Uses main database users/tokens tables plus local SQLite sidecar metadata.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Dict, Iterable, List, Optional

import bcrypt
from sqlalchemy import text

from .database import DatabaseEngine, DatabaseManager, get_db_manager
from .key_generator import get_key_generator
from .local_storage import LocalStorage, get_local_storage


class TemporaryAccountService:
    """Create, list, and manage temporary accounts."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        storage: Optional[LocalStorage] = None,
        user_management_service: Optional[Any] = None,
    ):
        self._db = db
        self._storage = storage
        self._user_management_service = user_management_service

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

    @property
    def user_management_service(self):
        if self._user_management_service is None:
            from .user_management_service import get_user_management_service

            self._user_management_service = get_user_management_service()
        return self._user_management_service

    def get_capability(self) -> Dict[str, Any]:
        return self._probe_creation_capability()

    def list_accounts(self, page: int = 1, page_size: int = 20, status: Optional[str] = None) -> Dict[str, Any]:
        sidecar_page = self.storage.list_temporary_accounts(page=page, page_size=page_size, status=status)
        items = sidecar_page["items"]

        user_ids = [int(item["user_id"]) for item in items]
        token_ids = [int(item["default_token_id"]) for item in items if int(item.get("default_token_id") or 0) > 0]

        user_details = self._fetch_user_details(user_ids)
        token_details = self._fetch_token_details(token_ids)

        merged_items = []
        for item in items:
            user_id = int(item["user_id"])
            token_id = int(item.get("default_token_id") or 0)
            main_user = user_details.get(user_id, {})
            default_token = token_details.get(token_id, {}) if token_id else {}
            merged_items.append(
                {
                    **item,
                    "main_user": main_user,
                    "default_token": default_token,
                    "is_expired": bool(item.get("expires_at")) and int(item.get("expires_at") or 0) < int(time.time()),
                }
            )

        summary = {
            "total": int(sidecar_page["total"]),
            "active": sum(1 for item in merged_items if item.get("status") == "active"),
            "disabled": sum(1 for item in merged_items if item.get("status") == "disabled"),
            "expired": sum(1 for item in merged_items if item.get("is_expired")),
        }

        capability = self._probe_creation_capability()
        return {
            **sidecar_page,
            "summary": summary,
            "capability": capability,
            "items": merged_items,
            "recent_events": self.storage.list_temporary_account_events(limit=20),
        }

    def create_account(
        self,
        *,
        username: str,
        remark: str = "",
        created_by: str = "",
        expires_at: int = 0,
        quota: int = 0,
        group_name: str = "default",
        token_name: str = "",
        email: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        capability = self._probe_creation_capability()
        if not capability["supported"]:
            return {
                "success": False,
                "message": capability["reason"],
                "capability": capability,
            }

        normalized_username = username.strip()
        if not normalized_username:
            return {"success": False, "message": "username is required", "capability": capability}

        existing_sql = "SELECT id FROM users WHERE username = :username AND deleted_at IS NULL"
        existing = self.db.execute(existing_sql, {"username": normalized_username})
        if existing:
            return {"success": False, "message": f"username already exists: {normalized_username}", "capability": capability}

        user_meta = capability["tables"]["users"]["meta"]
        token_meta = capability["tables"]["tokens"]["meta"]

        generated_email = email or f"{normalized_username}@temporary.local"
        generated_display_name = display_name or normalized_username
        generated_password = self._hash_password(secrets.token_urlsafe(16))
        now = int(time.time())
        token_key = get_key_generator().generate_key("tmp")
        token_label = token_name or f"temp-{normalized_username}"

        user_payload = self._build_user_insert_payload(
            meta=user_meta,
            username=normalized_username,
            password=generated_password,
            display_name=generated_display_name,
            email=generated_email,
            quota=quota,
            group_name=group_name,
            now=now,
        )
        token_payload_template = self._build_token_insert_payload(
            meta=token_meta,
            user_id=0,
            token_key=token_key,
            token_name=token_label,
            quota=quota,
            expires_at=expires_at,
            group_name=group_name,
            now=now,
        )

        sidecar_row_id = 0
        user_id = 0
        token_id = 0
        try:
            with self.db.engine.connect() as conn:
                trans = conn.begin()
                try:
                    user_id = self._insert_row(conn, "users", user_payload)
                    token_payload = {**token_payload_template, "user_id": user_id}
                    token_id = self._insert_row(conn, "tokens", token_payload)

                    masked_key = self._mask_token_key(token_key)
                    sidecar_row_id = self.storage.create_temporary_account(
                        user_id=user_id,
                        username=normalized_username,
                        default_token_id=token_id,
                        default_token_key_masked=masked_key,
                        created_by=created_by,
                        remark=remark,
                        status="active",
                        expires_at=expires_at,
                        created_at=now,
                    )
                    self.storage.add_temporary_account_event(
                        user_id=user_id,
                        action="create",
                        operator=created_by,
                        detail={
                            "username": normalized_username,
                            "default_token_id": token_id,
                            "expires_at": expires_at,
                            "quota": quota,
                        },
                        temporary_account_id=sidecar_row_id,
                        created_at=now,
                    )
                    trans.commit()
                except Exception:
                    trans.rollback()
                    raise
        except Exception as exc:
            if sidecar_row_id and user_id:
                self.storage.delete_temporary_account(user_id=user_id)
            return {
                "success": False,
                "message": f"failed to create temporary account: {exc}",
                "capability": capability,
            }

        return {
            "success": True,
            "message": "temporary account created",
            "capability": capability,
            "data": {
                "user_id": user_id,
                "username": normalized_username,
                "default_token_id": token_id,
                "default_token_key": token_key,
                "default_token_key_masked": self._mask_token_key(token_key),
                "expires_at": expires_at,
                "remark": remark,
                "created_by": created_by,
            },
        }

    def disable_account(self, user_id: int, operator: str = "", reason: str = "") -> Dict[str, Any]:
        metadata = self.storage.get_temporary_account(user_id)
        if metadata is None:
            return {"success": False, "message": f"temporary account not found: {user_id}"}

        result = self.user_management_service.ban_user(
            user_id=user_id,
            reason=reason or "temporary account disabled",
            disable_tokens=True,
            operator=operator,
            context={"source": "temporary_account_service"},
        )
        if not result.get("success"):
            return result

        self.storage.update_temporary_account(user_id, status="disabled")
        self.storage.add_temporary_account_event(
            user_id=user_id,
            action="disable",
            operator=operator,
            detail={"reason": reason or "temporary account disabled"},
            temporary_account_id=int(metadata["id"]),
        )
        return {"success": True, "message": result.get("message") or "temporary account disabled"}

    def enable_account(self, user_id: int, operator: str = "", reason: str = "") -> Dict[str, Any]:
        metadata = self.storage.get_temporary_account(user_id)
        if metadata is None:
            return {"success": False, "message": f"temporary account not found: {user_id}"}

        result = self.user_management_service.unban_user(
            user_id=user_id,
            reason=reason or "temporary account enabled",
            enable_tokens=True,
            operator=operator,
            context={"source": "temporary_account_service"},
        )
        if not result.get("success"):
            return result

        new_status = "expired" if metadata.get("expires_at") and int(metadata["expires_at"]) < int(time.time()) else "active"
        self.storage.update_temporary_account(user_id, status=new_status)
        self.storage.add_temporary_account_event(
            user_id=user_id,
            action="enable",
            operator=operator,
            detail={"reason": reason or "temporary account enabled"},
            temporary_account_id=int(metadata["id"]),
        )
        return {"success": True, "message": result.get("message") or "temporary account enabled"}

    def _probe_creation_capability(self) -> Dict[str, Any]:
        users_meta = self._describe_table("users")
        tokens_meta = self._describe_table("tokens")

        tables = {
            "users": {
                "exists": bool(users_meta),
                "columns": sorted(users_meta.keys()),
                "required_insert_columns": self._required_insert_columns(users_meta),
                "meta": users_meta,
            },
            "tokens": {
                "exists": bool(tokens_meta),
                "columns": sorted(tokens_meta.keys()),
                "required_insert_columns": self._required_insert_columns(tokens_meta),
                "meta": tokens_meta,
            },
        }

        if not users_meta or not tokens_meta:
            missing = [name for name, info in tables.items() if not info["exists"]]
            return {
                "supported": False,
                "reason": f"missing required tables: {', '.join(missing)}",
                "tables": tables,
            }

        missing_users = self._required_insert_columns(users_meta) - {"id", "username", "password", "display_name", "email", "role", "status", "quota", "used_quota", "request_count", "group", "created_at", "created_time", "access_token", "aff_code", "aff_count", "aff_quota", "aff_history", "inviter_id"}
        missing_tokens = self._required_insert_columns(tokens_meta) - {"id", "user_id", "key", "status", "name", "quota", "remain_quota", "used_quota", "unlimited_quota", "created_time", "created_at", "accessed_time", "expired_time", "group", "models", "subnet"}

        if missing_users or missing_tokens:
            reasons: List[str] = []
            if missing_users:
                reasons.append(f"users table has unsupported required columns: {', '.join(sorted(missing_users))}")
            if missing_tokens:
                reasons.append(f"tokens table has unsupported required columns: {', '.join(sorted(missing_tokens))}")
            return {
                "supported": False,
                "reason": "; ".join(reasons),
                "tables": tables,
            }

        for required_column in ("username", "password"):
            if required_column not in users_meta:
                return {
                    "supported": False,
                    "reason": f"users missing required creation column: {required_column}",
                    "tables": tables,
                }
        for required_column in ("user_id", "key"):
            if required_column not in tokens_meta:
                return {
                    "supported": False,
                    "reason": f"tokens missing required creation column: {required_column}",
                    "tables": tables,
                }

        return {
            "supported": True,
            "reason": "",
            "tables": tables,
        }

    def _build_user_insert_payload(
        self,
        *,
        meta: Dict[str, Dict[str, Any]],
        username: str,
        password: str,
        display_name: str,
        email: str,
        quota: int,
        group_name: str,
        now: int,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "username": username,
            "password": password,
        }
        if "display_name" in meta:
            payload["display_name"] = display_name
        if "email" in meta:
            payload["email"] = email
        if "role" in meta:
            payload["role"] = 1
        if "status" in meta:
            payload["status"] = 1
        if "quota" in meta:
            payload["quota"] = int(quota or 0)
        if "used_quota" in meta:
            payload["used_quota"] = 0
        if "request_count" in meta:
            payload["request_count"] = 0
        if "group" in meta:
            payload["group"] = group_name
        if "created_at" in meta:
            payload["created_at"] = now
        if "created_time" in meta:
            payload["created_time"] = now
        if "access_token" in meta:
            payload["access_token"] = ""
        if "aff_code" in meta:
            payload["aff_code"] = ""
        if "aff_count" in meta:
            payload["aff_count"] = 0
        if "aff_quota" in meta:
            payload["aff_quota"] = 0
        if "aff_history" in meta:
            payload["aff_history"] = ""
        if "inviter_id" in meta:
            payload["inviter_id"] = 0
        return payload

    def _build_token_insert_payload(
        self,
        *,
        meta: Dict[str, Dict[str, Any]],
        user_id: int,
        token_key: str,
        token_name: str,
        quota: int,
        expires_at: int,
        group_name: str,
        now: int,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "key": token_key,
        }
        if "status" in meta:
            payload["status"] = 1
        if "name" in meta:
            payload["name"] = token_name
        if "quota" in meta:
            payload["quota"] = int(quota or 0)
        if "remain_quota" in meta:
            payload["remain_quota"] = int(quota or 0)
        if "used_quota" in meta:
            payload["used_quota"] = 0
        if "unlimited_quota" in meta:
            payload["unlimited_quota"] = 1 if quota <= 0 else 0
        if "created_time" in meta:
            payload["created_time"] = now
        if "created_at" in meta:
            payload["created_at"] = now
        if "accessed_time" in meta:
            payload["accessed_time"] = 0
        if "expired_time" in meta:
            payload["expired_time"] = int(expires_at or 0)
        if "group" in meta:
            payload["group"] = group_name
        if "models" in meta:
            payload["models"] = ""
        if "subnet" in meta:
            payload["subnet"] = ""
        return payload

    def _describe_table(self, table_name: str) -> Dict[str, Dict[str, Any]]:
        if self.db.config.engine == DatabaseEngine.POSTGRESQL:
            sql = """
                SELECT
                    column_name,
                    is_nullable,
                    column_default,
                    '' as extra
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
            """
            rows = self.db.execute(sql, {"table_name": table_name})
        else:
            sql = """
                SELECT
                    column_name,
                    is_nullable,
                    column_default,
                    extra
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
            """
            rows = self.db.execute(sql, {"schema_name": self.db.config.database, "table_name": table_name})

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            column_name = str(row["column_name"])
            default_value = row.get("column_default")
            extra = str(row.get("extra") or "")
            auto_generated = "auto_increment" in extra.lower() or (default_value and "nextval(" in str(default_value).lower())
            result[column_name] = {
                "is_nullable": str(row.get("is_nullable") or "").upper() == "YES",
                "column_default": default_value,
                "extra": extra,
                "auto_generated": auto_generated,
            }
        return result

    def _required_insert_columns(self, meta: Dict[str, Dict[str, Any]]) -> set[str]:
        required = set()
        for column_name, info in meta.items():
            if info.get("auto_generated"):
                continue
            if info.get("is_nullable"):
                continue
            if info.get("column_default") is not None:
                continue
            required.add(column_name)
        return required

    def _insert_row(self, conn, table_name: str, payload: Dict[str, Any]) -> int:
        quoted_columns = ", ".join(self._quote_identifier(column) for column in payload.keys())
        value_params = ", ".join(f":{column}" for column in payload.keys())
        if self.db.config.engine == DatabaseEngine.POSTGRESQL:
            sql = f"INSERT INTO {table_name} ({quoted_columns}) VALUES ({value_params}) RETURNING id"
            row = conn.execute(text(sql), payload).fetchone()
            return int(row[0])

        sql = f"INSERT INTO {table_name} ({quoted_columns}) VALUES ({value_params})"
        result = conn.execute(text(sql), payload)
        return int(result.lastrowid or 0)

    def _quote_identifier(self, name: str) -> str:
        if self.db.config.engine == DatabaseEngine.POSTGRESQL:
            return f'"{name}"'
        return f"`{name}`"

    def _build_in_clause(self, prefix: str, values: Iterable[int]) -> tuple[str, Dict[str, int]]:
        params: Dict[str, int] = {}
        placeholders: List[str] = []
        for index, value in enumerate(values):
            key = f"{prefix}_{index}"
            placeholders.append(f":{key}")
            params[key] = int(value)
        return ", ".join(placeholders), params

    def _fetch_user_details(self, user_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        if not user_ids:
            return {}

        table_meta = self._describe_table("users")
        selected_columns = [column for column in ["id", "username", "display_name", "email", "status", "quota", "used_quota", "request_count", "group"] if column in table_meta]
        if not selected_columns:
            return {}

        placeholders, params = self._build_in_clause("user_id", user_ids)
        quoted_columns = ", ".join(self._quote_identifier(column) for column in selected_columns)
        sql = f"SELECT {quoted_columns} FROM users WHERE id IN ({placeholders})"
        rows = self.db.execute(sql, params)
        return {int(row["id"]): {column: row.get(column) for column in selected_columns} for row in rows}

    def _fetch_token_details(self, token_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        if not token_ids:
            return {}

        table_meta = self._describe_table("tokens")
        selected_columns = [column for column in ["id", "name", "status", "expired_time", "quota", "remain_quota", "used_quota", "group"] if column in table_meta]
        if not selected_columns:
            return {}

        placeholders, params = self._build_in_clause("token_id", token_ids)
        quoted_columns = ", ".join(self._quote_identifier(column) for column in selected_columns)
        sql = f"SELECT {quoted_columns} FROM tokens WHERE id IN ({placeholders})"
        rows = self.db.execute(sql, params)
        return {int(row["id"]): {column: row.get(column) for column in selected_columns} for row in rows}

    def _mask_token_key(self, token_key: str) -> str:
        if len(token_key) <= 10:
            return token_key
        return f"{token_key[:6]}...{token_key[-4:]}"

    def _hash_password(self, raw_password: str) -> str:
        return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


_temporary_account_service: Optional[TemporaryAccountService] = None


def get_temporary_account_service() -> TemporaryAccountService:
    global _temporary_account_service
    if _temporary_account_service is None:
        _temporary_account_service = TemporaryAccountService()
    return _temporary_account_service

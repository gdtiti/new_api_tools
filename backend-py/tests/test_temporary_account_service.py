from __future__ import annotations

from dataclasses import dataclass

from app.database import DatabaseEngine
from app.local_storage import LocalStorage
from app.temporary_account_service import TemporaryAccountService


def test_local_storage_temporary_account_sidecar_crud(tmp_path):
    storage = LocalStorage(db_path=str(tmp_path / "local.db"))
    created_at = 1_700_000_000

    row_id = storage.create_temporary_account(
        user_id=101,
        username="temp-user",
        default_token_id=501,
        default_token_key_masked="tmp-12...cdef",
        created_by="tester",
        remark="for qa",
        expires_at=1_700_086_400,
        created_at=created_at,
    )
    storage.add_temporary_account_event(
        temporary_account_id=row_id,
        user_id=101,
        action="create",
        operator="tester",
        detail={"remark": "for qa"},
        created_at=created_at,
    )

    stored = storage.get_temporary_account(101)
    assert stored is not None
    assert stored["status"] == "active"
    assert stored["default_token_id"] == 501

    assert storage.update_temporary_account(101, status="disabled", remark="disabled for test") is True

    page = storage.list_temporary_accounts(page=1, page_size=10)
    assert page["total"] == 1
    assert page["items"][0]["status"] == "disabled"
    assert page["items"][0]["remark"] == "disabled for test"

    events = storage.list_temporary_account_events(user_id=101, limit=10)
    assert len(events) == 1
    assert events[0]["action"] == "create"
    assert events[0]["detail"] == {"remark": "for qa"}

    assert storage.delete_temporary_account(101) is True
    assert storage.get_temporary_account(101) is None


@dataclass
class DummyConfig:
    engine: DatabaseEngine = DatabaseEngine.MYSQL
    database: str = "newapi"


class FakeTransaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeResult:
    def __init__(self, lastrowid: int) -> None:
        self.lastrowid = lastrowid


class FakeConnection:
    def __init__(self) -> None:
        self.transaction = FakeTransaction()
        self.inserted: list[tuple[str, dict[str, object]]] = []
        self._row_ids = iter((201, 301))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def begin(self) -> FakeTransaction:
        return self.transaction

    def execute(self, sql, payload):  # noqa: ANN001
        self.inserted.append((str(sql), dict(payload)))
        return FakeResult(next(self._row_ids))


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> FakeConnection:
        return self._connection


class FakeDb:
    def __init__(self, connection: FakeConnection) -> None:
        self.config = DummyConfig()
        self.engine = FakeEngine(connection)

    def execute(self, sql: str, params=None):  # noqa: ANN001
        if "SELECT id FROM users WHERE username" in sql:
            return []
        raise AssertionError(f"unexpected SQL: {sql}")


class ExplodingStorage:
    def create_temporary_account(self, **kwargs):  # noqa: ANN003, ARG002
        raise RuntimeError("sidecar failure")


class FakeKeyGenerator:
    def generate_key(self, prefix: str) -> str:  # noqa: ARG002
        return "tmp-test-key-123456"


def test_create_account_returns_explicit_failure_when_sidecar_write_fails(monkeypatch):
    connection = FakeConnection()
    service = TemporaryAccountService(
        db=FakeDb(connection),
        storage=ExplodingStorage(),
        user_management_service=object(),
    )

    monkeypatch.setattr(
        service,
        "_probe_creation_capability",
        lambda: {
            "supported": True,
            "reason": "",
            "tables": {
                "users": {
                    "meta": {
                        "username": {},
                        "password": {},
                        "display_name": {},
                        "email": {},
                        "status": {},
                        "quota": {},
                        "used_quota": {},
                        "request_count": {},
                        "group": {},
                        "created_at": {},
                    }
                },
                "tokens": {
                    "meta": {
                        "user_id": {},
                        "key": {},
                        "status": {},
                        "name": {},
                        "quota": {},
                        "remain_quota": {},
                        "used_quota": {},
                        "expired_time": {},
                        "created_at": {},
                        "group": {},
                    }
                },
            },
        },
    )
    monkeypatch.setattr("app.temporary_account_service.get_key_generator", lambda: FakeKeyGenerator())

    result = service.create_account(
        username="temp-user",
        remark="qa",
        created_by="tester",
        expires_at=1_700_086_400,
        quota=123,
        group_name="default",
    )

    assert result["success"] is False
    assert "failed to create temporary account" in result["message"]
    assert connection.transaction.rolled_back is True
    assert connection.transaction.committed is False

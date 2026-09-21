from pathlib import Path

import pytest
from fastapi import HTTPException

from app.auth import check_auth_rate_limit
from app.database import Database


def test_auth_rate_limit_blocks_after_configured_attempts(tmp_path: Path):
    database = Database(tmp_path / "rate-limit.db")
    database.migrate()

    check_auth_rate_limit(database, "203.0.113.10\0user@example.com", "login:identity", limit=2)
    check_auth_rate_limit(database, "203.0.113.10\0user@example.com", "login:identity", limit=2)

    with pytest.raises(HTTPException) as exc_info:
        check_auth_rate_limit(database, "203.0.113.10\0user@example.com", "login:identity", limit=2)

    assert exc_info.value.status_code == 429


def test_auth_rate_limit_keeps_accounts_on_shared_ip_independent(tmp_path: Path):
    database = Database(tmp_path / "shared-ip.db")
    database.migrate()

    check_auth_rate_limit(database, "203.0.113.20\0first@example.com", "register:identity", limit=1)
    check_auth_rate_limit(database, "203.0.113.20\0second@example.com", "register:identity", limit=1)

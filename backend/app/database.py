import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Small SQLite repository with explicit transactions and versioned schema."""

    def __init__(self, path: Path):
        self.path = path
        self._migration_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def migrate(self) -> None:
        with self._migration_lock, closing(self.connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON user_sessions(expires_at);

                CREATE TABLE IF NOT EXISTS auth_rate_limits (
                    client_hash TEXT NOT NULL,
                    action TEXT NOT NULL,
                    window_start INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(client_hash, action, window_start)
                );

                CREATE TABLE IF NOT EXISTS billing_customers (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    stripe_customer_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS billing_orders (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    purchase_type TEXT NOT NULL CHECK (purchase_type IN ('one_time', 'subscription')),
                    status TEXT NOT NULL CHECK (status IN ('creating', 'pending', 'paid', 'failed', 'expired', 'refunded')),
                    amount_cents INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    stripe_session_id TEXT UNIQUE,
                    stripe_session_url TEXT,
                    stripe_payment_intent_id TEXT,
                    stripe_subscription_id TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, request_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_order_per_user
                    ON billing_orders(user_id) WHERE status IN ('creating', 'pending');
                CREATE INDEX IF NOT EXISTS idx_orders_payment_intent ON billing_orders(stripe_payment_intent_id);
                CREATE INDEX IF NOT EXISTS idx_orders_subscription ON billing_orders(stripe_subscription_id);

                CREATE TABLE IF NOT EXISTS membership_grants (
                    order_id TEXT PRIMARY KEY REFERENCES billing_orders(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_grants_user ON membership_grants(user_id, ends_at);

                CREATE TABLE IF NOT EXISTS billing_subscriptions (
                    stripe_subscription_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    current_period_end TEXT,
                    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                    last_event_created INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON billing_subscriptions(user_id);

                CREATE TABLE IF NOT EXISTS billing_webhook_events (
                    stripe_event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    received_at TEXT NOT NULL,
                    processed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_usage (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    usage_date TEXT NOT NULL,
                    action TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id, usage_date, action)
                );

                CREATE TABLE IF NOT EXISTS anonymous_daily_usage (
                    client_hash TEXT NOT NULL,
                    usage_date TEXT NOT NULL,
                    action TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(client_hash, usage_date, action)
                );

                CREATE TABLE IF NOT EXISTS anonymous_action_requests (
                    client_hash TEXT NOT NULL,
                    action TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(client_hash, action, request_key)
                );

                CREATE TABLE IF NOT EXISTS action_requests (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, action, request_key)
                );

                CREATE TABLE IF NOT EXISTS support_tickets (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    subject TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, ?)",
                (utcnow_iso(),),
            )

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fetchone(self, query: str, parameters: tuple = ()) -> sqlite3.Row | None:
        with closing(self.connect()) as connection:
            return connection.execute(query, parameters).fetchone()

    def fetchall(self, query: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        with closing(self.connect()) as connection:
            return list(connection.execute(query, parameters).fetchall())

    def execute(self, query: str, parameters: tuple = ()) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(query, parameters)

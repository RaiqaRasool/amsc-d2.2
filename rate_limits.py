import math
import sqlite3
import time

from config import RATE_LIMIT_DB_PATH


EVENT_RETENTION_SECONDS = 24 * 60 * 60


class RateLimitExceeded(Exception):
    def __init__(self, retry_after):
        super().__init__(retry_after)
        self.retry_after = retry_after


def rate_limit_db():
    return sqlite3.connect(RATE_LIMIT_DB_PATH)


def init_rate_limit_db():
    with rate_limit_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS request_rate_events (
                scope_key TEXT NOT NULL,
                action TEXT NOT NULL,
                occurred_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_request_rate_events_lookup
            ON request_rate_events (scope_key, action, occurred_at)
            """
        )


def record_request(scope_key, action, limits, now=None):
    now = time.time() if now is None else now
    with rate_limit_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM request_rate_events WHERE occurred_at <= ?",
            (now - EVENT_RETENTION_SECONDS,),
        )
        for maximum_requests, window_seconds in limits:
            count, oldest = connection.execute(
                """
                SELECT COUNT(*), MIN(occurred_at)
                FROM request_rate_events
                WHERE scope_key = ? AND action = ? AND occurred_at > ?
                """,
                (scope_key, action, now - window_seconds),
            ).fetchone()
            if count >= maximum_requests:
                retry_after = max(1, math.ceil(oldest + window_seconds - now))
                raise RateLimitExceeded(retry_after)
        connection.execute(
            """
            INSERT INTO request_rate_events (scope_key, action, occurred_at)
            VALUES (?, ?, ?)
            """,
            (scope_key, action, now),
        )


init_rate_limit_db()

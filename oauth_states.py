import hashlib
import sqlite3
import time

from config import OAUTH_STATE_DB_PATH, OAUTH_STATE_TTL_SECONDS


def oauth_state_db():
    return sqlite3.connect(OAUTH_STATE_DB_PATH)


def state_digest(state):
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def init_oauth_state_db():
    with oauth_state_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_oauth_states (
                state_digest TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pending_oauth_states_created_at
            ON pending_oauth_states (created_at)
            """
        )


def store_oauth_state(state, now=None):
    now = time.time() if now is None else now
    with oauth_state_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM pending_oauth_states WHERE created_at <= ?",
            (now - OAUTH_STATE_TTL_SECONDS,),
        )
        connection.execute(
            """
            INSERT INTO pending_oauth_states (state_digest, created_at)
            VALUES (?, ?)
            """,
            (state_digest(state), now),
        )


def consume_oauth_state(state, now=None):
    now = time.time() if now is None else now
    with oauth_state_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM pending_oauth_states WHERE created_at <= ?",
            (now - OAUTH_STATE_TTL_SECONDS,),
        )
        cursor = connection.execute(
            "DELETE FROM pending_oauth_states WHERE state_digest = ?",
            (state_digest(state),),
        )
    return cursor.rowcount == 1


init_oauth_state_db()

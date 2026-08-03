import json
import sqlite3
from datetime import datetime, timezone

from config import JOBS_DB_PATH


TERMINAL_JOB_STATUSES = (
    "query_complete",
    "query_failed",
    "transfer_succeeded",
    "transfer_failed",
    "transfer_auth_failed",
)


class QueueCapacityError(Exception):
    def __init__(self, scope):
        super().__init__(scope)
        self.scope = scope


class TokenReferenceRetiredError(Exception):
    pass


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def jobs_db():
    connection = sqlite3.connect(JOBS_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_jobs_db():
    with jobs_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mya_transfer_jobs (
                job_id TEXT PRIMARY KEY,
                user_identity TEXT,
                globus_identity TEXT,
                query_type TEXT NOT NULL,
                query_params TEXT NOT NULL,
                source_collection_id TEXT,
                source_path TEXT,
                destination_collection_id TEXT,
                destination_collection_name TEXT,
                destination_path TEXT,
                transfer_label TEXT,
                transfer_requested INTEGER NOT NULL DEFAULT 0,
                required_scopes TEXT,
                token_reference TEXT,
                access_token_expires_at TEXT,
                globus_task_id TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(mya_transfer_jobs)")
        }
        if "destination_collection_name" not in columns:
            connection.execute(
                "ALTER TABLE mya_transfer_jobs "
                "ADD COLUMN destination_collection_name TEXT"
            )
        if "transfer_label" not in columns:
            connection.execute(
                "ALTER TABLE mya_transfer_jobs ADD COLUMN transfer_label TEXT"
            )
        if "transfer_requested" not in columns:
            connection.execute(
                "ALTER TABLE mya_transfer_jobs "
                "ADD COLUMN transfer_requested INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mya_transfer_jobs_globus_identity
            ON mya_transfer_jobs (globus_identity, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mya_transfer_jobs_retention
            ON mya_transfer_jobs (status, updated_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS token_cleanup_requests (
                token_reference TEXT PRIMARY KEY,
                requested_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )


def job_row(row):
    if row is None:
        return None
    job = dict(row)
    job["query_params"] = json.loads(job["query_params"])
    job["transfer_requested"] = bool(job["transfer_requested"])
    return job


def create_job(
    *,
    job_id,
    status,
    query_type,
    query_params,
    user_identity=None,
    globus_identity=None,
    source_collection_id=None,
    source_path=None,
    destination_collection_id=None,
    destination_collection_name=None,
    destination_path=None,
    transfer_label=None,
    transfer_requested=False,
    required_scopes=None,
    token_reference=None,
    access_token_expires_at=None,
    globus_task_id=None,
    error_message=None,
    max_pending_per_user=None,
    max_pending_global=None,
):
    now = utc_timestamp()
    with jobs_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if transfer_requested and token_reference:
            retired_reference = connection.execute(
                """
                SELECT 1 FROM token_cleanup_requests
                WHERE token_reference = ?
                """,
                (token_reference,),
            ).fetchone()
            if retired_reference:
                raise TokenReferenceRetiredError
        pending_statuses = ("queued", "query_running")
        if max_pending_per_user is not None:
            pending_for_user = connection.execute(
                """
                SELECT COUNT(*) FROM mya_transfer_jobs
                WHERE globus_identity = ? AND status IN (?, ?)
                """,
                (globus_identity, *pending_statuses),
            ).fetchone()[0]
            if pending_for_user >= max_pending_per_user:
                raise QueueCapacityError("user")
        if max_pending_global is not None:
            pending_global = connection.execute(
                """
                SELECT COUNT(*) FROM mya_transfer_jobs
                WHERE status IN (?, ?)
                """,
                pending_statuses,
            ).fetchone()[0]
            if pending_global >= max_pending_global:
                raise QueueCapacityError("global")
        connection.execute(
            """
            INSERT INTO mya_transfer_jobs (
                job_id,
                user_identity,
                globus_identity,
                query_type,
                query_params,
                source_collection_id,
                source_path,
                destination_collection_id,
                destination_collection_name,
                destination_path,
                transfer_label,
                transfer_requested,
                required_scopes,
                token_reference,
                access_token_expires_at,
                globus_task_id,
                status,
                error_message,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_identity,
                globus_identity,
                query_type,
                json.dumps(query_params, sort_keys=True),
                source_collection_id,
                source_path,
                destination_collection_id,
                destination_collection_name,
                destination_path,
                transfer_label,
                int(transfer_requested),
                required_scopes,
                token_reference,
                access_token_expires_at,
                globus_task_id,
                status,
                error_message,
                now,
                now,
            ),
        )
    return get_job(job_id)


def get_job(job_id):
    with jobs_db() as connection:
        row = connection.execute(
            "SELECT * FROM mya_transfer_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return job_row(row)


def get_job_for_identity(job_id, globus_identity):
    if not globus_identity:
        return None
    with jobs_db() as connection:
        row = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            WHERE job_id = ? AND globus_identity = ?
            """,
            (job_id, globus_identity),
        ).fetchone()
    return job_row(row)


def list_jobs(globus_identity, limit=20):
    if not globus_identity:
        return []
    with jobs_db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            WHERE globus_identity = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (globus_identity, limit),
        ).fetchall()
    return [job_row(row) for row in rows]


def list_refreshable_transfer_jobs():
    with jobs_db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            WHERE globus_task_id IS NOT NULL
              AND (
                status NOT IN ('transfer_succeeded', 'transfer_failed')
                OR destination_collection_name IS NULL
                OR transfer_label IS NULL
              )
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [job_row(row) for row in rows]


def list_expired_terminal_jobs(cutoff):
    placeholders = ", ".join("?" for _ in TERMINAL_JOB_STATUSES)
    with jobs_db() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM mya_transfer_jobs
            WHERE status IN ({placeholders}) AND updated_at <= ?
            ORDER BY updated_at
            """,
            (*TERMINAL_JOB_STATUSES, cutoff),
        ).fetchall()
    return [job_row(row) for row in rows]


def delete_expired_terminal_job(job_id, cutoff):
    placeholders = ", ".join("?" for _ in TERMINAL_JOB_STATUSES)
    with jobs_db() as connection:
        cursor = connection.execute(
            f"""
            DELETE FROM mya_transfer_jobs
            WHERE job_id = ? AND status IN ({placeholders}) AND updated_at <= ?
            """,
            (job_id, *TERMINAL_JOB_STATUSES, cutoff),
        )
    return cursor.rowcount == 1


def schedule_token_cleanup(token_reference):
    now = utc_timestamp()
    with jobs_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT OR IGNORE INTO token_cleanup_requests (
                token_reference, requested_at
            ) VALUES (?, ?)
            """,
            (token_reference, now),
        )


def list_pending_token_cleanups():
    with jobs_db() as connection:
        rows = connection.execute(
            """
            SELECT token_reference FROM token_cleanup_requests
            WHERE completed_at IS NULL
            ORDER BY requested_at
            """
        ).fetchall()
    return [row["token_reference"] for row in rows]


def token_reference_has_unfinished_transfers(token_reference):
    terminal_transfer_statuses = (
        "query_failed",
        "transfer_succeeded",
        "transfer_failed",
        "transfer_auth_failed",
    )
    placeholders = ", ".join("?" for _ in terminal_transfer_statuses)
    with jobs_db() as connection:
        row = connection.execute(
            f"""
            SELECT 1 FROM mya_transfer_jobs
            WHERE token_reference = ?
              AND transfer_requested = 1
              AND status NOT IN ({placeholders})
            LIMIT 1
            """,
            (token_reference, *terminal_transfer_statuses),
        ).fetchone()
    return row is not None


def complete_token_cleanup(token_reference):
    now = utc_timestamp()
    with jobs_db() as connection:
        connection.execute(
            """
            UPDATE token_cleanup_requests SET completed_at = ?
            WHERE token_reference = ? AND completed_at IS NULL
            """,
            (now, token_reference),
        )


def claim_next_job():
    now = utc_timestamp()
    with jobs_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            WHERE status = 'queued'
            ORDER BY created_at
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None

        connection.execute(
            """
            UPDATE mya_transfer_jobs
            SET status = 'query_running', updated_at = ?
            WHERE job_id = ? AND status = 'queued'
            """,
            (now, row["job_id"]),
        )
        claimed_row = connection.execute(
            "SELECT * FROM mya_transfer_jobs WHERE job_id = ?",
            (row["job_id"],),
        ).fetchone()
    return job_row(claimed_row)


def update_job(job_id, **fields):
    if not fields:
        return get_job(job_id)

    fields["updated_at"] = utc_timestamp()
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [job_id]

    with jobs_db() as connection:
        connection.execute(
            f"UPDATE mya_transfer_jobs SET {assignments} WHERE job_id = ?",
            values,
        )
    return get_job(job_id)


init_jobs_db()

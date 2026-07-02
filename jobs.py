import json
import sqlite3
from datetime import datetime

from config import JOBS_DB_PATH


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
):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with jobs_db() as connection:
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


def list_jobs(limit=20):
    with jobs_db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
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


def claim_next_job():
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
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

    fields["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [job_id]

    with jobs_db() as connection:
        connection.execute(
            f"UPDATE mya_transfer_jobs SET {assignments} WHERE job_id = ?",
            values,
        )
    return get_job(job_id)


init_jobs_db()

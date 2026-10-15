import logging
import os
import posixpath
import uuid
from datetime import datetime, timedelta, timezone

from config import JOB_RETENTION_DAYS, MYA_OUTPUT_DIR
from jobs import delete_expired_terminal_job, list_expired_terminal_jobs, export_has_other_jobs


LOGGER = logging.getLogger(__name__)


def generated_export_path(source_path):
    if not source_path:
        return None
    filename = posixpath.basename(source_path)
    stem, extension = os.path.splitext(filename)
    if extension not in (".csv", ".json") or not stem.startswith("mya-"):
        return None
    try:
        export_id = uuid.UUID(stem.removeprefix("mya-"))
    except ValueError:
        return None
    if filename != f"mya-{export_id}{extension}":
        return None
    return os.path.join(MYA_OUTPUT_DIR, filename)


def retention_cutoff(now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=JOB_RETENTION_DAYS)
    return cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")


def cleanup_expired_jobs(now=None):
    cutoff = retention_cutoff(now)
    deleted_jobs = 0
    for job in list_expired_terminal_jobs(cutoff):
        export_path = generated_export_path(job.get("source_path"))
        if export_path and not export_has_other_jobs(job):
            try:
                os.remove(export_path)
            except FileNotFoundError:
                pass
            except OSError:
                LOGGER.exception(
                    "Could not remove expired export for job %s.",
                    job["job_id"],
                )
                continue
        if delete_expired_terminal_job(job["job_id"], cutoff):
            deleted_jobs += 1
    return deleted_jobs


def delete_owned_job(job_id, identity):
    """Serialize deletion with job creation/claiming; preserve shared exports."""
    from jobs import jobs_db
    with jobs_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM mya_transfer_jobs WHERE job_id = ? AND globus_identity = ?",
            (job_id, identity),
        ).fetchone()
        if row is None:
            return False
        from jobs import TERMINAL_JOB_STATUSES
        if row['status'] not in TERMINAL_JOB_STATUSES or (
            row['status'] == 'query_complete' and row['transfer_requested']
        ):
            raise ValueError('Wait for this job and its transfer to finish before deleting it.')
        shared = connection.execute(
            "SELECT 1 FROM mya_transfer_jobs WHERE source_path = ? AND job_id != ? LIMIT 1",
            (row['source_path'], job_id),
        ).fetchone()
        path = generated_export_path(row['source_path'])
        if path and not shared:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        connection.execute("DELETE FROM mya_transfer_jobs WHERE job_id = ?", (job_id,))
    return True

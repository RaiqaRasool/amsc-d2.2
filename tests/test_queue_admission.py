import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))
TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory()
os.environ["JOBS_DB_PATH"] = str(
    Path(TEMPORARY_DIRECTORY.name) / "queue-admission.sqlite3"
)
jobs = importlib.import_module("jobs")


def create_pending_job(job_id, identity, user_limit=10, global_limit=500):
    return jobs.create_job(
        job_id=job_id,
        status="queued",
        query_type="point",
        query_params={"channel": "test", "time": "2026-01-01T00:00:00"},
        globus_identity=identity,
        max_pending_per_user=user_limit,
        max_pending_global=global_limit,
    )


class QueueAdmissionTests(unittest.TestCase):
    def setUp(self):
        with jobs.jobs_db() as connection:
            connection.execute("DELETE FROM mya_transfer_jobs")

    def test_user_limit_rejects_additional_pending_job(self):
        create_pending_job("job-1", "user-1", user_limit=1)
        with self.assertRaisesRegex(jobs.QueueCapacityError, "user"):
            create_pending_job("job-2", "user-1", user_limit=1)

    def test_global_limit_applies_across_users(self):
        create_pending_job("job-1", "user-1", global_limit=1)
        with self.assertRaisesRegex(jobs.QueueCapacityError, "global"):
            create_pending_job("job-2", "user-2", global_limit=1)

    def test_completed_job_does_not_consume_capacity(self):
        create_pending_job("job-1", "user-1", user_limit=1)
        jobs.update_job("job-1", status="query_complete")
        create_pending_job("job-2", "user-1", user_limit=1)


if __name__ == "__main__":
    unittest.main()

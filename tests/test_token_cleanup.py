import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

import jobs  # noqa: E402
import token_cleanup  # noqa: E402


class TokenCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_jobs_db_path = jobs.JOBS_DB_PATH
        cls.temporary_directory = tempfile.TemporaryDirectory()
        jobs.JOBS_DB_PATH = str(
            Path(cls.temporary_directory.name) / "token-cleanup.sqlite3"
        )
        jobs.init_jobs_db()

    @classmethod
    def tearDownClass(cls):
        jobs.JOBS_DB_PATH = cls.original_jobs_db_path
        cls.temporary_directory.cleanup()

    def setUp(self):
        with jobs.jobs_db() as connection:
            connection.execute("DELETE FROM mya_transfer_jobs")
            connection.execute("DELETE FROM token_cleanup_requests")
        self.revoked = []

    def revoke(self, token_reference):
        self.revoked.append(token_reference)

    def create_transfer_job(self, status="queued"):
        jobs.create_job(
            job_id="job-1",
            status=status,
            query_type="point",
            query_params={"channel": "test", "time": "2026-01-01T00:00:00"},
            transfer_requested=True,
            token_reference="token-1",
        )

    def test_unused_reference_is_cleaned_immediately(self):
        jobs.schedule_token_cleanup("token-1")
        cleaned = token_cleanup.cleanup_token_reference_if_ready(
            "token-1", self.revoke
        )
        self.assertTrue(cleaned)
        self.assertEqual(self.revoked, ["token-1"])
        self.assertEqual(jobs.list_pending_token_cleanups(), [])

    def test_reference_is_retained_until_transfer_is_terminal(self):
        self.create_transfer_job()
        jobs.schedule_token_cleanup("token-1")
        self.assertFalse(
            token_cleanup.cleanup_token_reference_if_ready("token-1", self.revoke)
        )
        self.assertEqual(self.revoked, [])

        jobs.update_job("job-1", status="transfer_succeeded")
        self.assertTrue(
            token_cleanup.cleanup_token_reference_if_ready("token-1", self.revoke)
        )
        self.assertEqual(self.revoked, ["token-1"])

    def test_retired_reference_cannot_create_new_transfer_job(self):
        jobs.schedule_token_cleanup("token-1")
        with self.assertRaises(jobs.TokenReferenceRetiredError):
            self.create_transfer_job()

    def test_revocation_failure_remains_pending_for_retry(self):
        jobs.schedule_token_cleanup("token-1")

        def fail_revocation(_token_reference):
            raise RuntimeError("temporary failure")

        with self.assertLogs(token_cleanup.LOGGER, level="ERROR"):
            cleaned = token_cleanup.cleanup_token_reference_if_ready(
                "token-1", fail_revocation
            )

        self.assertFalse(cleaned)
        self.assertEqual(jobs.list_pending_token_cleanups(), ["token-1"])


if __name__ == "__main__":
    unittest.main()

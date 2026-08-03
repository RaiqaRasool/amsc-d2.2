import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

import jobs  # noqa: E402
import retention  # noqa: E402


class RetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_jobs_db_path = jobs.JOBS_DB_PATH
        cls.original_output_dir = retention.MYA_OUTPUT_DIR
        cls.temporary_directory = tempfile.TemporaryDirectory()
        jobs.JOBS_DB_PATH = str(
            Path(cls.temporary_directory.name) / "retention.sqlite3"
        )
        retention.MYA_OUTPUT_DIR = cls.temporary_directory.name
        jobs.init_jobs_db()

    @classmethod
    def tearDownClass(cls):
        jobs.JOBS_DB_PATH = cls.original_jobs_db_path
        retention.MYA_OUTPUT_DIR = cls.original_output_dir
        cls.temporary_directory.cleanup()

    def setUp(self):
        with jobs.jobs_db() as connection:
            connection.execute("DELETE FROM mya_transfer_jobs")

    def create_job(self, job_id, status, source_path, updated_at):
        jobs.create_job(
            job_id=job_id,
            status=status,
            query_type="point",
            query_params={"channel": "test", "time": "2026-01-01T00:00:00"},
            source_path=source_path,
        )
        with jobs.jobs_db() as connection:
            connection.execute(
                "UPDATE mya_transfer_jobs SET updated_at = ? WHERE job_id = ?",
                (updated_at, job_id),
            )

    def test_cleanup_removes_expired_terminal_job_and_export(self):
        filename = "mya-12345678-1234-1234-1234-123456789abc.csv"
        export = Path(self.temporary_directory.name) / filename
        export.write_text("data")
        self.create_job("expired", "query_complete", f"/source/{filename}", "2026-01-01T00:00:00Z")

        deleted = retention.cleanup_expired_jobs(
            datetime(2026, 2, 15, tzinfo=timezone.utc)
        )

        self.assertEqual(deleted, 1)
        self.assertFalse(export.exists())
        self.assertIsNone(jobs.get_job("expired"))

    def test_cleanup_preserves_active_and_recent_jobs(self):
        active_filename = "mya-12345678-1234-1234-1234-123456789abc.json"
        recent_filename = "mya-12345678-1234-1234-1234-123456789abd.json"
        active_export = Path(self.temporary_directory.name) / active_filename
        recent_export = Path(self.temporary_directory.name) / recent_filename
        active_export.write_text("active")
        recent_export.write_text("recent")
        self.create_job("active", "query_running", f"/source/{active_filename}", "2026-01-01T00:00:00Z")
        self.create_job("recent", "query_complete", f"/source/{recent_filename}", "2026-02-01T00:00:00Z")

        deleted = retention.cleanup_expired_jobs(
            datetime(2026, 2, 15, tzinfo=timezone.utc)
        )

        self.assertEqual(deleted, 0)
        self.assertTrue(active_export.exists())
        self.assertTrue(recent_export.exists())
        self.assertIsNotNone(jobs.get_job("active"))
        self.assertIsNotNone(jobs.get_job("recent"))

    def test_cleanup_never_deletes_unrecognized_filename(self):
        unrelated_file = Path(self.temporary_directory.name) / "important.csv"
        unrelated_file.write_text("keep")
        self.create_job("invalid-path", "query_complete", "/source/important.csv", "2026-01-01T00:00:00Z")

        retention.cleanup_expired_jobs(
            datetime(2026, 2, 15, tzinfo=timezone.utc)
        )

        self.assertTrue(unrelated_file.exists())
        self.assertIsNone(jobs.get_job("invalid-path"))


if __name__ == "__main__":
    unittest.main()

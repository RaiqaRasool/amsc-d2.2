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
os.environ.setdefault(
    "RATE_LIMIT_DB_PATH",
    str(Path(TEMPORARY_DIRECTORY.name) / "rate-limits.sqlite3"),
)
rate_limits = importlib.import_module("rate_limits")
rate_limits.RATE_LIMIT_DB_PATH = str(
    Path(TEMPORARY_DIRECTORY.name) / "rate-limits.sqlite3"
)
rate_limits.init_rate_limit_db()


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        with rate_limits.rate_limit_db() as connection:
            connection.execute("DELETE FROM request_rate_events")

    def test_request_is_rejected_at_limit_with_retry_time(self):
        limits = ((2, 60),)
        rate_limits.record_request("user-1", "query", limits, now=1_000)
        rate_limits.record_request("user-1", "query", limits, now=1_001)

        with self.assertRaises(rate_limits.RateLimitExceeded) as raised:
            rate_limits.record_request("user-1", "query", limits, now=1_002)

        self.assertEqual(raised.exception.retry_after, 58)

    def test_window_reopens_after_oldest_request_expires(self):
        limits = ((1, 60),)
        rate_limits.record_request("user-1", "query", limits, now=1_000)
        rate_limits.record_request("user-1", "query", limits, now=1_060)

    def test_identities_and_actions_have_separate_limits(self):
        limits = ((1, 60),)
        rate_limits.record_request("user-1", "query", limits, now=1_000)
        rate_limits.record_request("user-2", "query", limits, now=1_001)
        rate_limits.record_request("user-1", "browse", limits, now=1_001)

    def test_hourly_limit_applies_after_minute_window_reopens(self):
        limits = ((2, 60), (3, 3_600))
        rate_limits.record_request("user-1", "query", limits, now=1_000)
        rate_limits.record_request("user-1", "query", limits, now=1_001)
        rate_limits.record_request("user-1", "query", limits, now=1_061)
        with self.assertRaises(rate_limits.RateLimitExceeded):
            rate_limits.record_request("user-1", "query", limits, now=1_062)


if __name__ == "__main__":
    unittest.main()

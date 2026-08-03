import io
import sys
import time
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker_limits import (  # noqa: E402
    LimitedTextWriter,
    OutputLimitExceeded,
    run_with_timeout,
)


def return_value():
    return 42


def wait_too_long():
    time.sleep(1)


class WorkerLimitTests(unittest.TestCase):
    def test_writer_rejects_bytes_beyond_limit(self):
        output = LimitedTextWriter(io.StringIO(), 4)
        output.write("test")
        with self.assertRaises(OutputLimitExceeded):
            output.write("!")

    def test_process_returns_successful_result(self):
        self.assertEqual(run_with_timeout(return_value, (), 1), ("complete", 42))

    def test_process_is_terminated_at_timeout(self):
        result, value = run_with_timeout(wait_too_long, (), 0.01)
        self.assertEqual(result, "timeout")
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()

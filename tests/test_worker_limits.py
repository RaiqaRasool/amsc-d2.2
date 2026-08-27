import io
import sys
import time
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker_limits import (  # noqa: E402
    LimitedTextWriter,
    MAX_ERROR_MESSAGE_LENGTH,
    OutputLimitExceeded,
    bounded_error_message,
    run_with_timeout,
)


def return_value():
    return 42


def wait_too_long():
    time.sleep(1)


def fail_with_reason():
    raise RuntimeError("MYA backend\nrejected the query")


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

    def test_process_returns_bounded_single_line_failure_reason(self):
        result, value = run_with_timeout(fail_with_reason, (), 1)
        self.assertEqual(result, "failed")
        self.assertEqual(value, "MYA backend rejected the query")

    def test_failure_reason_is_limited(self):
        message = bounded_error_message(RuntimeError("x" * 600))
        self.assertEqual(len(message), MAX_ERROR_MESSAGE_LENGTH)


if __name__ == "__main__":
    unittest.main()

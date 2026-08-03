import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from query_validation import (  # noqa: E402
    MAX_BINS,
    MAX_PVS,
    MAX_QUERY_WINDOW,
    MAX_SAMPLES,
    validate_query_params,
)


class QueryValidationTests(unittest.TestCase):
    def test_limits_accept_boundary_values(self):
        validate_query_params(
            "mysampler",
            {"pvlist": ["pv"] * MAX_PVS, "num_samples": MAX_SAMPLES},
        )
        start = datetime(2026, 1, 1)
        validate_query_params(
            "mystats",
            {
                "pvlist": ["pv"],
                "num_bins": MAX_BINS,
                "start": start.isoformat(),
                "end": (start + MAX_QUERY_WINDOW).isoformat(),
            },
        )

    def test_limits_reject_oversized_queries_with_safe_messages(self):
        cases = (
            (
                "mysampler",
                {"pvlist": ["pv"], "num_samples": MAX_SAMPLES + 1},
                "no more than 100,000 samples",
            ),
            (
                "mysampler",
                {"pvlist": ["pv"] * (MAX_PVS + 1), "num_samples": 1},
                "no more than 100 PVs",
            ),
            ("point", {"channel": "x" * 257}, "256 characters or fewer"),
            ("channel", {"pattern": "x" * 257}, "256 characters or fewer"),
        )
        for query_type, params, message in cases:
            with self.subTest(query_type=query_type):
                with self.assertRaisesRegex(ValueError, message):
                    validate_query_params(query_type, params)

    def test_limits_reject_long_time_window(self):
        start = datetime(2026, 1, 1)
        with self.assertRaisesRegex(ValueError, "31 days or fewer"):
            validate_query_params(
                "interval",
                {
                    "begin": start.isoformat(),
                    "end": (start + MAX_QUERY_WINDOW + timedelta(seconds=1)).isoformat(),
                },
            )


if __name__ == "__main__":
    unittest.main()

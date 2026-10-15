import tempfile
import unittest
from pathlib import Path

from demo_csv_import import (
    extend_channel_mapping, load_channel_mapping, save_channel_mapping, to_mya_timestamp,
)


class DemoCsvFormatTests(unittest.TestCase):
    def test_known_archive_timestamp(self):
        # Exporting binary fractions as nanoseconds truncates precision. Re-encoding
        # this known table_100 event is one MYA tick below the stored timestamp.
        self.assertEqual(
            409247436633184470,
            to_mya_timestamp("2018-04-24 06:25:05.360009040"),
        )

    def test_zone_and_fraction_conversion(self):
        self.assertEqual(0, to_mya_timestamp("1970-01-01T00:00:00Z"))
        self.assertEqual(1 << 27, to_mya_timestamp("1970-01-01T00:00:00.5Z"))
        self.assertEqual(
            to_mya_timestamp("2024-05-09T12:53:00Z"),
            to_mya_timestamp("2024-05-09 08:53:00"),
        )
        self.assertEqual(
            to_mya_timestamp("2024-01-09T13:53:00Z"),
            to_mya_timestamp("2024-01-09 08:53:00"),
        )

    def test_invalid_or_unresolved_times(self):
        for value in ("2024-11-03 01:30:00", "2024-03-10 02:30:00",
                      "bad", "2024-05-09", "1969-01-01T00:00:00Z",
                      "2024-05-09 00:00:00.1234567890"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                to_mya_timestamp(value)
        # Explicit offsets resolve the repeated fall-back hour.
        self.assertNotEqual(to_mya_timestamp("2024-11-03T01:30:00-04:00"),
                            to_mya_timestamp("2024-11-03T01:30:00-05:00"))

    def test_stable_mapping_and_json_reuse(self):
        first = extend_channel_mapping(["R222GMES", "R221GMES"])
        self.assertEqual({"R221GMES": 1000, "R222GMES": 1001}, first)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "channels.json"
            save_channel_mapping(path, first)
            restored = load_channel_mapping(path)
            with self.assertRaises(FileExistsError):
                save_channel_mapping(path, first)
        extended = extend_channel_mapping(["NEW", "R221GMES"], restored)
        self.assertEqual(first["R221GMES"], extended["R221GMES"])
        self.assertEqual(first["R222GMES"], extended["R222GMES"])
        self.assertEqual(1002, extended["NEW"])
        self.assertEqual(first, extend_channel_mapping(list(reversed(first))))

    def test_invalid_mappings(self):
        for mapping in ({"a": 100}, {"a": True}, {"a": 1000, "b": 1000},
                        {"": 1000}, {"a": "1000"}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                extend_channel_mapping([], mapping)
        with self.assertRaises(ValueError):
            extend_channel_mapping(["pv", "pv"])


if __name__ == "__main__":
    unittest.main()

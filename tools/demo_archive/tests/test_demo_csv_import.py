import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.demo_archive.demo_csv_import import (
    channel_sql_filename, convert_csv, extend_channel_mapping, load_channel_mapping, save_channel_mapping, to_mya_timestamp,
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


class DemoCsvConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / "samples.csv"
        self.output = self.directory / "sql"

    def write_csv(self, rows, header=("Date", "pvA", "pvB")):
        with self.source.open("w", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(header)
            writer.writerows(rows)

    def test_independent_changes_and_return_to_previous_value(self):
        self.write_csv([
            ["2024-05-09 08:53:00", "0", "5"],
            ["2024-05-09 08:53:01", "0.000", "6"],
            ["2024-05-09 08:53:02", "1", "6"],
            ["2024-05-09 08:53:03", "0", "6"],
        ])
        self.assertEqual({"pvA": 3, "pvB": 2}, convert_csv(self.source, self.output))
        sql = (self.output / "1000_pvA.sql").read_text()
        self.assertIn("CREATE TABLE `table_1000`", sql)
        self.assertIn("`val1` FLOAT", sql)
        self.assertIn(f"VALUES ({to_mya_timestamp('2024-05-09 08:53:02')}, 0, 1)", sql)
        self.assertNotIn(str(to_mya_timestamp("2024-05-09 08:53:01")), sql)
        self.assertEqual(3, sql.count("INSERT INTO `table_1000`"))
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(4, summary["rows"])
        self.assertEqual({"pvA": 3, "pvB": 2}, summary["events_per_pv"])

    def test_reuse_mapping_and_keep_first_value_after_gap(self):
        self.write_csv([["2024-05-09 08:53:00", "1", "2"]])
        convert_csv(self.source, self.output)
        mapping = self.output / "channels.json"
        later = self.directory / "later"
        self.write_csv([["2024-05-19 08:53:00", "2", "1"]], ("Date", "pvB", "pvA"))
        self.assertEqual({"pvB": 1, "pvA": 1}, convert_csv(self.source, later, mapping))
        self.assertEqual(load_channel_mapping(mapping), load_channel_mapping(later / "channels.json"))
        sql = (later / "1000_pvA.sql").read_text()
        self.assertEqual(1, sql.count("INSERT INTO `table_1000`"))
        self.assertIn(f"VALUES ({to_mya_timestamp('2024-05-19 08:53:00')}, 0, 1)", sql)
        self.assertNotIn("unavailable", sql)

    def test_identical_duplicate_timestamp_is_skipped(self):
        self.write_csv([["2024-05-09 08:53:00", "1", "2"],
                        ["2024-05-09 08:53:00", "1.0", "2.0"]])
        self.assertEqual({"pvA": 1, "pvB": 1}, convert_csv(self.source, self.output))

    def test_failure_does_not_publish_partial_output(self):
        bad_rows = [
            ["2024-05-09 08:53:01", "", "2"],
            ["2024-05-09 08:53:01", "NaN", "2"],
            ["2024-05-09 08:53:01", "Infinity", "2"],
            ["2024-05-09 08:53:01", "1e100", "2"],
            ["2024-05-09 08:53:01", "1e-100", "2"],
            ["2024-05-09 08:53:00", "3", "2"],
            ["2024-05-09 08:52:59", "1", "2"],
            ["bad", "1", "2"],
            ["2024-05-09 08:53:01", "1"],
        ]
        for row in bad_rows:
            with self.subTest(row=row):
                self.write_csv([["2024-05-09 08:53:00", "1", "2"], row])
                with self.assertRaisesRegex(ValueError, "row 3"):
                    convert_csv(self.source, self.output)
                self.assertFalse(self.output.exists())
                self.assertEqual([], list(self.directory.glob(".demo-csv-*")))

    def test_headers_empty_input_and_existing_output(self):
        for header in (("Time", "pv"), ("Date", "pv", "pv"), ("Date", "channel100")):
            with self.subTest(header=header):
                self.write_csv([], header)
                with self.assertRaises(ValueError):
                    convert_csv(self.source, self.output)
        self.write_csv([])
        with self.assertRaisesRegex(ValueError, "no measurement rows"):
            convert_csv(self.source, self.output)
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            convert_csv(self.source, self.output)

    def test_pv_name_is_safely_encoded_in_filename_and_sql(self):
        name = "../pv'; DROP TABLE channels; --"
        self.write_csv([["2024-05-09 08:53:00", "1"]], ("Date", name))
        convert_csv(self.source, self.output)
        sql = (self.output / channel_sql_filename(name, 1000)).read_text()
        filename = channel_sql_filename(name, 1000)
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)
        self.assertIn("%2F", filename)
        self.assertLessEqual(len(channel_sql_filename("é" * 255, 1000)), 255)
        self.assertEqual("1002_INX2L07_gDsRt.sql", channel_sql_filename("INX2L07_gDsRt", 1002))
        self.assertIn(name.encode().hex(), sql)
        self.assertNotIn("DROP TABLE", sql)
        self.assertEqual({name: 1000}, load_channel_mapping(self.output / "channels.json"))


if __name__ == "__main__":
    unittest.main()

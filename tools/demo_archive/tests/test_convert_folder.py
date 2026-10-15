import json
import tempfile
import unittest
from pathlib import Path

from tools.demo_archive.demo_csv_import import convert_folder, load_channel_mapping
from tools.demo_archive.import_sql import validate_bundle, validated_events


class DemoFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv_dir = self.root / 'csv'
        self.csv_dir.mkdir()
        self.output = self.root / 'sql'

    def test_shared_channels_merge_by_time_and_keep_file_boundaries(self):
        # Filename order deliberately differs from time order.
        (self.csv_dir / 'a.csv').write_text('Date,pvB,pvA\n2024-05-19 10:00:00,9,5\n2024-05-19 10:00:01,9,6\n')
        (self.csv_dir / 'z.csv').write_text('Date,pvA\n2024-05-09 10:00:00,5\n2024-05-09 10:00:01,5\n')
        (self.csv_dir / 'ignored.txt').write_text('not CSV')
        self.assertEqual({'pvA': 3, 'pvB': 1}, convert_folder(self.csv_dir, self.output))
        mapping = load_channel_mapping(self.output / 'channels.json')
        channels = validate_bundle(self.output)
        self.assertEqual(2, len(channels))
        events = list(validated_events(self.output / f"{mapping['pvA']}_pvA.sql", 'pvA', mapping['pvA']))
        self.assertEqual([5, 5, 6], [value for _, value in events])
        self.assertEqual(sorted(time for time, _ in events), [time for time, _ in events])
        summary = json.loads((self.output / 'summary.json').read_text())
        self.assertEqual(['z.csv', 'a.csv'], [run['source'] for run in summary['sources']])
        self.assertEqual(4, summary['rows'])
        self.assertEqual(1, (self.output / f"{mapping['pvA']}_pvA.sql").read_text().count('CREATE TABLE'))

    def test_overlap_and_bad_later_file_publish_nothing(self):
        (self.csv_dir / 'a.csv').write_text('Date,pv\n2024-05-09 10:00:00,1\n2024-05-09 10:00:02,2\n')
        later = self.csv_dir / 'b.csv'
        later.write_text('Date,pv\n2024-05-09 10:00:01,1\n')
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            convert_folder(self.csv_dir, self.output)
        self.assertFalse(self.output.exists())
        later.write_text('Date,pv\n2024-05-19 10:00:00,NaN\n')
        with self.assertRaises(ValueError):
            convert_folder(self.csv_dir, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual([], list(self.root.glob('.demo-folder-*')))

    def test_reuses_explicit_mapping(self):
        mapping = self.root / 'mapping.json'
        mapping.write_text('{"pv": 1234, "older": 1233}')
        (self.csv_dir / 'data.CSV').write_text('Date,pv\n2024-05-09 10:00:00,1\n')
        convert_folder(self.csv_dir, self.output, mapping)
        self.assertEqual({'pv': 1234, 'older': 1233}, load_channel_mapping(self.output / 'channels.json'))
        self.assertTrue((self.output / '1234_pv.sql').exists())

    def test_empty_folder_and_existing_output(self):
        with self.assertRaisesRegex(ValueError, 'no CSV'):
            convert_folder(self.csv_dir, self.output)
        (self.csv_dir / 'data.csv').write_text('Date,pv\n2024-05-09 10:00:00,1\n')
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            convert_folder(self.csv_dir, self.output)

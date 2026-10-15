import csv
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.demo_archive.refresh_catalog import refresh_catalog
from tools.demo_archive import import_sql


class DemoCatalogTests(unittest.TestCase):
    @patch('tools.demo_archive.refresh_catalog._query')
    def test_inventory_and_dates_come_from_database(self, query):
        query.side_effect = [
            [['100', '6368616e6e656c313030', '6', '1'], ['1002', '494e58324c30375f6744735274', '1', '11']],
            [['100', '0', str(1 << 27), '2'], ['1002', 'NULL', 'NULL', '0']],
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'demo-catalog.csv'
            self.assertEqual(2, refresh_catalog(['mysql'], output))
            with output.open(newline='') as source:
                rows = list(csv.DictReader(source))
            self.assertEqual('INX2L07_gDsRt', rows[0]['pv_name'])
            self.assertEqual('', rows[0]['first_stored_event'])
            self.assertEqual('0', rows[0]['stored_events'])
            self.assertEqual('DBR_SHORT', rows[0]['datatype'])
            self.assertEqual('array (11 elements)', rows[0]['value_shape'])
            self.assertEqual('DBR_DOUBLE', rows[1]['datatype'])
            self.assertEqual('scalar', rows[1]['value_shape'])
            self.assertNotIn('refreshed_at', rows[0])
            self.assertNotIn('datatype_code', rows[0])
            self.assertNotIn('element_count', rows[0])
            self.assertEqual('1969-12-31T19:00:00.000000-05:00', rows[1]['first_stored_event'])
            self.assertEqual('1969-12-31T19:00:00.500000-05:00', rows[1]['last_stored_event'])
            self.assertEqual(0o644, output.stat().st_mode & 0o777)
            self.assertIn('`table_1002`', query.call_args.args[1])

    @patch('tools.demo_archive.refresh_catalog._query')
    def test_failure_preserves_previous_catalog(self, query):
        query.side_effect = [[['100', '7076', '6', '1']], RuntimeError('missing table')]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'demo-catalog.csv'
            output.write_text('previous catalog')
            with self.assertRaisesRegex(RuntimeError, 'missing table'):
                refresh_catalog(['mysql'], output)
            self.assertEqual('previous catalog', output.read_text())
            self.assertEqual([output], list(Path(directory).iterdir()))

    @patch('tools.demo_archive.refresh_catalog._query', return_value=[])
    def test_empty_database_publishes_header_only(self, query):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'demo-catalog.csv'
            self.assertEqual(0, refresh_catalog(['mysql'], output))
            self.assertEqual(1, len(output.read_text().splitlines()))
            self.assertEqual(1, query.call_count)

    @patch('tools.demo_archive.import_sql.refresh_catalog', return_value=226)
    @patch('tools.demo_archive.import_sql.import_bundle')
    def test_cli_refreshes_after_successful_import(self, importer, refresh):
        with patch('sys.argv', ['import_sql.py', 'bundle', '--catalog', 'catalog.csv']):
            import_sql.main()
        importer.assert_called_once()
        refresh.assert_called_once_with(importer.call_args.args[1], 'catalog.csv')

    @patch('tools.demo_archive.import_sql.refresh_catalog', side_effect=RuntimeError('offline'))
    @patch('tools.demo_archive.import_sql.import_bundle')
    def test_cli_reports_refresh_failure_after_import(self, importer, refresh):
        with patch('sys.argv', ['import_sql.py', 'bundle']), self.assertRaises(SystemExit) as error:
            import_sql.main()
        self.assertEqual(1, error.exception.code)
        importer.assert_called_once()

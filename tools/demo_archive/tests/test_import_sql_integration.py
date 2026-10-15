"""Opt-in checks against a disposable pinned mycontainer; never a Compose service."""
import os
import csv as csv_module
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.demo_archive.csv_to_sql import convert_csv
from tools.demo_archive.import_sql import import_bundle
from tools.demo_archive.refresh_catalog import refresh_catalog


@unittest.skipUnless(os.environ.get('DEMO_IMPORT_TEST_CONTAINER', '').startswith('mya-import-test-'),
                     'requires an explicitly named disposable mya-import-test-* container')
class DemoSqlDatabaseTests(unittest.TestCase):
    def test_initial_repeat_append_and_conflict_guards(self):
        command = ['docker', 'exec', '-i', os.environ['DEMO_IMPORT_TEST_CONTAINER'], 'sh', '-c',
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --batch --skip-column-names -u root archive']

        def query(sql):
            result = subprocess.run(command, input=sql, capture_output=True, text=True, check=True)
            return result.stdout.strip()

        self.assertEqual('0', query('SELECT COUNT(*) FROM channels WHERE chan_id IN (100,1000,1001);'))
        fixture = Path(__file__).resolve().parents[3] / 'docker/demo-archive/mya/100_channel.sql'
        self.addCleanup(query, 'DROP TABLE IF EXISTS table_100; DELETE FROM channels WHERE chan_id=100;')
        query(fixture.read_text())
        self.addCleanup(query, 'DROP TABLE IF EXISTS table_1000,table_1001; DELETE FROM channels WHERE chan_id IN (1000,1001);')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv = root / 'sample.csv'
            csv.write_text('Date,import_test_pv\n2024-05-09 08:53:00,5.911\n')
            first = root / 'first'
            convert_csv(csv, first)
            import_bundle(first, command)
            import_bundle(first, command)
            self.assertEqual('1', query('SELECT COUNT(*) FROM table_1000;'))
            csv.write_text('Date,import_test_pv\n2024-05-09 08:53:01,8\n')
            later = root / 'later'
            convert_csv(csv, later, first / 'channels.json')
            import_bundle(later, command)
            self.assertEqual('2', query('SELECT COUNT(*) FROM table_1000;'))
            catalog_path = root / 'demo-catalog.csv'
            refresh_catalog(command, catalog_path)
            with catalog_path.open(newline='') as source:
                catalog = {row['pv_name']: row for row in csv_module.DictReader(source)}
            self.assertIn('channel100', catalog)
            self.assertEqual(query('SELECT COUNT(*) FROM table_100;'), catalog['channel100']['stored_events'])
            self.assertEqual('2', catalog['import_test_pv']['stored_events'])
            self.assertEqual('2024-05-09T08:53:00.000000-04:00', catalog['import_test_pv']['first_stored_event'])
            self.assertEqual('2024-05-09T08:53:01.000000-04:00', catalog['import_test_pv']['last_stored_event'])
            csv.write_text('Date,import_test_pv\n2024-05-09 08:53:00,9\n')
            conflict = root / 'conflict'
            convert_csv(csv, conflict, first / 'channels.json')
            with self.assertRaisesRegex(RuntimeError, 'events_ok'):
                import_bundle(conflict, command)
            self.assertEqual('2', query('SELECT COUNT(*) FROM table_1000;'))
            self.assertEqual('8', query('SELECT val1 FROM table_1000 ORDER BY time DESC LIMIT 1;'))
            query("UPDATE channels SET host='different' WHERE chan_id=1000;")
            with self.assertRaisesRegex(RuntimeError, 'identity_ok'):
                import_bundle(first, command)
            query("UPDATE channels SET host='mya' WHERE chan_id=1000;")
            query('ALTER TABLE table_1000 ADD extra INT;')
            with self.assertRaisesRegex(RuntimeError, 'structure_ok'):
                import_bundle(first, command)
            query('ALTER TABLE table_1000 DROP extra;')
            csv.write_text('Date,other_pv\n2024-05-09 08:53:00,1\n')
            collision = root / 'collision'
            convert_csv(csv, collision)
            with self.assertRaisesRegex(RuntimeError, 'identity_ok'):
                import_bundle(collision, command)
            self.assertEqual('0', query("SELECT COUNT(*) FROM channels WHERE name='other_pv';"))
            csv.write_text('Date,café\n2024-05-09 08:53:00,1\n', encoding='utf-8')
            unicode_bundle = root / 'unicode'
            convert_csv(csv, unicode_bundle, first / 'channels.json')
            import_bundle(unicode_bundle, command)
            import_bundle(unicode_bundle, command)
            self.assertEqual('1', query('SELECT COUNT(*) FROM table_1001;'))

"""Opt-in checks against a disposable pinned mycontainer; never a Compose service."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.demo_archive.demo_csv_import import convert_csv
from tools.demo_archive.import_sql import import_bundle


@unittest.skipUnless(os.environ.get('DEMO_IMPORT_TEST_CONTAINER', '').startswith('mya-import-test-'),
                     'requires an explicitly named disposable mya-import-test-* container')
class DemoSqlDatabaseTests(unittest.TestCase):
    def test_initial_repeat_append_and_conflict_guards(self):
        command = ['docker', 'exec', '-i', os.environ['DEMO_IMPORT_TEST_CONTAINER'], 'sh', '-c',
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --batch --skip-column-names -u root archive']

        def query(sql):
            result = subprocess.run(command, input=sql, capture_output=True, text=True, check=True)
            return result.stdout.strip()

        self.assertEqual('0', query('SELECT COUNT(*) FROM channels WHERE chan_id IN (1000,1001);'))
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

import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.demo_archive.demo_csv_import import convert_csv
from tools.demo_archive.import_sql import (
    import_bundle, mysql_command, validate_bundle, write_import_sql,
)


class DemoSqlImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        source = root / 'sample.csv'
        source.write_text('Date,pv\n2024-05-09 08:53:00,1\n2024-05-09 08:53:01,2\n')
        self.bundle = root / 'sql'
        convert_csv(source, self.bundle)

    def test_sql_stages_float_and_checks_before_inserting_events(self):
        name, channel_id, path = validate_bundle(self.bundle)[0]
        sql = io.StringIO()
        write_import_sql(sql, name, channel_id, path)
        script = sql.getvalue()
        self.assertIn('CREATE TEMPORARY TABLE incoming', script)
        self.assertIn("IF(GET_LOCK('demo_archive_import', 0)=1,1,NULL)", script)
        self.assertIn('BINARY CONVERT(name USING utf8mb4)=BINARY', script)
        self.assertIn("ENGINE='InnoDB'", script)
        self.assertIn('WHERE t.code<>i.code OR t.val1<>i.val1', script)
        self.assertLess(script.index('import_checks(events_ok)'), script.index('INSERT INTO `table_1000`'))
        self.assertIn('WHERE t.time IS NULL', script)
        self.assertNotIn('REPLACE INTO', script)

    @patch('tools.demo_archive.import_sql.subprocess.run')
    def test_rejects_tampered_sql_before_database_access(self, run):
        with (self.bundle / '1000_pv.sql').open('a') as output:
            output.write('DROP TABLE channels;\n')
        with self.assertRaisesRegex(ValueError, 'invalid event statement'):
            import_bundle(self.bundle, ['mysql'])
        run.assert_not_called()

    def test_rejects_bad_summary_and_extra_sql(self):
        summary = self.bundle / 'summary.json'
        data = json.loads(summary.read_text())
        data['events_per_pv']['pv'] += 1
        summary.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'count differs'):
            validate_bundle(self.bundle)
        data['events_per_pv']['pv'] -= 1
        summary.write_text(json.dumps(data))
        (self.bundle / 'other.sql').write_text('')
        with self.assertRaisesRegex(ValueError, 'SQL files do not match'):
            validate_bundle(self.bundle)

    @patch('tools.demo_archive.import_sql.subprocess.run')
    def test_success_and_failure_reporting(self, run):
        version = subprocess.CompletedProcess([], 0, '10.5.23-MariaDB\n', '')
        run.side_effect = [version, subprocess.CompletedProcess([], 0, '2\t0\n', '')]
        self.assertEqual(['pv'], import_bundle(self.bundle, ['mysql']))
        run.side_effect = [version, subprocess.CompletedProcess([], 1, '', 'events_ok failed')]
        with self.assertRaisesRegex(RuntimeError, "completed channels: \\[\\].*events_ok failed"):
            import_bundle(self.bundle, ['mysql'])

    @patch('tools.demo_archive.import_sql.subprocess.run')
    def test_old_database_is_rejected(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '5.1.42\n', '')
        with self.assertRaisesRegex(RuntimeError, 'unsupported'):
            import_bundle(self.bundle, ['mysql'])
        self.assertEqual(1, run.call_count)

    def test_legacy_filenames_still_import(self):
        (self.bundle / '1000_pv.sql').rename(self.bundle / '1000_channel.sql')
        self.assertEqual('1000_channel.sql', validate_bundle(self.bundle)[0][2].name)

    def test_compose_command_uses_container_credentials(self):
        command = mysql_command('podman', 'docker-compose.production.yml')
        self.assertEqual(['podman', 'compose', '-f', 'docker-compose.production.yml'], command[:4])
        self.assertIn('MYSQL_ROOT_PASSWORD', command[-1])
        self.assertIn('-T', command)


if __name__ == '__main__':
    unittest.main()

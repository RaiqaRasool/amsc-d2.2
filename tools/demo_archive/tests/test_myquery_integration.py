"""Opt-in query checks using only five source rows and two approved PV columns."""
import csv
import json
import os
import struct
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from itertools import islice
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from tools.demo_archive.csv_to_sql import convert_csv
from tools.demo_archive.import_sql import import_bundle

DB = os.environ.get('DEMO_QUERY_TEST_DB', '')
QUERY = os.environ.get('DEMO_QUERY_TEST_CONTAINER', '')


@unittest.skipUnless(DB.startswith('mya-import-test-') and QUERY.startswith('mya-import-test-'),
                     'requires disposable mya-import-test-* database and MyQuery containers')
class DemoMyQueryTests(unittest.TestCase):
    def test_approved_subset_through_all_query_types(self):
        project = Path(__file__).resolve().parents[3]
        source_path = project.parent / 'cebaf_linac_fe_2024' / 'data-2024-05-14.csv'
        with source_path.open(newline='') as source:
            reader = csv.reader(source)
            header = next(reader)[:3]
            rows = [row[:3] for row in islice(reader, 5)]
        self.assertEqual(5, len(rows))
        names = header[1:]
        dates = [datetime.fromisoformat(row[0]).replace(tzinfo=ZoneInfo('America/New_York'))
                 for row in rows]
        for previous, current in zip(dates, dates[1:]):
            self.assertEqual(timedelta(seconds=1), current - previous)
        epoch_ms = [int(date.timestamp()) * 1000 for date in dates]
        values = {name: [struct.unpack('!f', struct.pack('!f', float(row[index + 1])))[0]
                         for row in rows] for index, name in enumerate(names)}
        command = ['docker', 'exec', '-i', DB, 'sh', '-c',
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --batch --skip-column-names -u root archive']

        def sql(text):
            return subprocess.run(command, input=text, text=True, capture_output=True,
                                  check=True).stdout.strip()

        def query(endpoint, **params):
            params.update(m='docker', u='on')
            result = subprocess.run(['docker', 'exec', QUERY, 'curl', '--max-time', '15', '-fsS',
                                     'http://localhost:8080/myquery/' + endpoint + '?' + urlencode(params)],
                                    capture_output=True, text=True, check=True)
            return json.loads(result.stdout)

        self.assertEqual('0', sql('SELECT COUNT(*) FROM channels WHERE chan_id IN (1000,1001);'))
        self.addCleanup(sql, 'DROP TABLE IF EXISTS table_1000,table_1001; DELETE FROM channels WHERE chan_id IN (1000,1001);')
        self.assertEqual('0', sql('SELECT COUNT(*) FROM channels WHERE chan_id IN (100,101,102);'))
        self.addCleanup(sql, 'DROP TABLE IF EXISTS table_100,table_101,table_102; DELETE FROM channels WHERE chan_id IN (100,101,102);')
        # Install the existing project fixtures too, proving imports preserve them.
        for channel_id in (100, 101, 102):
            sql((project / 'docker' / 'demo-archive' / 'mya' / f'{channel_id}_channel.sql').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subset = root / 'subset.csv'
            with subset.open('w', newline='') as output:
                writer = csv.writer(output)
                writer.writerow(header)
                writer.writerows(rows)
            bundle = root / 'sql'
            counts = convert_csv(subset, bundle)
            import_bundle(bundle, command)
            import_bundle(bundle, command)
            for name in names:
                metadata = query('channel', q=name)[0]
                self.assertEqual(name, metadata['name'])
                self.assertEqual('DBR_DOUBLE', metadata['datatype'])
                self.assertEqual(1, metadata['datasize'])
                self.assertEqual('mya', metadata['datahost'])

                events = query('interval', c=name, b=dates[0].strftime('%Y-%m-%dT%H:%M:%S'),
                               e=(dates[-1] + timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S'), l='')['data']
                change_indexes = [index for index in range(5)
                                  if index == 0 or values[name][index] != values[name][index-1]]
                self.assertEqual(counts[name], len(events))
                self.assertEqual([epoch_ms[index] for index in change_indexes], [event['d'] for event in events])
                for event, index in zip(events, change_indexes):
                    self.assertAlmostEqual(values[name][index], event['v'], places=6)

                point = query('point', c=name, t=(dates[-1] + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S'))
                self.assertEqual(epoch_ms[change_indexes[-1]], point['data']['d'])
                self.assertAlmostEqual(values[name][-1], point['data']['v'], places=6)

            sampled = query('mysampler', c=','.join(names), b=dates[0].strftime('%Y-%m-%dT%H:%M:%S'),
                            s=1000, n=7)['channels']
            for name in names:
                events = sampled[name]['data']
                self.assertEqual(7, len(events))
                self.assertEqual([epoch_ms[0] + 1000 * index for index in range(7)], [event['d'] for event in events])
                for event, expected in zip(events, values[name] + [values[name][-1]] * 2):
                    self.assertAlmostEqual(expected, event['v'], places=6)

            stats = query('mystats', c=','.join(names), b=dates[0].strftime('%Y-%m-%dT%H:%M:%S'),
                          e=(dates[-1] + timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S'), n=1)['channels']
            for name in names:
                result = stats[name]['data'][0]
                self.assertEqual(epoch_ms[0], result['begin'])
                self.assertEqual(5, result['duration'])
                self.assertAlmostEqual(min(values[name]), result['min'], places=6)
                self.assertAlmostEqual(max(values[name]), result['max'], places=6)
                self.assertAlmostEqual(sum(values[name]) / 5, result['mean'], places=6)
            fixtures = query('channel', q='channel10%')
            self.assertTrue({'channel100', 'channel101', 'channel102'} <= {item['name'] for item in fixtures})

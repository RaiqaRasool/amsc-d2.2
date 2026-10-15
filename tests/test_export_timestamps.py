import csv
import io
import unittest
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

try:
    import pandas as pd
except ImportError:
    pd = None

if pd is not None:
    from export_timestamps import prepare_export_timestamps


@unittest.skipIf(pd is None, 'requires pandas, provided by jlab-archiver-client')
class ExportTimestampTests(unittest.TestCase):
    def test_csv_local_clock_offsets_and_precision(self):
        index = pd.DatetimeIndex(['2024-05-14 09:54:00.123456789', '2024-01-14 09:54:00'], name='Date')
        for query_type in ('mysampler', 'interval'):
            with self.subTest(query_type=query_type):
                original = pd.DataFrame({'pv': [5, 8]}, index=index)
                output = prepare_export_timestamps(original, query_type)
                rows = list(csv.reader(io.StringIO(output.to_csv())))
                self.assertEqual('2024-05-14T09:54:00.123456789-04:00', rows[1][0])
                self.assertEqual('2024-01-14T09:54:00-05:00', rows[2][0])
                self.assertEqual(['5', '8'], [row[1] for row in rows[1:]])
                self.assertIsNone(original.index.tz)
                self.assertEqual('Date', output.index.name)

    def test_mystats_multiindex_preserves_metrics(self):
        index = pd.MultiIndex.from_product([pd.to_datetime(['2024-05-14 09:54:00']), ['min', 'mean']],
                                          names=['timestamp', 'stat'])
        original = pd.DataFrame({'pv': [1, 2]}, index=index)
        output = prepare_export_timestamps(original, 'mystats')
        self.assertEqual(['2024-05-14T09:54:00-04:00'] * 2, list(output.index.get_level_values(0)))
        self.assertEqual(['min', 'mean'], list(output.index.get_level_values(1)))
        self.assertEqual(['timestamp', 'stat'], output.index.names)
        self.assertEqual([1, 2], list(output['pv']))

    def test_point_json_and_channel_metadata(self):
        original = {'data': {'d': '2024-05-14 09:54:00.123456789', 'v': 8}, 'datatype': 'DBR_DOUBLE'}
        output = prepare_export_timestamps(original, 'point')
        self.assertEqual('2024-05-14T09:54:00.123456789-04:00', output['data']['d'])
        self.assertEqual(8, output['data']['v'])
        self.assertEqual('2024-05-14 09:54:00.123456789', original['data']['d'])
        channels = [{'name': 'pv', 'datatype': 'DBR_DOUBLE'}]
        self.assertIs(channels, prepare_export_timestamps(channels, 'channel'))

    def test_already_aware_timestamps_preserve_instant(self):
        data = pd.Series([5], index=pd.DatetimeIndex(['2024-05-14T13:54:00Z']))
        self.assertEqual('2024-05-14T09:54:00-04:00', prepare_export_timestamps(data, 'interval').index[0])
        point = {'data': {'d': '2024-11-03T01:30:00-05:00', 'v': 5}}
        self.assertEqual(point, prepare_export_timestamps(point, 'point'))

    def test_ambiguous_and_nonexistent_local_times_fail(self):
        for value in ('2024-11-03 01:30:00', '2024-03-10 02:30:00'):
            for query_type in ('point', 'interval'):
                data = {'data': {'d': value}} if query_type == 'point' else pd.Series([1], index=pd.DatetimeIndex([value]))
                with self.subTest(value=value, query_type=query_type), self.assertRaisesRegex(ValueError, 'unambiguous'):
                    prepare_export_timestamps(data, query_type)

    def test_worker_serializes_offsets_into_the_actual_export_files(self):
        config = types.SimpleNamespace(MAX_MYA_OUTPUT_BYTES=1024 * 1024,
                                       MYA_OUTPUT_DIR='/unused', WORKER_QUERY_TIMEOUT_SECONDS=60,
                                       required_env=lambda name: 'unused')
        empty = lambda *args, **kwargs: None
        dependencies = {
            'config': config,
            'globus_service': types.SimpleNamespace(submit_transfer_for_job=empty,
                                                    transfer_client_from_token_reference=empty),
            'jobs': types.SimpleNamespace(get_job=empty, update_job=empty),
            'mya_query': types.SimpleNamespace(run_mya_query=empty),
        }
        spec = importlib.util.spec_from_file_location('timestamp_export_execution',
                                                     Path(__file__).resolve().parents[1] / 'job_execution.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, dependencies):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            for query_type, data in (
                ('interval', pd.Series([5], index=pd.to_datetime(['2024-05-14 09:54:00']), name='pv')),
                ('point', {'data': {'d': '2024-01-14 09:54:00', 'v': 5}}),
            ):
                path = Path(directory) / query_type
                with patch.object(module, 'run_mya_query', return_value=data):
                    module.run_and_export_mya_query({'query_type': query_type, 'query_params': {}}, str(path))
                if query_type == 'point':
                    self.assertEqual('2024-01-14T09:54:00-05:00', json.loads(path.read_text())['data']['d'])
                else:
                    self.assertIn('2024-05-14T09:54:00-04:00', path.read_text())

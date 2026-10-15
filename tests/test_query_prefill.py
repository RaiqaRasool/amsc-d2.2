import unittest
from query_prefill import query_form_values


class QueryPrefillTests(unittest.TestCase):
    def test_supported_queries_and_no_transfer_state(self):
        cases = (
            ('mysampler', {'start': '2024-05-14T09:54:00', 'interval': 1000, 'num_samples': 5, 'pvlist': ['pv1', 'pv2']}, 'mysampler_pvlist', 'pv1, pv2'),
            ('interval', {'begin': '2024-05-14T09:54:00', 'end': '2024-05-14T09:55:00', 'channel': 'pv1', 'prior_point': False}, 'interval_pvlist', 'pv1'),
            ('mystats', {'start': '2024-05-14T09:54:00', 'end': '2024-05-14T09:55:00', 'num_bins': 2, 'pvlist': ['pv']}, 'mystats_num_bins', 2),
            ('point', {'channel': 'pv', 'time': '2024-05-14T13:54:00+00:00'}, 'point_time', '2024-05-14T09:54:00'),
            ('channel', {'pattern': 'pv%'}, 'channel_pattern', 'pv%'),
        )
        for kind, params, key, expected in cases:
            with self.subTest(kind=kind):
                job = dict(query_type=kind, query_params=params, token_reference='old-secret',
                           destination_path='/old-destination', transfer_label='old-label')
                result = query_form_values(job)
                self.assertEqual(expected, result[key])
                self.assertEqual(kind, result['query_type'])
                self.assertEqual('', result['transfer_label'])
                self.assertNotIn('token_reference', result)
                self.assertNotIn('destination_path', result)
                if kind == 'interval':
                    self.assertFalse(result['interval_prior_point'])

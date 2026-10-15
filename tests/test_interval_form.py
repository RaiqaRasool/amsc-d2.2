import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class IntervalFormTests(unittest.TestCase):
    def test_unified_pvs_select_single_or_parallel_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, FLASK_SECRET_KEY='test-only', SOURCE_COLLECTION_ID='test-source')
            for key in ('JOBS_DB_PATH', 'TOKEN_DB_PATH', 'RATE_LIMIT_DB_PATH', 'OAUTH_STATE_DB_PATH'):
                environment[key] = str(Path(directory) / f'{key}.sqlite3')
            script = r'''
from unittest.mock import patch
import app as module
client = module.app.test_client()
with client.session_transaction() as session:
    session['logged_in'] = True
    session['globus_identity'] = 'test-owner'
    session['csrf_token'] = 'test-csrf'
base = dict(query_type='interval', interval_begin='2024-05-14T09:54:00',
            interval_end='2024-05-14T09:54:10', csrf_token='test-csrf')
with patch.object(module, 'transfer_client', return_value=object()), \
     patch.object(module, 'rate_limit_response', return_value=None), \
     patch.object(module, 'create_job') as create, \
     patch.object(module, 'list_jobs', return_value=[]):
    for value, prior, expected in (
        (' pv1 ', False, {'channel': 'pv1', 'prior_point': False}),
        ('pv1', True, {'channel': 'pv1', 'prior_point': True}),
        ('pv1, pv2', False, {'pvlist': ['pv1', 'pv2'], 'prior_point': True}),
    ):
        form = dict(base, interval_pvlist=value)
        if prior:
            form['interval_prior_point'] = 'true'
        create.reset_mock()
        assert client.post('/mya/query', data=form).status_code == 302
        create.assert_called_once()
        params = create.call_args.kwargs['query_params']
        assert params == dict(begin='2024-05-14T09:54:00', end='2024-05-14T09:54:10', **expected), params
    for value in ('', ' , ', 'x' * 257, ','.join('pv' + str(i) for i in range(101))):
        create.reset_mock()
        client.post('/mya/query', data=dict(base, interval_pvlist=value))
        create.assert_not_called()
    create.reset_mock()
    client.post('/mya/query', data=dict(base, interval_channel='pv1'))
    create.assert_not_called()
    page = client.get('/').data
    assert b'name="interval_channel"' not in page
    assert b'name="interval_pvlist" maxlength="25699" required' in page
    assert b'For multiple PVs, the prior point is always included.' in page
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class QueryReuseWebTests(unittest.TestCase):
    def test_owned_query_is_prefilled_without_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, FLASK_SECRET_KEY='test-only')
            for key in ('JOBS_DB_PATH', 'TOKEN_DB_PATH', 'RATE_LIMIT_DB_PATH', 'OAUTH_STATE_DB_PATH'):
                environment[key] = str(Path(directory) / f'{key}.sqlite3')
            script = r'''
from unittest.mock import patch
import app as module
import jobs
jobs.create_job(job_id='old', query_type='interval', query_params={
    'begin': '2024-05-14T09:54:00', 'end': '2024-05-14T09:55:00',
    'channel': 'pv1', 'prior_point': False}, globus_identity='owner', status='query_failed',
    token_reference='secret-token', destination_path='/old-target')
client = module.app.test_client()
assert client.get('/?reuse=old').status_code == 401
with client.session_transaction() as session:
    session['logged_in'] = True
    session['globus_identity'] = 'other'
assert client.get('/?reuse=old').status_code == 404
with client.session_transaction() as session:
    session['globus_identity'] = 'owner'
    session['destination_path'] = '/current-target'
with patch.object(module, 'create_job') as create:
    page = client.get('/?reuse=old')
    assert page.status_code == 200
    assert b'notice notice-info' in page.data
    assert b'Nothing has been submitted' in page.data
    assert b'"interval_pvlist": "pv1"' in page.data
    assert b'"interval_prior_point": false' in page.data
    assert b'"query_type": "interval"' in page.data
    assert b'secret-token' not in page.data
    assert b'Run again' in page.data
    assert b'queryForm.elements.interval_channel' not in page.data
    create.assert_not_called()
    assert b'Previous query loaded' not in client.get('/').data
with client.session_transaction() as session:
    assert session['destination_path'] == '/current-target'
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

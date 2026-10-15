"""Permanent local deletion preserves active work, shared files, and ownership."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class JobDeletionTests(unittest.TestCase):
    def test_owner_status_and_file_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, FLASK_SECRET_KEY='test', DELETE_TEST_DIR=directory)
            for key in ('JOBS_DB_PATH', 'TOKEN_DB_PATH', 'RATE_LIMIT_DB_PATH', 'OAUTH_STATE_DB_PATH'):
                environment[key] = str(Path(directory) / key)
            script = r'''
import os
from pathlib import Path
from unittest.mock import patch
import app as module
import jobs, retention
retention.MYA_OUTPUT_DIR = os.environ['DELETE_TEST_DIR']
filename = 'mya-12345678-1234-1234-1234-123456789abc.csv'
path = Path(retention.MYA_OUTPUT_DIR) / filename
path.write_text('data')
def create(name, status='query_complete', transfer=False):
    return jobs.create_job(job_id=name, status=status, query_type='mysampler', query_params={},
                           globus_identity='owner', source_path='/source/' + filename,
                           transfer_requested=transfer)
create('original')
client = module.app.test_client()
with client.session_transaction() as session:
    session.update(logged_in=True, globus_identity='other', csrf_token='csrf')
assert client.post('/jobs/original/delete', data={'csrf_token':'csrf'}).status_code == 404
with client.session_transaction() as session: session['globus_identity'] = 'owner'
assert client.get('/jobs/original/delete').status_code == 405
assert client.post('/jobs/original/delete').status_code == 302
assert jobs.get_job('original') and path.exists()
for status in ('queued','query_running','transfer_submitting','transfer_submitted','transfer_active'):
    create(status, status)
    assert client.post('/jobs/' + status + '/delete', data={'csrf_token':'csrf'}).status_code == 409
    assert jobs.get_job(status)
    with jobs.jobs_db() as connection: connection.execute('DELETE FROM mya_transfer_jobs WHERE job_id=?',(status,))
create('awaiting', transfer=True)
assert client.post('/jobs/awaiting/delete', data={'csrf_token':'csrf'}).status_code == 409
with jobs.jobs_db() as connection: connection.execute("DELETE FROM mya_transfer_jobs WHERE job_id='awaiting'")
create('attempt', 'transfer_failed')
assert client.post('/jobs/original/delete', data={'csrf_token':'csrf'}).json == {'deleted':True}
assert jobs.get_job('original') is None and path.exists()
with patch.object(retention.os, 'remove', side_effect=PermissionError('denied')):
    assert client.post('/jobs/attempt/delete', data={'csrf_token':'csrf'}).status_code == 500
assert jobs.get_job('attempt') and path.exists()
assert client.post('/jobs/attempt/delete', data={'csrf_token':'csrf'}).status_code == 200
assert not path.exists() and jobs.get_job('attempt') is None
create('missing')
assert client.post('/jobs/missing/delete', data={'csrf_token':'csrf'}).status_code == 200
assert client.post('/jobs/missing/delete', data={'csrf_token':'csrf'}).status_code == 404
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

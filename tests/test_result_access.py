"""Isolated Flask tests avoid optional-client test doubles in other modules."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ResultAccessTests(unittest.TestCase):
    def test_ownership_lifecycle_preview_and_streamed_download(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, FLASK_SECRET_KEY='test-only', TEST_RESULT_DIR=directory)
            for name in ('JOBS_DB_PATH', 'TOKEN_DB_PATH', 'RATE_LIMIT_DB_PATH', 'OAUTH_STATE_DB_PATH'):
                environment[name] = str(Path(directory) / f'{name}.sqlite3')
            script = r'''
import os
from pathlib import Path
from unittest.mock import patch
import app as module
import jobs
import retention
root = Path(os.environ['TEST_RESULT_DIR'])
retention.MYA_OUTPUT_DIR = str(root)
name = 'mya-12345678-1234-1234-1234-123456789abc.csv'
path = root / name
path.write_text('time,pv\n0,<script>alert(1)</script>\n')
jobs.create_job(job_id='owned', query_type='interval', query_params={'channel': 'pv'},
                globus_identity='owner', status='query_complete', source_path='/globus/' + name)
jobs.create_job(job_id='other', query_type='interval', query_params={},
                globus_identity='another', status='query_complete', source_path='/globus/' + name)
client = module.app.test_client()
for action in ('preview', 'download'):
    assert client.get('/jobs/owned/' + action).status_code == 401
with client.session_transaction() as session:
    session['logged_in'] = True
    session['globus_identity'] = 'owner'
for action in ('preview', 'download'):
    assert client.get('/jobs/other/' + action).status_code == 404
    assert client.get('/jobs/unknown/' + action).status_code == 404
preview = client.get('/jobs/owned/preview')
assert preview.status_code == 200
assert b'&lt;script&gt;' in preview.data
assert b'<script>alert(1)</script>' not in preview.data
assert preview.headers['Cache-Control'] == 'private, no-store'
assert b'partial preview' in preview.data
response = client.get('/jobs/owned/download')
assert response.status_code == 200
assert 'attachment' in response.headers['Content-Disposition']
assert response.data == path.read_bytes()
assert int(response.headers['Content-Length']) == path.stat().st_size
response.close()
with patch.object(module, 'list_jobs', return_value=[jobs.get_job('owned')]):
    page = client.get('/jobs/table').data
    assert b'/jobs/owned/preview' in page
    assert b'/jobs/owned/download' in page
jobs.update_job('owned', status='query_running')
assert client.get('/jobs/owned/preview').status_code == 404
jobs.update_job('owned', status='query_complete')
path.unlink()
for action in ('preview', 'download'):
    assert client.get('/jobs/owned/' + action).status_code == 404
outside = root / 'secret.txt'
outside.write_text('private')
path.symlink_to(outside)
for action in ('preview', 'download'):
    assert client.get('/jobs/owned/' + action).status_code == 404
path.unlink()
jobs.update_job('owned', source_path='/etc/passwd')
assert client.get('/jobs/owned/download').status_code == 404
jobs.update_job('owned', source_path='/globus/' + name)
jobs.delete_expired_terminal_job('owned', '9999-01-01T00:00:00Z')
assert client.get('/jobs/owned/preview').status_code == 404
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

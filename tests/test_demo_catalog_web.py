"""Run Flask checks in isolation from test modules that replace optional clients."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DemoCatalogWebTests(unittest.TestCase):
    def test_catalog_link_authentication_availability_and_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, FLASK_SECRET_KEY='test-only', MYA_DEPLOYMENT='docker')
            for name in ('JOBS_DB_PATH', 'TOKEN_DB_PATH', 'RATE_LIMIT_DB_PATH', 'OAUTH_STATE_DB_PATH'):
                environment[name] = str(Path(directory) / f'{name}.sqlite3')
            environment['DEMO_CATALOG_PATH'] = str(Path(directory) / 'catalog.csv')
            script = '''
from pathlib import Path
from unittest.mock import patch
import app as module
client = module.app.test_client()
assert client.get('/demo-catalog.csv').status_code == 302
with client.session_transaction() as session:
    session['logged_in'] = True
    session['globus_identity'] = 'test-identity'
assert client.get('/demo-catalog.csv').status_code == 404
path = Path(module.DEMO_CATALOG_PATH)
path.write_text('pv_name,stored_events\\npv1,2\\n')
response = client.get('/demo-catalog.csv')
assert response.status_code == 200
assert b'pv1,2' in response.data
assert response.headers['Cache-Control'] == 'private, no-store'
assert 'attachment' in response.headers['Content-Disposition']
path.write_text('pv_name,stored_events\\npv2,3\\n')
assert b'pv2,3' in client.get('/demo-catalog.csv').data
with patch.object(module, 'list_jobs', return_value=[]):
    page = client.get('/')
    assert b'Available demo data (CSV)' in page.data
    assert b'Only PVs available for now' not in page.data
    module.MYA_DEPLOYMENT = 'history'
    assert b'Available demo data (CSV)' not in client.get('/').data
    assert client.get('/demo-catalog.csv').status_code == 404
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

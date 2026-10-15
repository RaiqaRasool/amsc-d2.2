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
assert client.get('/demo-catalog').status_code == 302
with client.session_transaction() as session:
    session['logged_in'] = True
    session['globus_identity'] = 'test-identity'
assert client.get('/demo-catalog.csv').status_code == 404
assert client.get('/demo-catalog').status_code == 404
path = Path(module.DEMO_CATALOG_PATH)
path.write_text('pv_name,stored_events\\npv1,2\\n')
response = client.get('/demo-catalog.csv')
assert response.status_code == 200
assert b'pv1,2' in response.data
assert response.headers['Cache-Control'] == 'private, no-store'
assert 'attachment' in response.headers['Content-Disposition']
path.write_text('pv_name,stored_events\\npv2,3\\n')
assert b'pv2,3' in client.get('/demo-catalog.csv').data
page = client.get('/demo-catalog')
assert page.status_code == 200
assert page.mimetype == 'text/html'
assert 'Content-Disposition' not in page.headers
assert page.headers['Cache-Control'] == 'private, no-store'
assert b'pv2' in page.data
assert b'Download CSV' in page.data
assert b'data-copy-pv="pv2"' in page.data
assert b'data-select-pv="pv2"' in page.data
assert b'Copy 0 selected PVs' in page.data
assert b'id="copy-selected-pvs" disabled' in client.get('/demo-catalog?q=missing').data
assert b'No matching PVs' in client.get('/demo-catalog?q=missing').data
assert b'pv2' in client.get('/demo-catalog?q=PV2').data
path.write_text('pv_name,stored_events\\n<script>alert(1)</script>,1\\n')
assert b'&lt;script&gt;' in client.get('/demo-catalog').data
assert b'<script>alert(1)</script>' not in client.get('/demo-catalog').data
with patch.object(module, 'list_jobs', return_value=[]):
    page = client.get('/')
    assert b'Available demo data' not in page.data
    assert page.data.count(b'Use the ? help icon beside PVs') == 3
    assert page.data.count(b'>available demo data catalog</a>') == 3
    assert b'docs.google.com/spreadsheets' not in page.data
    assert b'Only PVs available for now' not in page.data
    module.MYA_DEPLOYMENT = 'history'
    other_page = client.get('/').data
    assert b'Available demo data' not in other_page
    assert other_page.count(b'docs.google.com/spreadsheets') == 3
    assert b'available demo data catalog' not in other_page
    assert client.get('/demo-catalog.csv').status_code == 404
    assert client.get('/demo-catalog').status_code == 404
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

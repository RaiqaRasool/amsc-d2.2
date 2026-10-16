"""Queued-job and other flashed notifications share an accessible dismiss control."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class NotificationTests(unittest.TestCase):
    def test_flash_categories_are_dismissible_and_escaped(self):
        with tempfile.TemporaryDirectory() as directory:
            env=dict(os.environ,FLASK_SECRET_KEY='test')
            for key in ('JOBS_DB_PATH','TOKEN_DB_PATH','RATE_LIMIT_DB_PATH','OAUTH_STATE_DB_PATH'):
                env[key]=str(Path(directory)/key)
            script=r'''
import app as module
client=module.app.test_client()
with client.session_transaction() as session:
    session['_flashes']=[('success','MYA job queued: example'),('error','<script>bad()</script>'),('info','Review request'),('warning','Check destination')]
page=client.get('/').data
assert page.count(b'aria-label="Dismiss notification"')==4
assert page.count(b'data-notification>')==4
assert b'MYA job queued: example' in page
assert b'&lt;script&gt;bad()&lt;/script&gt;' in page and b'<script>bad()</script>' not in page
assert b'data-dismiss-notification' in page
'''
            result=subprocess.run([sys.executable,'-c',script],env=env,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)

"""Transfer attempts retain safe query context independently of original history."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TransferQuerySnapshotTests(unittest.TestCase):
    def test_snapshot_survives_original_deletion_and_retransfer(self):
        with tempfile.TemporaryDirectory() as directory:
            env=dict(os.environ,FLASK_SECRET_KEY='test',SNAPSHOT_TEST_DIR=directory)
            for key in ('JOBS_DB_PATH','TOKEN_DB_PATH','RATE_LIMIT_DB_PATH','OAUTH_STATE_DB_PATH'):
                env[key]=str(Path(directory)/key)
            script=r'''
import os,json
from pathlib import Path
from unittest.mock import patch, MagicMock
import app as module
import jobs,retention
retention.MYA_OUTPUT_DIR=os.environ['SNAPSHOT_TEST_DIR']
filename='mya-12345678-1234-1234-1234-123456789abc.csv'
(Path(retention.MYA_OUTPUT_DIR)/filename).write_text('time,pv\n1,2\n')
collection='12345678-1234-1234-1234-123456789abc'
params=dict(begin='2024-05-09T08:53:00',end='2024-05-09T08:54:00',channel='pv',prior_point=False,token_reference='do-not-copy')
jobs.create_job(job_id='original',status='query_complete',query_type='interval',query_params=params,
                globus_identity='owner',source_path='/exports/'+filename,source_collection_id=collection)
client=module.app.test_client()
with client.session_transaction() as session:
    session.update(logged_in=True,globus_identity='owner',csrf_token='csrf',token_reference='current',
                   destination_collection_id=collection,destination_path='/dest',destination_selection_id='proof')
data=dict(csrf_token='csrf',destination_selection_id='proof',validated_collection_id=collection,validated_destination_path='/dest')
with patch.object(module,'transfer_client',return_value=MagicMock()),patch.object(module,'rate_limit_response',return_value=None):
    client.post('/jobs/original/transfer',data=data)
    attempt=next(j for j in jobs.list_jobs('owner') if j['query_type']=='transfer')
    snapshot=attempt['query_params']['source_query']
    assert snapshot['query_type']=='interval' and snapshot['query_params']['channel']=='pv'
    assert 'token_reference' not in snapshot['query_params']
    assert retention.delete_owned_job('original','owner')
    details=client.get('/jobs/'+attempt['job_id']+'/query')
    assert details.status_code==200 and b'2024-05-09T08:53:00' in details.data
    assert b'do-not-copy' not in details.data and b'current' not in details.data
    page=client.get('/?reuse='+attempt['job_id']+'&cancel_transfer=1')
    assert b'"interval_pvlist": "pv"' in page.data and b'"interval_prior_point": false' in page.data
    jobs.update_job(attempt['job_id'],status='transfer_succeeded')
    preview=client.get('/jobs/'+attempt['job_id']+'/preview')
    assert preview.status_code==200 and b'2024-05-09T08:53:00' in preview.data
    history=client.get('/').data
    assert b'aria-label="Run query again"' in history
    assert b'aria-label="Transfer file again"' in history
    assert b'aria-label="View query parameters"' in history
    before=len(jobs.list_jobs('owner'))
    review=client.get('/?transfer='+attempt['job_id'])
    assert review.status_code==200 and len(jobs.list_jobs('owner'))==before
    client.post('/jobs/'+attempt['job_id']+'/transfer',data=data)
    repeated=next(j for j in jobs.list_jobs('owner') if j['status']=='queued')
    assert repeated['query_params']['source_query']==snapshot
    assert repeated['token_reference']=='current'
    # Legacy transfers can use an owner-scoped parent, never another owner's job.
    jobs.create_job(job_id='foreign',status='query_complete',query_type='point',query_params={'channel':'secret-pv','time':'2024-01-01'},globus_identity='other')
    jobs.create_job(job_id='legacy',status='transfer_failed',query_type='transfer',query_params={'parent_job_id':'foreign'},globus_identity='owner')
    legacy=client.get('/jobs/legacy/query')
    assert b'parameters are unavailable' in legacy.data and b'secret-pv' not in legacy.data
    jobs.create_job(job_id='parent',status='query_complete',query_type='point',query_params={'channel':'pv','time':'2024-01-01'},globus_identity='owner')
    jobs.update_job('legacy',query_params=json.dumps({'parent_job_id':'parent'}))
    assert b'2024-01-01' in client.get('/jobs/legacy/query').data
    with client.session_transaction() as session: session['globus_identity']='other'
    assert client.get('/jobs/'+attempt['job_id']+'/query').status_code==404
    assert client.get('/?reuse='+attempt['job_id']).status_code==404
'''
            result=subprocess.run([sys.executable,'-c',script],env=env,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)

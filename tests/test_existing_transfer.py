"""Owner-scoped transfer attempts reuse finished exports, never rerun MYA."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ExistingTransferTests(unittest.TestCase):
    def test_existing_output_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, FLASK_SECRET_KEY='test', MYA_OUTPUT_DIR=directory)
            for key in ('JOBS_DB_PATH', 'TOKEN_DB_PATH', 'RATE_LIMIT_DB_PATH', 'OAUTH_STATE_DB_PATH'):
                environment[key] = str(Path(directory) / key)
            script = r'''
import sys, types, os
from pathlib import Path
from unittest.mock import patch, MagicMock
import app as module
import jobs, retention
import config, result_preview
MYA_OUTPUT_DIR = os.environ["MYA_OUTPUT_DIR"]
config.MYA_OUTPUT_DIR = retention.MYA_OUTPUT_DIR = MYA_OUTPUT_DIR
collection = '12345678-1234-1234-1234-123456789abc'
filename = 'mya-' + collection + '.csv'
export = Path(MYA_OUTPUT_DIR) / filename
export.write_text('time,pv\n1,2\n')
jobs.create_job(job_id='original', status='query_complete', query_type='mysampler',
                query_params={}, globus_identity='owner', source_collection_id=collection,
                source_path='/exports/' + filename)
client = module.app.test_client()
assert client.post('/jobs/original/transfer', data={}).status_code == 302
with client.session_transaction() as session:
    session.update(logged_in=True, globus_identity='other', csrf_token='csrf')
assert client.get('/?transfer=original').status_code == 404
with client.session_transaction() as session:
    session.update(globus_identity='owner', token_reference='fresh',
                   destination_collection_id=collection, destination_path='/dest',
                   destination_collection_name='Destination', destination_selection_id='proof')
with patch.object(module, 'transfer_client', return_value=MagicMock()), patch.object(module, 'rate_limit_response', return_value=None):
    with module.app.test_request_context('/'):
        display = module.job_for_display(dict(jobs.get_job('original'), updated_at='2026-10-15T19:47:37Z',
            destination_path='/dest/' + filename, destination_collection_id=collection,
            globus_task_id='87654321-1234-1234-1234-123456789abc'))
        assert display['destination_folder'] == '/dest'
        assert display['updated_date'] == '2026-10-15'
        assert display['updated_time'] == '15:47:37 EDT (UTC-0400)'
        history = module.render_template('_jobs.html', jobs=[display])
        assert 'Submitted job' in history and 'Globus transfer' in history
        assert 'Browse source folder in Globus' in history and 'View transfer' in history
        assert 'Path:</strong>' not in history
    page = client.get('/?transfer=original')
    assert page.status_code == 200 and b'Transfer existing output' in page.data
    assert b'Transfer file' in page.data and b'formnovalidate' in page.data
    assert client.post('/jobs/original/transfer', data={'csrf_token':'csrf'}).status_code == 302
    assert len(jobs.list_jobs('owner')) == 1
    data = dict(csrf_token='csrf', destination_selection_id='proof',
                validated_collection_id=collection, validated_destination_path='/dest', transfer_label='Later')
    client.post('/jobs/original/transfer', data=data)
    attempts = [j for j in jobs.list_jobs('owner') if j['query_type'] == 'transfer']
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt['source_path'] == '/exports/' + filename
    assert attempt['query_params'] == {'parent_job_id':'original'}
    assert attempt['token_reference'] == 'fresh' and attempt['status'] == 'queued'
    assert jobs.get_job('original')['status'] == 'query_complete'
    assert jobs.export_has_other_jobs(jobs.get_job('original'))
    # Retention can delete the old query record, but must preserve the shared file.
    with jobs.jobs_db() as connection:
        connection.execute("UPDATE mya_transfer_jobs SET updated_at='2000-01-01T00:00:00Z' WHERE job_id='original'")
    retention.cleanup_expired_jobs()
    assert export.exists() and jobs.get_job('original') is None
    # Worker dispatches transfer-only jobs without calling the query executor.
    execute_query = MagicMock(side_effect=AssertionError('Must not rerun MYA'))
    execute_transfer = MagicMock(side_effect=lambda j: jobs.update_job(j['job_id'], status='transfer_submitted'))
    sys.modules['job_execution'] = types.SimpleNamespace(execute_mya_query=execute_query, execute_job_transfer=execute_transfer)
    import worker
    assert worker.process_next_job()
    execute_query.assert_not_called()
    execute_transfer.assert_called_once()
    assert jobs.get_job(attempt['job_id'])['status'] == 'transfer_submitted'
    jobs.update_job(attempt['job_id'], status='query_failed')
    retry_page = client.get('/?transfer=' + attempt['job_id'])
    assert retry_page.status_code == 200 and b'Retry transfer' in retry_page.data
    assert b'aria-label="Retry transfer"' in retry_page.data
    assert b'Transfer of' not in retry_page.data and b'>original query</a>' not in retry_page.data
    client.post('/jobs/' + attempt['job_id'] + '/transfer', data=data)
    retries = [j for j in jobs.list_jobs('owner') if j['status'] == 'queued']
    assert len(retries) == 1 and retries[0]['query_params']['parent_job_id'] == 'original'
    jobs.update_job(attempt['job_id'], status='transfer_submitted')
    export.unlink()
    assert client.get('/?transfer=' + attempt['job_id']).status_code == 409
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

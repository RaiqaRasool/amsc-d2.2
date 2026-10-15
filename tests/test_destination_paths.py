import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DestinationPathTests(unittest.TestCase):
    def test_direct_selection_and_inline_browse(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, FLASK_SECRET_KEY='test-only', SOURCE_COLLECTION_ID='12345678-1234-1234-1234-123456789abc')
            for key in ('JOBS_DB_PATH', 'TOKEN_DB_PATH', 'RATE_LIMIT_DB_PATH', 'OAUTH_STATE_DB_PATH'):
                environment[key] = str(Path(directory) / f'{key}.sqlite3')
            script = r'''
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import app as module
collection_id = '12345678-1234-1234-1234-123456789abc'
client = module.app.test_client()
browse = '/collections/' + collection_id + '/browse'
assert client.get(browse).status_code == 401
assert client.get('/collections/search?q=test').status_code == 401
with client.session_transaction() as session:
    session.update(logged_in=True, globus_identity='owner', token_reference='current-token',
                   csrf_token='test-csrf', destination_collection_id=collection_id,
                   destination_collection_name='Current collection', destination_path='/old')
api = MagicMock()
api.operation_ls.return_value = [{'name': 'folder', 'type': 'dir'}, {'name': 'file.csv', 'type': 'file'}]
api.get_endpoint.return_value = {'display_name': 'Current collection'}
api.endpoint_search.return_value = [{'id': collection_id, 'display_name': 'Test collection'}]
class BrowseError(Exception):
    def __init__(self, consent=False):
        self.info = SimpleNamespace(consent_required=consent)
        self.message = 'Permission denied'
        self.code = 'EndpointError'
with patch.object(module, 'transfer_client', return_value=api), \
     patch.object(module, 'rate_limit_response', return_value=None) as limited, \
     patch.object(module, 'GlobusAPIError', BrowseError), \
     patch.object(module, 'list_jobs', return_value=[]):
    page = client.get('/').data
    assert b'Current collection</span>' in page
    assert b'Destination folder path' in page
    assert b'Use this folder' not in page
    assert b'press Enter' in page
    assert b'aria-label="Refresh folder"' in page
    assert b'aria-label="Reset destination"' in page
    assert b'id="destination-collection"' in page
    response = client.get('/collections/search?q=test')
    assert response.status_code == 200
    assert response.json['collections'] == [{'id': collection_id, 'name': 'Test collection'}]
    assert response.headers['Cache-Control'] == 'private, no-store'
    api.endpoint_search.return_value = [{'id': collection_id, 'display_name': str(i)} for i in range(20)]
    assert len(client.get('/collections/search?q=test').json['collections']) == 10
    api.endpoint_search.reset_mock()
    assert client.get('/collections/search?q=' + 'x' * 129 + '').status_code == 400
    api.endpoint_search.assert_not_called()
    with client.session_transaction() as session:
        session.pop('destination_collection_id', None)
        session.pop('destination_path', None)
    fresh_page = client.get('/').data
    assert b'id="destination-path"' in fresh_page
    assert b'id="destination-collection"' in fresh_page
    with client.session_transaction() as session:
        session['destination_collection_id'] = collection_id
        session['destination_path'] = '/old'
    response = client.get(browse + '?path=/old')
    assert response.status_code == 200
    assert response.json['folders'] == [{'name': 'folder', 'path': '/old/folder'}]
    assert response.json['parent_path'] == '/'
    limited.assert_called_with('identity:owner', 'collection_browse', module.COLLECTION_BROWSE_RATE_LIMITS)
    with client.session_transaction() as session:
        assert session['destination_path'] == '/old'  # Browsing is not selecting.
    api.operation_ls.return_value = [{'name': str(i), 'type': 'dir'} for i in range(300)]
    response = client.get(browse)
    assert response.json['limited'] and len(response.json['folders']) == 200
    api.operation_ls.return_value = []  # Empty directories are valid.
    response = client.post('/destination/select', data=dict(collection_id=collection_id, path='new folder/sub', csrf_token='test-csrf'))
    assert response.status_code == 200
    assert response.json['selection_id']
    selected = response.json
    api.operation_ls.assert_called_with(collection_id, path='/new folder/sub')
    with client.session_transaction() as session:
        assert session['destination_path'] == '/new folder/sub'
    api.operation_ls.reset_mock()
    base_query = dict(query_type='channel', channel_pattern='pv%', submit_action='query_and_transfer', csrf_token='test-csrf')
    with patch.object(module, 'create_job') as create:
        client.post('/mya/query', data=base_query)
        create.assert_not_called()
        validated = dict(base_query, destination_selection_id=selected['selection_id'],
                         validated_collection_id=collection_id, validated_destination_path=selected['path'])
        client.post('/mya/query', data=dict(validated, validated_destination_path='/unvalidated'))
        create.assert_not_called()
        client.post('/mya/query', data=validated)
        create.assert_called_once()
        assert create.call_args.kwargs['destination_path'] == selected['path']
        api.operation_ls.assert_not_called()  # No repeated folder request on transfer.
    api.operation_ls.side_effect = BrowseError()
    response = client.post('/destination/select', data=dict(collection_id=collection_id, path='/denied', csrf_token='test-csrf'))
    assert response.status_code == 400
    with client.session_transaction() as session:
        assert session['destination_path'] == '/new folder/sub'
    response = client.get(browse + '?path=/denied')
    assert response.status_code == 400
    assert 'Permission denied' in response.json['error']
    api.operation_ls.side_effect = BrowseError(consent=True)
    response = client.get(browse + '?path=/consent')
    assert response.status_code == 403
    assert response.json['login_url'] == '/login'
    with client.session_transaction() as session:
        assert collection_id in session['consent_collection_ids']
        assert session['post_auth_redirect'] == '/'
    response = client.post('/destination/select', data=dict(collection_id=collection_id, path='/consent', csrf_token='test-csrf'))
    assert response.status_code == 403 and response.json['login_url'] == '/login'
    limited.return_value = ('rate limited', 429, {'Retry-After': '30'})
    for url in (browse, '/collections/search?q=test'):
        response = client.get(url)
        assert response.status_code == 429 and response.is_json
        assert response.headers['Retry-After'] == '30'
    limited.return_value = None
    api.reset_mock()
    client.post('/destination/select', data=dict(collection_id=collection_id, path='x' * 1025, csrf_token='test-csrf'))
    api.operation_ls.assert_not_called()
    client.post('/destination/select', data=dict(collection_id='invalid', path='/valid', csrf_token='test-csrf'))
    api.operation_ls.assert_not_called()
    client.post('/destination/select', data=dict(collection_id=collection_id, path='/valid'))
    api.operation_ls.assert_not_called()
    with client.session_transaction() as session:
        assert session['destination_path'] == '/new folder/sub'

with client.session_transaction() as session:
    session['post_auth_redirect'] = '/collections/' + collection_id + '/browse?path=/old'
    session[module.OAUTH_SESSION_STATES_KEY] = ['test-state']
tokens = MagicMock()
tokens.decode_id_token.return_value = {'sub': 'owner'}
auth = MagicMock()
auth.oauth2_exchange_code_for_tokens.return_value = tokens
with patch.object(module, 'auth_client', return_value=auth), \
     patch.object(module, 'consume_oauth_state', return_value=True), \
     patch.object(module, 'store_token_response', return_value='new-token'), \
     patch.object(module, 'required_env', return_value='http://localhost/callback'):
    response = client.get('/callback?state=test-state&code=test-code')
    assert response.status_code == 302
    assert response.headers['Location'] == '/'
    with client.session_transaction() as session:
        assert 'post_auth_redirect' not in session
        assert 'destination_selection_id' not in session
response = client.post('/destination/reset', data={'csrf_token': 'test-csrf'})
assert response.status_code == 200 and response.json['reset']
with client.session_transaction() as session:
    assert 'destination_path' not in session
    assert 'destination_collection_id' not in session
    assert 'destination_selection_id' not in session
'''
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

"""Allowlisted query-only form values for reviewing a historical request."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo


QUERY_FIELDS = {
    'mysampler': ('start', 'interval', 'num_samples', 'pvlist'),
    'interval': ('begin', 'end', 'prior_point', 'pvlist'),
    'mystats': ('start', 'end', 'num_bins', 'pvlist'),
    'point': ('channel', 'time'),
    'channel': ('pattern',),
}


def query_form_values(job):
    query_type = job['query_type']
    params = job['query_params']
    if query_type not in QUERY_FIELDS:
        raise ValueError('Unsupported historical query type')
    result = {'query_type': query_type, 'transfer_label': ''}
    for field in QUERY_FIELDS[query_type]:
        value = params.get(field, '')
        if field == 'pvlist':
            value = ', '.join(value) if value else params.get('channel', '')
        elif field in ('start', 'begin', 'end', 'time') and value:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone(ZoneInfo('America/New_York')).replace(tzinfo=None)
            value = timestamp.isoformat()
        elif field == 'prior_point':
            value = params.get(field, False)
        result[f'{query_type}_{field}'] = value
    return result


def query_snapshot(job):
    """Copy query inputs only, never credentials, destinations, or task state."""
    source = job['query_params'].get('source_query') if job['query_type'] == 'transfer' else job
    if not isinstance(source, dict) or source.get('query_type') not in QUERY_FIELDS:
        raise ValueError('Original query parameters are unavailable for this older transfer.')
    query_type = source['query_type']
    params = source.get('query_params')
    if not isinstance(params, dict):
        raise ValueError('Original query parameters are unavailable.')
    allowed = QUERY_FIELDS[query_type] + (('channel',) if query_type == 'interval' else ())
    snapshot = {'query_type': query_type,
                'query_params': {key: deepcopy(params[key]) for key in allowed if key in params}}
    query_form_values(snapshot)
    return snapshot

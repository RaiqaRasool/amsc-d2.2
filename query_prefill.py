"""Allowlisted query-only form values for reviewing a historical request."""
from datetime import datetime
from zoneinfo import ZoneInfo


def query_form_values(job):
    query_type = job['query_type']
    params = job['query_params']
    fields = {
        'mysampler': ('start', 'interval', 'num_samples', 'pvlist'),
        'interval': ('begin', 'end', 'prior_point', 'pvlist'),
        'mystats': ('start', 'end', 'num_bins', 'pvlist'),
        'point': ('channel', 'time'),
        'channel': ('pattern',),
    }
    if query_type not in fields:
        raise ValueError('Unsupported historical query type')
    result = {'query_type': query_type, 'transfer_label': ''}
    for field in fields[query_type]:
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

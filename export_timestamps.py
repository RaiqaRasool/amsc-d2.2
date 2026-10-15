"""Serialize confirmed MyQuery local times with explicit New York UTC offsets."""

from datetime import datetime

import pandas as pd

EXPORT_TIMEZONE = 'America/New_York'


def _localize(index):
    try:
        if index.tz is None:
            return index.tz_localize(EXPORT_TIMEZONE, ambiguous='raise', nonexistent='raise')
        return index.tz_convert(EXPORT_TIMEZONE)
    except Exception as error:
        raise ValueError(
            'Cannot assign an unambiguous America/New_York offset to export timestamps. '
            'A timestamp may fall in a repeated or nonexistent daylight-saving hour.'
        ) from error


def prepare_export_timestamps(data, query_type):
    """Return export-ready values without changing the client's original result."""
    if query_type == 'channel':
        return data
    if query_type == 'point':
        event = data.get('data')
        if not isinstance(event, dict) or 'd' not in event:
            return data
        value = event['d']
        if not isinstance(value, (str, datetime, pd.Timestamp)):
            raise ValueError('Expected a date/time string in the Point query result.')
        timestamp = _localize(pd.DatetimeIndex([pd.Timestamp(value)]))[0]
        return {**data, 'data': {**event, 'd': timestamp.isoformat()}}

    index = data.index
    dates = index.get_level_values(0) if isinstance(index, pd.MultiIndex) else index
    if not isinstance(dates, pd.DatetimeIndex):
        raise ValueError('Expected a datetime index in the MYA query result.')
    formatted = _localize(dates).map(lambda timestamp: timestamp.isoformat())
    result = data.copy(deep=False)
    if isinstance(index, pd.MultiIndex):
        result.index = pd.MultiIndex.from_arrays(
            [formatted] + [index.get_level_values(level) for level in range(1, index.nlevels)],
            names=index.names,
        )
    else:
        result.index = pd.Index(formatted, name=index.name)
    return result

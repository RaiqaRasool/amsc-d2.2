"""Publish a CSV inventory of PVs currently stored in the local demo archive."""

import argparse
import csv
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / 'demo-catalog' / 'demo-catalog.csv'
# JeffersonLab/jmyapi MyaDataType enum, verified at 7f2301e2.
DATATYPE_NAMES = ('DBR_STRING', 'DBR_SHORT', 'DBR_FLOAT', 'DBR_ENUM',
                  'DBR_CHAR', 'DBR_LONG', 'DBR_DOUBLE')
CATALOG_FIELDS = ('pv_name', 'datatype', 'value_shape', 'first_stored_event',
                  'last_stored_event', 'stored_events')


def _query(command, sql):
    result = subprocess.run(command, input=sql, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Catalog database query failed: {result.stderr.strip()}")
    return [line.split('\t') for line in result.stdout.splitlines() if line]


def _event_date(value, zone):
    if value == 'NULL':
        return ''
    timestamp = int(value)
    seconds, fraction = divmod(timestamp, 1 << 28)
    instant = datetime.fromtimestamp(seconds, timezone.utc) + timedelta(microseconds=fraction * 1_000_000 // (1 << 28))
    return instant.astimezone(zone).isoformat(timespec='microseconds')


def refresh_catalog(command, output_path=DEFAULT_CATALOG_PATH, timezone_name='America/New_York'):
    """Replace the catalog only after every database query and CSV write succeeds.

    The importer must be finished and other archive writers idle during refresh.
    Only local demo-host channels are included; no source-file provenance is inferred.
    """
    zone = ZoneInfo(timezone_name)
    inventory = _query(command, "SELECT chan_id,HEX(name),type,size FROM channels WHERE host='mya' ORDER BY name;\n")
    channels = {}
    for channel_id, name_hex, datatype, size in inventory:
        channel_id = int(channel_id)
        if not 0 <= channel_id <= 2**32 - 1 or channel_id in channels:
            raise ValueError('Invalid or duplicate channel ID in database catalog')
        # Pinned mycontainer's channels.name uses latin1. HEX avoids TSV escaping.
        channels[channel_id] = (bytes.fromhex(name_hex).decode('latin1'), int(datatype), int(size))
    statements = [f"SELECT {channel_id},MIN(time),MAX(time),COUNT(*) FROM `table_{channel_id}`"
                  for channel_id in channels]
    ranges = _query(command, ' UNION ALL '.join(statements) + ';\n') if statements else []
    if len(ranges) != len(channels):
        raise ValueError('Incomplete catalog query result')
    rows = []
    seen = set()
    for channel_id, first, last, count in ranges:
        channel_id, count = int(channel_id), int(count)
        if channel_id not in channels or channel_id in seen or count < 0:
            raise ValueError('Invalid catalog event range')
        seen.add(channel_id)
        name, datatype, size = channels[channel_id]
        if not 0 <= datatype < len(DATATYPE_NAMES) or size < 1:
            raise ValueError(f'Unsupported datatype or element count for {name!r}')
        shape = 'scalar' if size == 1 else f'array ({size} elements)'
        rows.append((name, DATATYPE_NAMES[datatype], shape,
                     _event_date(first, zone), _event_date(last, zone), count))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=output_path.parent, prefix='.catalog-', delete=False) as output:
            temporary = Path(output.name)
            writer = csv.writer(output)
            writer.writerow(CATALOG_FIELDS)
            writer.writerows(sorted(rows))
        temporary.chmod(0o644)  # The web container reads the operator-generated file.
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(rows)


def main():
    if __package__:
        from .import_sql import mysql_command
    else:
        from import_sql import mysql_command
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', choices=('docker', 'podman'), default='docker')
    parser.add_argument('--compose-file', default='docker-compose.yml')
    parser.add_argument('--output', default=str(DEFAULT_CATALOG_PATH))
    args = parser.parse_args()
    try:
        count = refresh_catalog(mysql_command(args.runtime, args.compose_file), args.output)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f'Catalog refresh failed: {error}\n')
    print(f'Published {count} PVs to {args.output}')


if __name__ == '__main__':
    main()

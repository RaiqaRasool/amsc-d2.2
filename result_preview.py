"""Bounded views of finished local exports; no user-controlled filesystem paths."""
import csv
import io
import os
import stat

from retention import generated_export_path

MAX_PREVIEW_BYTES = 256 * 1024
MAX_PREVIEW_ROWS = 100
MAX_PREVIEW_COLUMNS = 50
MAX_CELL_CHARS = 500


def open_export(job):
    path = generated_export_path(job.get('source_path'))
    if not path or job.get('status') in ('queued', 'query_running', 'query_failed'):
        raise FileNotFoundError('No finished export')
    # Refuse links and non-regular files, opening the checked file only once.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise FileNotFoundError('Not an export file')
        return os.fdopen(descriptor, 'rb'), os.path.basename(path), metadata.st_size
    except BaseException:
        os.close(descriptor)
        raise


def preview_export(source, filename):
    raw = source.read(MAX_PREVIEW_BYTES + 1)
    byte_limited = len(raw) > MAX_PREVIEW_BYTES
    text = raw[:MAX_PREVIEW_BYTES].decode('utf-8', errors='replace')
    if filename.endswith('.json'):
        return dict(headers=[], rows=[], text=text, limited=byte_limited, format='JSON')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    rows, headers = [], []
    parse_error = False
    try:
        headers = next(reader, [])
        for row in reader:
            rows.append(row)
            if len(rows) > MAX_PREVIEW_ROWS:
                break
    except csv.Error:
        parse_error = True
    more_rows = len(rows) > MAX_PREVIEW_ROWS
    if byte_limited and not more_rows and not parse_error and rows:
        rows.pop()  # The last parsed record may end in the middle of the byte slice.
    rows = rows[:MAX_PREVIEW_ROWS]
    display_limited = len(headers) > MAX_PREVIEW_COLUMNS

    def clip(value):
        nonlocal display_limited
        if len(value) > MAX_CELL_CHARS:
            display_limited = True
            return value[:MAX_CELL_CHARS] + '…'
        return value

    headers = [clip(value) for value in headers[:MAX_PREVIEW_COLUMNS]]
    clipped_rows = []
    for row in rows:
        if len(row) > MAX_PREVIEW_COLUMNS:
            display_limited = True
        clipped_rows.append([clip(value) for value in row[:MAX_PREVIEW_COLUMNS]])
    return dict(headers=headers, rows=clipped_rows, text=None,
                limited=byte_limited or more_rows or parse_error or display_limited, format='CSV')

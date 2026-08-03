# Data Retention

## Purpose

Prevent completed MYA exports and historical job records from consuming disk
space indefinitely.

## Expected Behavior

- Terminal jobs and their exports are retained for 30 days by default.
- Cleanup runs from the worker once per hour by default.
- `JOB_RETENTION_DAYS` and `CLEANUP_INTERVAL_SECONDS` configure the behavior.
- Terminal states are `query_complete`, `query_failed`, `transfer_succeeded`,
  `transfer_failed`, and `transfer_auth_failed`.
- Queued, running, submitted, inactive, and retrying work is never removed.
- File deletion is restricted to generated `mya-<uuid>.csv` and
  `mya-<uuid>.json` names inside the configured output directory.
- A database record is retained for retry when its export cannot be removed.

## Failure Behavior

Missing export files do not block record cleanup. Filesystem and cleanup-level
errors are logged server-side without stopping the worker's job loop.

## Key Components

- `retention.py`: cutoff calculation and restricted file cleanup
- `jobs.py`: terminal-job selection and conditional deletion
- `worker.py`: scheduled cleanup execution

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_retention.py'`.

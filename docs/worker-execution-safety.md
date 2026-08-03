# Worker Execution Safety

## Purpose

Bound the time and disk space consumed by each MYA job and prevent internal
exception details from being exposed through job records.

## Main Flow

1. The worker runs each MYA query and export in an isolated child process.
2. The child writes through a byte-limited writer to a temporary file.
3. The parent terminates the query process group, including parallel child
   processes, when work exceeds the configured deadline.
4. A successful temporary export is atomically renamed to its final filename.

## Expected Behavior

- MYA retrieval plus local export creation defaults to a one-hour limit.
- Each export defaults to a 1 GiB maximum.
- `WORKER_QUERY_TIMEOUT_SECONDS` and `MAX_MYA_OUTPUT_BYTES` configure the limits.
- The execution deadline does not apply to asynchronous Globus data movement.
- Failed and interrupted jobs leave no partial export file.
- Detailed exceptions are written to server logs, not job `error_message` values.

## Failure Behavior

Timeouts, oversized exports, and unexpected failures set the job to
`query_failed` with a bounded, user-safe explanation. Unexpected transfer
worker failures follow the same log-versus-user-message boundary.

## Key Components

- `worker_limits.py`: child-process deadline and byte-limited writer
- `job_execution.py`: temporary export lifecycle and safe failure messages
- `worker.py`: last-resort logging and safe worker errors

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_worker_limits.py'`.

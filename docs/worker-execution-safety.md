# Worker Execution Safety

## Purpose

Bound the time and disk space consumed by each MYA job while giving users a
concise reason when the MYA backend rejects or cannot complete a query.

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
- MYA failure reasons are collapsed to one line, limited to 500 characters, and
  stored in the job `error_message`.
- Exception types and tracebacks remain limited to server logs.

## Failure Behavior

Timeouts, oversized exports, and unexpected failures set the job to
`query_failed` with a bounded explanation. When the MYA process supplies an
exception message, the jobs API and jobs table show it after `MYA query failed:`.
Failures without a message use a generic support message. Unexpected transfer
worker failures keep the generic log-versus-user-message boundary.

## Key Components

- `worker_limits.py`: child-process deadline and byte-limited writer
- `job_execution.py`: temporary export lifecycle and safe failure messages
- `worker.py`: last-resort logging and safe worker errors

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_worker_limits.py'`.

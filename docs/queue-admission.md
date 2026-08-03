# Queue Admission

## Purpose

Allow researchers to submit asynchronous batches while bounding unprocessed
work stored by the application.

## Expected Behavior

- A user may have up to 10 pending MYA jobs by default.
- The application may have up to 500 pending MYA jobs globally by default.
- Only `queued` and `query_running` jobs count as pending.
- Completed, failed, and Globus-submitted jobs do not consume queue capacity.
- `MAX_PENDING_JOBS_PER_USER` and `MAX_PENDING_JOBS_GLOBAL` configure the caps.
- Capacity checks and job insertion occur in one SQLite write transaction, so
  concurrent submissions cannot exceed the configured limits.

## Failure Behavior

A rejected job is not created and does not contact MYA. The user sees whether
their own pending-job limit or the global application capacity was reached.

## Key Components

- `jobs.py`: atomic capacity check and job insertion
- `app.py`: configured limits and user-facing rejection messages

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_queue_admission.py'`.

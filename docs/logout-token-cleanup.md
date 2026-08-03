# Logout Token Cleanup

## Purpose

Remove server-side Globus credentials after logout without breaking the
application's asynchronous transfer workflow.

## Expected Behavior

- Logout permanently retires the session's opaque token reference before
  clearing the browser session.
- No new transfer job can use a retired reference, including submissions racing
  with logout from another browser tab.
- An unused reference is revoked and deleted immediately.
- A reference needed by queued, running, submitted, or retrying transfer work is
  retained until every associated transfer job becomes terminal.
- The monitor retries deferred cleanup after refreshing Globus task states.
- Access and refresh tokens for every resource server in the namespace are
  revoked through Globus Auth and removed from SQLite token storage.

## Failure Behavior

Transient revocation or storage failures are logged and remain pending for a
later monitor retry. Logout still clears the browser session after cleanup has
been durably scheduled.

## Key Components

- `jobs.py`: retirement markers and unfinished-transfer checks
- `globus_service.py`: Globus revocation and namespace deletion
- `token_cleanup.py`: immediate and deferred cleanup orchestration
- `app.py`: logout scheduling
- `monitor.py`: deferred cleanup retries

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_token_cleanup.py'`.

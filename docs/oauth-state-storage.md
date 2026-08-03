# OAuth State Storage

## Purpose

Keep Globus OAuth callbacks valid across web restarts and multiple workers while
preventing cross-session use, expiry bypass, and replay.

## Expected Behavior

- Login generates a cryptographically random OAuth state.
- The signed browser session retains at most five pending raw states to support
  parallel login and collection-consent tabs.
- SQLite stores only SHA-256 state digests, never raw state values.
- State records expire after ten minutes by default; stale records are removed
  during later state creation and consumption.
- Callback validation requires both a constant-time browser-session match and
  an atomic one-time database consume.
- `OAUTH_STATE_DB_PATH` and `OAUTH_STATE_TTL_SECONDS` configure storage and
  expiry.

## Failure Behavior

Missing, expired, cross-session, and replayed states return the same generic
HTTP 400 response. No authorization-code exchange occurs.

## Key Components

- `oauth_states.py`: persistent hashed state creation and atomic consumption
- `app.py`: browser-session binding and callback enforcement

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_oauth_states.py'`.

# Web Input Validation

## Purpose

Reject malformed or oversized non-MYA input before it reaches Globus or enters
application state, without rewriting valid user paths or labels.

## Expected Behavior

- Collection searches accept at most 128 characters.
- Collection IDs must be canonical 36-character UUIDs.
- Destination and browse paths accept at most 1,024 UTF-8 bytes.
- Transfer labels accept at most 128 characters after the 20-character
  application prefix; the form therefore allows 108 user-entered characters.
- OAuth authorization codes accept at most 2,048 characters.
- OAuth state values accept at most 128 characters and must still exactly match
  a generated pending state.
- Searches, paths, and labels reject null and other control characters.
- Valid Unicode, spaces, punctuation, and path separators are preserved.
- Browser length constraints provide early feedback; backend validation remains
  authoritative and runs before Globus API calls.
- Stored destinations are revalidated when a transfer job is queued, including
  values retained by sessions created before these checks were introduced.

## Failure Behavior

Invalid collection, path, search, and label input returns the user home with a
friendly error and performs no Globus request. Invalid OAuth callbacks receive
a generic HTTP 400 page without state diagnostics.

## Key Components

- `web_validation.py`: format and length validation
- `app.py`: trust-boundary enforcement
- `templates/index.html`: browser length constraints
- `templates/400.html`: safe OAuth callback errors

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_web_validation.py'`.

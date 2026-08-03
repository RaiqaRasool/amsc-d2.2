# CSRF Protection

## Purpose

Prevent another website from submitting state-changing requests through an
authenticated user's browser.

## Expected Behavior

- A random CSRF token is stored in the signed Flask session and rendered into
  every POST form.
- Every POST request is rejected before its route runs unless its form token
  matches the session token.
- Logout uses POST and requires the same CSRF validation.
- Query-draft persistence excludes the CSRF field, so a token saved before
  login or session rotation cannot replace the newly rendered token.
- GET requests remain unaffected.

## Failure Behavior

Missing, changed, or expired tokens return the user to the home page with a
friendly error. The requested action is not performed.

## Key Components

- `csrf.py`: token generation and constant-time comparison
- `app.py`: template token injection and POST request guard
- `templates/`: hidden tokens on every POST form

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_csrf.py'`.

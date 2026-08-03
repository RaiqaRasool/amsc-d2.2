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
- GET requests remain unaffected.

## Failure Behavior

Missing, changed, or expired tokens return the user to the home page with a
friendly error. The requested action is not performed.

## Key Components

- `csrf.py`: token generation and constant-time comparison
- `app.py`: template token injection and POST request guard
- `templates/`: hidden tokens on every POST form

## Verification

- Run `python3 -m unittest test_csrf.py`.

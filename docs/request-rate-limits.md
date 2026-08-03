# Request Rate Limits

## Purpose

Prevent rapid request bursts from creating excessive MYA, Globus, or web
service work while preserving the application's asynchronous batch workflow.

## Expected Behavior

- MYA submissions allow 5 per minute and 30 per hour per Globus identity.
- Collection searches allow 20 per minute per Globus identity.
- Collection browsing allows 60 per minute per Globus identity.
- Login starts allow 10 per minute per direct client IP address.
- Limits use persistent sliding windows stored in a dedicated SQLite database,
  isolating request-flood writes from the job queue.
- Jobs-dashboard polling is not rate-limited.
- All values are configurable through the corresponding environment variables.

## Failure Behavior

Rejected requests perform no route work and return HTTP 429 with a friendly
page and a `Retry-After` header containing the number of seconds to wait.

## Deployment Boundary

The application does not trust `X-Forwarded-For` or Cloudflare headers yet.
Configure trusted proxy handling when the production proxy topology is known;
until then, login rate limits use Flask's direct `remote_addr` value.

## Key Components

- `rate_limits.py`: persistent atomic sliding-window enforcement
- `app.py`: endpoint identities, actions, and HTTP 429 responses
- `templates/429.html`: user-facing rejection page

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_rate_limits.py'`.

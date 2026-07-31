# MYA Query Limits

## Purpose

Protect the web service and MYA archive from accidentally or deliberately
oversized queries before work enters the background queue.

## Expected Behavior

- The web service rejects request bodies larger than 64 KiB.
- A query may contain at most 100 PVs, each at most 256 characters long.
- MySampler accepts at most 100,000 samples.
- MyStats accepts at most 10,000 bins.
- Interval and MyStats time windows may span at most 31 days.
- Channel names and channel search patterns may contain at most 256 characters.
- Browser constraints provide early feedback, but backend validation is
  authoritative and returns HTTP 400 for invalid query parameters.

These initial limits are application safety defaults. Revisit them with the
MYA archive developers after measuring representative query cost and capacity.

## Failure Behavior

Rejected queries are not queued and do not contact MYA. Oversized request
bodies receive Flask's HTTP 413 response.

## Key Components

- `app.py`: request-size enforcement and query admission
- `query_validation.py`: backend query limits
- `templates/index.html`: matching browser constraints

## Verification

- Run `python -m unittest test_query_validation.py`.

# MYA Backend Configuration

## Purpose

Select one MyQuery endpoint and MYA deployment for all archive queries so the
application can move between sandbox and approved production environments
without changing query code.

## Expected Behavior

- `MYQUERY_PROTOCOL` and `MYQUERY_SERVER` configure the
  `jlab_archiver_client` endpoint when the query module loads.
- `MYA_DEPLOYMENT` is passed to MySampler, Interval, MyStats, Point, and Channel
  queries.
- Submitted jobs cannot override the application deployment.
- The client does not fall back to another deployment when the configured
  deployment is unavailable.

## Failure Behavior

- An unreachable MyQuery endpoint or unavailable deployment causes the query
  job to fail through the existing worker error path.
- A failed sandbox query never retries against History or Ops.

## Key Components

- `config.py`: environment-backed MYA connection settings
- `mya_query.py`: client initialization and query construction
- `.env.example`: sandbox-oriented example values

## Verification

- `python3 -m unittest tests.test_mya_query_config`

# MYA Backend Configuration

## Purpose

Select one MyQuery endpoint and MYA deployment for all archive queries so the
application can move between sandbox and approved production environments
without changing query code.

## Expected Behavior

- Both standalone Compose files define the optional MYA/MyQuery demo archive
  under the `demo` profile and use fixtures colocated in `docker/demo-archive/`.
- MYA and MyQuery have no published host ports and communicate with application
  services on the internal Compose network.
- `MYQUERY_SERVER` is required by Compose. It is `myquery:8080` for the demo
  profile or the configured external endpoint when the profile is disabled.
- `MYQUERY_PROTOCOL` and `MYQUERY_SERVER` configure the
  `jlab_archiver_client` endpoint when the query module loads.
- `MYA_DEPLOYMENT` is passed to MySampler, Interval, MyStats, Point, and Channel
  queries.
- Submitted jobs cannot override the application deployment.
- The client does not fall back to another deployment when the configured
  deployment is unavailable.

## Failure Behavior

- An unset `MYQUERY_SERVER` stops Compose configuration before startup.
- An unreachable MyQuery endpoint or unavailable deployment causes the query
  job to fail through the existing worker error path.
- A failed sandbox query never retries against History or Ops.

## Key Components

- `config.py`: environment-backed MYA connection settings
- `mya_query.py`: client initialization and query construction
- `docker-compose.yml` and `docker-compose.production.yml`: independent runtime
  definitions and optional demo archive services
- `docker/demo-archive/`: demo SQL and MyQuery configuration
- `.env.example`: sandbox-oriented example values

## Verification

- `python3 -m unittest tests.test_mya_query_config`
- `podman compose --profile demo config`
- `podman compose -f docker-compose.production.yml --profile demo config`

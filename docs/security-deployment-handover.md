# Security and Deployment Handover

## Purpose

This document summarizes the application security controls implemented before
deployment and identifies the decisions that remain with MYA archive and
infrastructure owners. It is intended for the final review with Brad, Kelvin,
and the MYA archive developers.

Verified against commit `c6bff4f` with:

```bash
python3 -m unittest discover -s tests
```

Result: 35 tests passed.

## Implemented Application Controls

### MYA Query Admission

| Control | Default | Configuration |
| --- | ---: | --- |
| HTTP request body | 64 KiB | Flask `MAX_CONTENT_LENGTH` |
| PVs per query | 100 | Application constant |
| Characters per PV/channel/pattern | 256 | Application constant |
| MySampler samples | 100,000 | Application constant |
| MyStats bins | 10,000 | Application constant |
| Interval/MyStats time range | 31 days | Application constant |
| Pending jobs per user | 10 | `MAX_PENDING_JOBS_PER_USER` |
| Pending jobs globally | 500 | `MAX_PENDING_JOBS_GLOBAL` |

Only `queued` and `query_running` jobs consume queue capacity. Capacity checks
and job insertion use one SQLite write transaction. Browser validation provides
early feedback, but the backend is authoritative.

### Request Rate Limits

| Request | Default | Scope | Configuration |
| --- | ---: | --- | --- |
| MYA submissions | 5/minute and 30/hour | Globus identity | `MYA_SUBMISSIONS_PER_MINUTE`, `MYA_SUBMISSIONS_PER_HOUR` |
| Collection searches | 20/minute | Globus identity | `COLLECTION_SEARCHES_PER_MINUTE` |
| Collection browsing | 60/minute | Globus identity | `COLLECTION_BROWSES_PER_MINUTE` |
| Login starts | 10/minute | Direct client IP | `LOGIN_ATTEMPTS_PER_MINUTE` |

Rejected requests return HTTP 429 with `Retry-After`. Events use a dedicated
SQLite database so request floods do not lock the job queue. The jobs-dashboard
poll is not rate-limited.

### Worker and Storage Bounds

| Control | Default | Configuration |
| --- | ---: | --- |
| MYA retrieval plus local export timeout | 1 hour | `WORKER_QUERY_TIMEOUT_SECONDS=3600` |
| Maximum generated export | 1 GiB | `MAX_MYA_OUTPUT_BYTES=1073741824` |
| Terminal job/export retention | 30 days | `JOB_RETENTION_DAYS=30` |
| Retention cleanup interval | 1 hour | `CLEANUP_INTERVAL_SECONDS=3600` |

Queries and exports run in an isolated process group. Timeout stops descendant
processes. Exports write through a byte limiter to a temporary file and become
visible only after an atomic rename. Cleanup deletes only generated
`mya-<uuid>.csv` and `mya-<uuid>.json` files; active MYA and Globus work is not
removed.

The one-hour timeout applies to MYA retrieval and local export creation only.
Globus transfers are asynchronous and retain Globus's progress-aware retry and
deadline behavior.

### Non-MYA Input Validation

| Input | Backend rule |
| --- | --- |
| Collection search | Maximum 128 characters; no control characters |
| Collection ID | Canonical 36-character UUID |
| Destination/browse path | Maximum 1,024 UTF-8 bytes; no control characters |
| Transfer label | Maximum 128 characters after the 20-character application prefix |
| User-entered transfer label | Frontend maximum 108 characters |
| OAuth authorization code | Maximum 2,048 characters |
| OAuth state | Maximum 128 characters, session-bound, one-time, and expiring |

Validation preserves valid Unicode, spaces, punctuation, and path separators.
The application validates according to field format rather than trying to
strip generic “injection characters.” Stored destinations are revalidated when
a transfer job is queued.

### Authentication and Web Security

- Globus access and refresh tokens remain in server-side SDK-managed SQLite
  storage; browser sessions contain only an opaque namespace reference.
- Logout permanently retires the reference. Unused tokens are revoked and
  deleted immediately; credentials needed by asynchronous transfers remain
  until those jobs become terminal, then the monitor revokes and deletes them.
- OAuth state digests persist in dedicated SQLite for restart/multi-worker
  support. Raw values are bound to the initiating signed session, expire after
  10 minutes (`OAUTH_STATE_TTL_SECONDS=600`), and are atomically consumed once.
- Every POST form uses CSRF validation. Logout is POST-only. Query draft storage
  cannot overwrite CSRF tokens.
- Unhandled worker and HTTP exceptions are logged server-side. Users receive
  bounded job errors or a generic HTTP 500 page without tracebacks.
- Job APIs isolate records by authenticated Globus identity and omit token
  references from responses.

## Injection and Dangerous-Operation Review

- No shell, subprocess, `eval`, or `exec` execution path is used for web input.
- MYA requests use Python client query objects rather than shell commands.
- SQLite values use bound parameters. The limited dynamic SQL fragments are
  constructed from application-owned field/status names, not request values.
- Jinja templates auto-escape displayed values.
- There is no file-upload endpoint.
- There is no web endpoint for reboot, service control, or operating-system
  command execution. These capabilities should not be added to the portal.

## Application Databases

| Database | Purpose |
| --- | --- |
| `instance/mya-transfer-jobs.sqlite3` | Jobs, queue admission, deferred token cleanup |
| `instance/request-rate-limits.sqlite3` | Short-lived rate-limit events |
| `instance/oauth-states.sqlite3` | Short-lived hashed OAuth states |
| `instance/globus-tokens.sqlite3` | SDK-managed OAuth access/refresh tokens |

Separating application databases reduces lock contention and credential
exposure boundaries. Adding more application databases does not protect the MYA
archive from DDoS; archive replicas, archive-side limits, and permitted worker
concurrency require an infrastructure/MYA decision.

## Decisions for MYA Archive Developers

- Confirm that 100 PVs, 100,000 samples, 10,000 bins, and 31-day ranges are
  acceptable for each query type.
- Confirm whether a one-hour query/export deadline and 1 GiB output ceiling
  match representative workloads.
- Establish supported concurrent MYA queries. Application worker concurrency
  should remain one until this is confirmed.
- Confirm archive-side throttling, timeouts, overload responses, and monitoring.
- Decide whether MYA replicas exist or are required and how traffic should be
  routed or failed over.
- Identify who receives application/MYA overload and failed-query alerts.

## Deployment Actions for Brad and Kelvin

- [ ] Choose the production VM domain.
- [ ] Configure DNS, HTTPS, and the production Globus callback URI.
- [ ] Enable Cloudflare and agree on WAF/edge rate-limit rules that complement
      rather than conflict with application limits.
- [ ] Document the trusted proxy chain before enabling forwarded-client-IP
      handling. Until then, login limiting uses Flask's direct `remote_addr`.
- [ ] Put the VM on the required VLAN and confirm MYA/Globus network routes.
- [ ] Set `FLASK_DEBUG=0` and run a production WSGI server.
- [ ] Enable secure session-cookie deployment settings: `Secure`, `HttpOnly`,
      and an approved `SameSite` policy.
- [ ] Store application/Globus secrets outside source control with restrictive
      filesystem permissions and a rotation procedure.
- [ ] Provide persistent storage and capacity alerts for databases and exports;
      account for 1 GiB per in-retention export.
- [ ] Decide backup/restore policy for jobs and whether token databases should
      be backed up or re-created through login.
- [ ] Configure centralized logs, health checks, patching, monitoring, and alert
      ownership.
- [ ] Perform a production-mode test of generic 400/429/500 pages, OAuth login,
      query execution, Globus transfer, logout, and cleanup.

## Meeting Exit Criteria

- [ ] MYA developers approve or revise query and concurrency limits.
- [ ] Replica/load-distribution responsibility is documented.
- [ ] Domain, VLAN, Cloudflare, certificates, and callback ownership are named.
- [ ] Monitoring, patching, backup, incident response, and alert recipients are
      named.
- [ ] Any revised application values are recorded in the applicable deployment
      configuration or application constants.
- [ ] Brad, Kelvin, the developer, and MYA owners agree the application is ready
      for production deployment.

## Detailed Contracts

- [MYA query limits](mya-query-limits.md)
- [Queue admission](queue-admission.md)
- [Request rate limits](request-rate-limits.md)
- [Worker execution safety](worker-execution-safety.md)
- [Data retention](data-retention.md)
- [Web input validation](web-input-validation.md)
- [CSRF protection](csrf-protection.md)
- [OAuth state storage](oauth-state-storage.md)
- [Authentication design](auth-plan.md)
- [Logout token cleanup](logout-token-cleanup.md)
- [Web error handling](web-error-handling.md)


mya-amsc == VM name
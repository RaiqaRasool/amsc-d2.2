# Transfer Existing Output

## Purpose

Transfer a retained query result without rerunning MYA.

## Main Flow

1. History offers Transfer… for a finished query whose local output is available.
2. The main page shows the existing filename and byte size, hides query inputs,
   and presents the current destination browser with a Cancel link.
3. The user selects and validates a destination, then presses Transfer file.
4. A separate queued transfer entry retains an internal original-query reference and its
   own destination, authorization reference, status, error, and Globus task link.
   The worker submits the existing source file without executing MYA.

## Expected Behavior

- History distinguishes Submitted job IDs from Globus transfer IDs. IDs are abbreviated
  with full values in tooltips; View transfer opens the Globus task. File links
  explicitly browse source/destination folders. Destinations show the collection
  and folder rather than repeating the exported filename. Long names and paths
  are ellipsized with full-value tooltips. Update times show New York local date,
  time, timezone abbreviation and UTC offset; raw timestamps remain unchanged.
- History actions use icons with tooltips and accessible names for View query
  parameters, Run query again, Transfer, Retry transfer, and Transfer file again.
  Viewing and rerunning a transfer row use the original query, not query_type=transfer.
- New transfer attempts store an allowlisted snapshot of source query type and
  inputs in query_params.source_query. Credentials, destinations, transfer labels,
  and task state are excluded. Further attempts copy that snapshot, so history
  deletion or retention of the original query does not remove these inputs.
- Older attempts without snapshots resolve the original query by owner-scoped
  parent lookup when possible. Otherwise details explain that inputs are
  unavailable and the rerun icon is omitted. Existing file transfer still works.
- Successful transfer attempts with retained outputs offer Transfer file again.
  Failed attempts offer Retry transfer. Both open destination review and require
  explicit submission using current authorization; neither re-executes MYA.

- Owner authentication and CSRF are required. Other users cannot access or transfer
  a query result. File access uses the same restricted export opener as preview.
- The current validated collection/path proof must match the submitted form.
  Old query destinations and tokens are never copied into a new attempt.
- Existing login and collection-consent redirects preserve transfer mode. No
  automatic submission occurs after login; the user still confirms the transfer.
- Attempts use the existing submission rate limits, queue limits, token retirement
  checks, transfer submission, status refresh, and Globus task links.
- Query-only results and finished query-and-transfer results can be transferred.
  Transfer attempt rows retain the original-query relationship internally and
  expose source-query inspection and rerun actions when those inputs are available.
  Failed attempts offer Retry transfer… when the export remains available,
  including legacy query_failed attempts processed by an older worker. Retry
  returns to destination review and creates a new attempt with current credentials.
- There is no automatic retry: another attempt is an explicit user action and
  may create another Globus transfer. The original query record is unchanged.
- Shared exports are retained while another job references them. Original query
  records may expire before later attempts; saved query snapshots remain usable.
- Preview displays the source query type and inputs for transfer-only rows, using
  the same snapshot/fallback resolution as history details and rerun.

## Failure Behavior

- Missing outputs offer Run again; unfinished jobs and transfer-only job sources
  are rejected unless the transfer-only job is a failed attempt being retried. The worker also checks file availability before submission.
- Permission, authorization, and submission failures use the existing transfer
  error/status handling. Successful folder browsing does not guarantee later
  Globus permission or availability.
- Queue, input, and stale-validation errors do not create an attempt.

## Key Components

- `app.py`, `templates/index.html`, `templates/_jobs.html`: owner-scoped review and submission
- `worker.py`, `job_execution.py`: query-free transfer dispatch and submission
- `jobs.py`, `retention.py`: separate attempts and shared-export retention

## Verification

- `tests/test_transfer_query_snapshot.py` covers snapshot survival after deletion,
  owner-scoped legacy fallback, secret exclusion, original-query prefill/preview,
  and successful retransfer with current authorization.
- `tests/test_existing_transfer.py` covers ownership, validation, separate history,
  current authorization, retention, and worker dispatch without MYA execution.
- Real Globus submission requires an authenticated local or deployed environment;
  automated checks mock Globus and do not transfer user files.

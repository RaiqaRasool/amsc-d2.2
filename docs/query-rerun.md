# Run Again from History

## Behavior

- History rows with available query inputs link to the query form using their
  historical job ID. Transfer-only rows use a saved source-query snapshot, or
  owner-scoped original-job fallback for legacy attempts. Missing legacy context
  omits the rerun action and shows an explanation on query inspection.
- Only the logged-in job owner can prefill that request. Unauthenticated requests
  return 401; unknown or other-owner jobs return 404.
- Opening the link performs no query, transfer, or job creation. Failed and
  completed requests can both be reviewed and edited.
- Only supported query fields are copied. Historical destinations, credentials,
  task IDs, and transfer labels are not reused. The transfer label is cleared.
- Prefilled query values override saved browser draft values and activate the
  matching query tab. Historical single-channel Interval jobs populate the
  unified PV field. Explicitly zoned dates are converted to New York local time
  for the timezone-less form controls; fractional seconds remain editable.
- A blue review notice with a bold heading explains that nothing has been
  submitted and current destination/authorization apply if transfer is chosen.
- A labeled × button dismisses only the reminder. It does not change query
  values or the saved draft, and there is no automatic hide timer.
- Normal form submission creates a new job using current validation, CSRF,
  limits, authorization, and explicit Query only/Query and transfer choice.
- Unsupported or malformed historical parameters show a friendly message.
- View query parameters opens an owner-scoped, private/no-store detail page,
  without submitting work. It remains available after file deletion when the job
  and source query snapshot still exist. Job deletion is a separate action.

## Components and Verification

- `query_prefill.py`: allowlisted query form mapping
- `app.py`: owner-scoped historical job lookup
- `templates/index.html`, `templates/_jobs.html`: prefill, review notice and link
- Tests cover all five query mappings, historical Interval fields, timezone-aware
  form dates, no credential/destination copying, ownership, and no submission.

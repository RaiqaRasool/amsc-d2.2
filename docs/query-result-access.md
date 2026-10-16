# Query Result Preview and Download

## Purpose

Let users inspect completed query results before downloading or moving the
complete export through Globus. Retrying/retriggering requests is outside scope.

## Main Flow

1. The worker atomically publishes a completed CSV or JSON export and records
   its source path on the job.
2. The history table offers Preview, Download, and the existing Globus link.
3. Preview opens a bounded on-site view in a new tab. Download streams the full
   file as an attachment; it does not read the full export into Python memory.

## Expected Behavior

- Both URLs require a logged-in session and retrieve the job using its owner
  identity. Knowing a job ID or filename does not grant access to another user.
- Fixed job-ID routes resolve only canonical generated `mya-<uuid>.csv/json`
  filenames inside the configured local export directory. No URL filesystem
  path is accepted. Symlinks and non-regular files are refused.
- Only published exports are offered. Queued/running/failed queries cannot
  retrieve partial data; jobs with completed queries can access their result
  even if the subsequent Globus transfer fails.
- CSV previews read at most 256 KiB plus one detection byte and show at most
  100 rows, 50 columns, and 500 characters per cell. Truncation is labeled.
- CSV parsing understands quoted fields and multiline records. A partial final
  record at the byte boundary is omitted conservatively. Invalid or oversized
  records stop preview parsing without expanding the read budget.
- JSON exports use an escaped, bounded text preview; partial JSON is not parsed
  as a complete document. No plotting or whole-file browser loading is included.
- New exports serialize event timestamps in America/New_York with explicit UTC
  offsets. Preview only displays file contents, without converting times. Existing
  exports remain unchanged; the preview explains that older files may lack offsets.
- Preview shows filename, byte size, query type/parameters, and an explicit
  partial-preview explanation. All result text is escaped by templates.
- Full downloads preserve their generated filename and stream from an open,
  validated file descriptor. HTTP range/resume support is not part of this step.
- Responses are private/no-store. Download responses disable content sniffing.
- Existing Globus links remain available for full-file movement. No transfer
  action is initiated by previewing or downloading.

## Failure and Retention

- Unauthenticated requests return 401. Unknown and other-owner jobs return 404.
- Missing, expired, unrecognized, symlinked, or unfinished exports return an
  unavailable message without exposing local paths.
- Existing retention rules are unchanged. Preview/download do not extend a
  job's lifetime or create copies. Deleted jobs no longer authorize access.
  An already-open response can finish if cleanup unlinks the file afterward.

## Key Components

- `result_preview.py`: validated file opening and bounded preview parsing
- `app.py`: authenticated owner-scoped routes and history display links
- `templates/_jobs.html`, `templates/result_preview.html`: result actions/view
- `retention.py`: reused generated-filename rules and existing cleanup behavior

## Verification

- Focused parser checks cover byte, row, column, and cell limits, quoted CSVs,
  multiline values, JSON bounds, and partial records.
- Isolated Flask checks cover ownership, authentication, escaped content,
  full-file download, history actions, lifecycle states, deleted files/jobs,
  path restrictions, and symlink rejection.
- Run `.venv/bin/python -m unittest discover -s tests -p 'test_result*.py'`.

Transfer-only previews show the source query type and allowlisted inputs from
a saved snapshot, falling back to the owner’s original job for older attempts.
Missing legacy context is explained instead of showing a parent ID as query parameters.

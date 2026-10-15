# Job Deletion

## Expected Behavior

- A trash icon appears for finished jobs; deletion asks for confirmation naming
  the job and explaining local history/file deletion and unchanged Globus data.
- Only the authenticated owner can delete, using a CSRF-protected POST.
- Queued/running/submitted transfers and query-complete jobs awaiting transfer
  cannot be deleted. Eligibility is checked again under a database write lock.
- Deleting removes the local job record. Its generated CSV/JSON is removed only
  when no other job references the same source path. Missing files are tolerated.
- Filesystem failures preserve the job record and show an error. Deletion is
  permanent. No Globus cancellation, remote-file deletion, or task removal occurs.
- References to a deleted original query may remain in later transfer records.
- History refresh and deletion preserve query form inputs. Hiding is not supported;
  any unused hidden column from earlier local development is ignored.
- Automatic retention continues to handle old finished jobs.

## Key Components

- `retention.py`: owner/status/shared-file checks and local deletion
- `app.py`, `templates/_jobs.html`, `templates/index.html`: delete action and confirmation

## Verification

- `tests/test_job_deletion.py`: ownership/CSRF, active-job guards, shared files,
  missing files, filesystem failures, and deletion of the last reference.

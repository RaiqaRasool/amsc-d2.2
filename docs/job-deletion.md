# Job Deletion

## Expected Behavior

- Finished jobs have selection checkboxes and Delete selected (N). Select all
  applies only to deletable rows currently shown, never undisplayed history.
  Active rows are disabled. Selection survives status refreshes for rows still
  shown and eligible; new rows are not automatically selected.
- Bulk deletion confirms the selected count and local/Globus scope. The server
  accepts at most 20 IDs (the history page size), verifies ownership of all
  supplied IDs before changes, then rechecks each job's state under a write lock.
  No blanket delete-all operation exists.
- Bulk results report deleted IDs and individual failures; a failed item does
  not roll back successful deletions. Shared files survive until the last
  referencing job is removed. Requests and UI prevent duplicate in-flight clicks.


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

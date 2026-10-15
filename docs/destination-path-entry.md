# Inline Destination Manager

## Purpose

Search collections and browse/select a destination folder in one panel on the
main query page, including when reviewing a historical query.

## Behavior

- Collection search returns up to ten choices in an inline dropdown. Choosing
  a collection enables the path field but does not validate/select its root.
- Enter in the path field browses and selects that folder through one authenticated,
  CSRF-protected POST. It never submits the MYA query. There is no separate
  Use this folder action. The same request obtains metadata and folder entries.
- The persistent folder box starts with a prompt and displays subfolders among
  the first 200 returned entries. A notice identifies truncated listings.
- Parent and refresh icons perform the same validated navigation. Clicking a
  subfolder browses/selects it. All icons have accessible names and tooltips.
- The reset icon above the collection controls clears search, dropdown choices,
  path, folder contents, and the server/client validated selection. Query values
  are retained. Path controls remain disabled until a collection is chosen.
- Editing a path or changing collection invalidates client-side selection proof
  and disables Query & Transfer. Loading/failure states keep it disabled. Users
  must successfully browse again even if they type back the previous path.
- Successful browsing stores collection, path, and an opaque selection ID in the
  signed session, returning matching values for hidden transfer form fields.
  These fields are excluded from browser query drafts and historical prefill.
- Transfer submission checks the exact collection/path and selection ID against
  the session, then uses normal validation/current authorization. It does not
  repeat directory listing. Stale or modified selections are rejected before
  job creation; this also handles conflicting selection changes in another tab.
- A previously validated session selection may be reused on page reload. Older
  sessions without a selection ID require Enter again. Reauthentication clears
  the previous validation ID; resumed browsing must obtain a new one.
- Relative paths receive a leading slash. Unicode/spaces are preserved; backend
  path-byte and collection-ID validation remains authoritative.
- JSON search and browse endpoints have no inline flag or full-page fallback.
  The read-only GET listing endpoint does not select a transfer destination;
  selection requires the CSRF-protected POST.

## Authorization and Failures

- Current authorization is used. Historical destination credentials are not reused.
- Inline authentication/consent failures redirect automatically to login, keeping
  the same user's destination/search draft in browser session storage. The
  callback returns to the main page and discards obsolete picker URLs.
- On return, the draft is restored and validated again. Failure after resume
  shows an error instead of causing an automatic redirect loop. Ordinary search
  errors do not trigger authentication unless the API reports an auth failure.
- Failed browsing never replaces the server's last successful selection. The
  browser clears its proof, so that stale selection cannot be silently submitted.
- Superseded browse requests are aborted and stale responses ignored. A cookie
  race cannot silently queue a different destination: mismatching selection IDs
  fail the transfer submission check.
- Folder access is not a promise of future write permission. Transfer failures
  continue through existing submission/monitoring handling. No folder creation
  or live autocomplete is implemented.

## Verification

- `tests/test_destination_paths.py` covers inline search/listing, limits,
  validation, CSRF, permission/consent failures, unchanged state on failure,
  selection proof, no re-listing on transfer, reset, and legacy callback URLs.
- Isolated headless-browser checks with mocked HTTP responses cover Enter-only
  selection, editing/failure guards, navigation icons, consent resume, reset,
  and the persistent folder panel. The rendered panel was visually inspected.
- No real Globus collections were queried or modified by these tests.
- [Globus file operations](https://docs.globus.org/api/transfer/file_operations/#list_directory)
  documents listing and filesystem/permission failures.

The destination browser uses compact Collection, Results, and Path rows above a shared icon toolbar and flat folder list. The current path appears in the address field; the folder pane does not repeat it. Collection identifiers remain option values while visible results show collection names.

A session-restored collection is labeled Current collection. A successful search replaces it with actual matches only and clears browser validation until a result and path are selected again.

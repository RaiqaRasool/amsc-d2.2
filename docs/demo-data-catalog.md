# Demo Data Catalog

## Purpose

Help authenticated demo users discover the PVs and stored event dates already
available, without updating frontend examples on every import.

## Main Flow

1. The demo SQL import CLI completes the bundle import.
2. `refresh_catalog.py` reads the local demo database, including existing
   fixtures, and atomically publishes `demo-catalog/demo-catalog.csv`.
3. The query page's PV help icons open an authenticated on-site catalog table
   in a new tab. Users can search by PV name and optionally download the CSV.
   Future imports update the same backing file without frontend edits.

## Expected Behavior

- The database, not SQL filenames or source CSVs, determines the inventory.
- Include channels hosted on local demo host `mya`, with exact PV name,
  readable MYA datatype (for example `DBR_DOUBLE`), value shape (`scalar` or
  `array (11 elements)`), first/last stored event, and stored event count.
  Empty channels have blank dates and zero events. There is no refresh-time column.
- Event dates use America/New_York with explicit UTC offsets.
  Fractional event dates are displayed to microsecond precision.
- First/last events do not establish continuous coverage or original sampled
  ranges. Values can carry forward beyond the last stored event and across gaps.
- The successful import CLI refreshes automatically, including identical reruns.
  Programmatic `import_bundle()` callers explicitly invoke `refresh_catalog()`.
- The standalone refresh CLI supports manual database changes or catalog recovery.
- PV help icons are available for all five query types, including Point’s
  Channel and Channel’s Channel pattern fields.
- The query page has no separate top catalog link; text below each PV box
  directs users to its ? help icon. PV help icons link to this catalog in the `docker` deployment; other deployments
  retain the external Hall-D reference spreadsheet. Demo help does not suggest
  PVs from that unrelated reference list.
- CSV conversion/import currently supports numeric scalars only. The database
  catalog also describes pre-existing array PVs, including the 11-element
  `channel102` fixture. Showing array shape does not imply array CSV import support.
- Datatype names describe database metadata, which is synthetic for imported CSV
  channels; they do not recover the source archive's original types.
- Only logged-in users in the `docker` deployment can view or download the catalog.
  `/demo-catalog` renders the current CSV as an escaped HTML table with
  case-insensitive PV-name search. `/demo-catalog.csv` remains an optional download.
  Both use a fixed operator-configured path, with private/no-store caching.
- Development reads the host file through the existing source bind mount.
  Production mounts the host `demo-catalog/` directory read-only into the web
  container, so atomic replacement becomes visible without rebuilding.
- Generated catalogs are excluded from Git and the Docker build context.

- Each PV has a copy icon for its exact name and a checkbox for bulk selection.
  Copy selected PVs copies only checked rows as comma-separated names, shows
  the selected count, and stays disabled until a row is checked. Selection
  works with or without filtering; a new search clears it. There is no select-all
  control. Clipboard failures show a manual-copy message; success is announced
  through an accessible status message.

## Failure Behavior

- Missing catalog returns a descriptive 404; other deployments return 404.
  Unauthenticated viewing and download requests redirect to the home page.
- Query/write errors preserve the previous catalog. Incomplete ranges or missing
  channel tables fail refresh rather than silently omitting PVs.
- Refresh failure after import reports that data import completed and the catalog
  needs refreshing; database imports are not rolled back.
- A partially failed bundle import does not auto-refresh. Run the refresh command
  to reflect any channels already committed before that failure.
- Refresh while archive writers are idle. Multi-query inventory collection is
  not a globally atomic database snapshot; the CSV publication itself is atomic.
- Operators must refresh after changing/recreating a database outside the import
  CLI; the web application does not independently detect a stale file.

## Key Components

- `tools/demo_archive/refresh_catalog.py`: database inventory and atomic CSV output
- `tools/demo_archive/import_sql.py`: refresh following successful CLI imports
- `app.py`, `templates/index.html`: authenticated download and discovery link
- `config.py`: `DEMO_CATALOG_PATH` override for the web reader
- `docker-compose.production.yml`: shared catalog directory

## Verification

- Tool tests cover database-derived inventory, encoded names, empty archives,
  precise timezone dates, atomic failure handling, and import CLI refresh.
- Flask test covers login, demo gating, missing file, updates, download headers,
  the query-page link, and removal of outdated fixture-only messages.
- Live checks against pinned `jeffersonlab/mycontainer:2.0.0` cover real imported
  event dates/counts and inclusion of the existing `channel100` fixture.

# Demo Archive CSV Converter

Convert approved MySampler CSV data into per-PV SQL for the demo MYA database.
The converter uses synthetic metadata. A separate import command explicitly
loads generated bundles into the demo database.

The [behavioral contract](../../docs/demo-csv-import.md) records the agreed rules.

## Generate a SQL Bundle

From `globus-web-prototype/`, use the standard-library CLI:

```bash
python3 tools/demo_archive/csv_to_sql.py ../cebaf_linac_fe_2024/data-2024-05-09.csv --output-dir /tmp/demo-mya-may09
```

The single-file example is optional. To convert all CSVs in a folder together,
use the folder command below. Each output bundle has `<channel_id>_<PV_name>.sql` files,
`channels.json`, and `summary.json` with source name and per-PV event counts.
Source CSVs are read row by row, with memory proportional to the column count;
the converter keeps one output file open per PV. It does not query a database.

For the next CSV, reuse the previous mapping and choose a new output directory:

```bash
python3 tools/demo_archive/csv_to_sql.py ../cebaf_linac_fe_2024/data-2024-05-14.csv --mapping /tmp/demo-mya-may09/channels.json --output-dir /tmp/demo-mya-may14
```

- Each input CSV must have nondecreasing timestamps; equal encoded timestamps
  with identical values are skipped, and conflicts fail.
  Cross-file/database conflict checking is performed by the import command.
- Output is staged in a temporary sibling directory and published only after
  validation completes. Existing output directories are refused.
- Names use UTF-8 hex expressions in SQL and readable ID/PV filenames. Duplicate,
  empty, control-character, and reserved fixture PV headers are rejected.
- SQL filenames include the ID and PV name, for example `1002_INX2L07_gDsRt.sql`.
  Unsafe characters are percent-encoded; labels are capped at 180 characters
  to fit filesystem limits. IDs preserve uniqueness. Exact PV names stay in
  the mapping/database and are what users search for. The importer also accepts
  earlier `<channel_id>_channel.sql` filenames.
- Numeric comparisons use Decimal so equivalent representations deduplicate.
  Storage follows the fixtures: type 6, size 1, and SQL FLOAT. FLOAT rounds
  values to single precision; nonfinite, overflow, and underflow-to-zero input
  is rejected. No original PV datatype or precision is claimed.
- Channel metadata uses demo host `mya`, zero deadband, and the fixtures' required
  flags/backup convention; optional clip/IOC fields remain NULL.
- [jmyapi EventCode](https://github.com/JeffersonLab/jmyapi/blob/7f2301e2e9acfee4853cfd27f689e7d1662d22ca/src/main/java/org/jlab/mya/event/EventCode.java)
  defines code 0 as a normal update. The
  [numeric reader](https://github.com/JeffersonLab/jmyapi/blob/7f2301e2e9acfee4853cfd27f689e7d1662d22ca/src/main/java/org/jlab/mya/nexus/QueryService.java)
  uses JDBC getFloat, matching fixture storage.
- Generated SQL uses plain INSERT/CREATE statements for initial loading.
  Use the importer below for later bundles and reruns; do not pipe raw SQL
  files over existing channels.

## Convert a Folder into One Combined Bundle

```bash
python3 tools/demo_archive/csv_to_sql.py ../cebaf_linac_fe_2024 --output-dir tools/demo_archive/generated/cebaf_linac_fe_2024
```

- Finds `.csv` files (case-insensitive) directly inside the folder, without
  recursing into subfolders. Files are streamed sequentially, using a shared
  channel mapping; they are not processed in parallel.
- Produces one final SQL file per PV across all input files. Shared PVs use the
  same channel ID and table; different timestamps are combined in time order.
  Columns may differ between CSVs. Each file's first measurement is retained.
- Sorts runs by their actual first timestamp, not filename. This initial folder
  mode rejects overlapping or touching input time ranges, even if their data
  might be identical, rather than silently reconciling sampled histories.
  Separate-bundle imports check conflicts between retained events only; they
  cannot detect conflicting sampled values that were dropped by deduplication.
- Rejects invalid input without publishing the final bundle. Intermediate
  per-file bundles are temporary and cleaned up. Disk usage includes these
  intermediate SQL files plus the final bundle; source data is never modified.
- Reuse `--mapping PATH/channels.json` when adding another batch later. The
  output directory must be new. Generated bundles under this tool's `generated/`
  directory are ignored by Git.
- `summary.json` records source files, their ranges/counts, and combined event
  counts. The existing importer accepts this combined bundle unchanged.

## Import a Bundle

Run from `globus-web-prototype/` after starting the demo MYA service:

```bash
python3 tools/demo_archive/import_sql.py /tmp/demo-mya-may09
python3 tools/demo_archive/import_sql.py /tmp/demo-mya-may14
```

Use `--runtime podman` for Podman, or
`--compose-file docker-compose.production.yml` for the production Compose file.
The importer targets only the selected Compose project's `mya` service and uses
its `MYSQL_ROOT_PASSWORD` environment variable inside the container. It does not
publish database ports, expose credentials in arguments, or start services.

- Validate every SQL file against this tool's schema and numeric event format
  before accessing the database; arbitrary SQL is not executed. Regenerate
  bundles produced before the importer was added, because their header differs.
- All listed SQL files must match `summary.json` and `channels.json`. Retain
  these files together. Deleting a file from a bundle makes it incomplete;
  deleting a file never removes previously imported database data.
- New channels get synthetic metadata and InnoDB event tables. Existing channels
  must match ID, exact name, synthetic metadata, and expected table structure.
  The pinned image uses latin1 PV names of at most 255 characters; names outside
  that supported range are rejected before import.
- Incoming values are staged as FLOAT, so rerun comparisons use database
  storage precision. Matching timestamp/code/value events are skipped; conflicts
  fail before inserting any events for that channel. Existing values are never
  overwritten. Events at new timestamps are inserted without further deduplication
  across file boundaries, retaining each file's first measurement.
- A database named lock serializes this tool's import sessions. Other database
  writers must be stopped while importing; they do not honor that advisory lock.
- The import is not atomic across channels. Completed channels remain committed
  if a later channel fails. Metadata/table creation uses DDL and may remain on a
  failing new channel. Errors identify the failing and completed channels.
  After resolving a conflict, rerun the bundle to skip already inserted events.
- Guard errors name `identity_ok` (channel collision or incompatible metadata),
  `structure_ok` (missing/orphan/incompatible table), `events_ok` (conflicting
  existing event), or `lock_ok` (another import is running).
- Tested against `jeffersonlab/mycontainer:2.0.0`, which runs MariaDB 5.5.
  Strict-mode NOT NULL guards are used because this version ignores CHECK constraints.

## Verification

Run from `globus-web-prototype/`:

```bash
.venv/bin/python -m unittest discover -s tools/demo_archive/tests -p "test_*.py"
```

The database integration test is opt-in. Set `DEMO_IMPORT_TEST_CONTAINER` to the
name of a fresh disposable `mya-import-test-*` container running the pinned
image, then run `test_import_sql_integration.py`. The test writes channel ID
1000 and must never target a shared or application database.

## MyQuery End-to-End Check

`tools/demo_archive/tests/test_myquery_integration.py` reads only five rows and two PV
columns from `cebaf_linac_fe_2024/data-2024-05-14.csv`. It converts and imports
that temporary subset, repeats the import, and checks all five MyQuery endpoints.
The test also installs the existing sample fixtures and confirms they remain
visible. It cleans up its test channels and tables when finished.

Run only against a fresh disposable database and query service. For example,
from `globus-web-prototype/`, start an isolated stack with no published ports:

```bash
docker network create mya-import-test-e2e
docker run -d --name mya-import-test-e2e-db --network mya-import-test-e2e --network-alias mya -e MYSQL_ROOT_PASSWORD=password -e MYSQL_PASSWORD=password -e TZ=America/New_York jeffersonlab/mycontainer:2.0.0
docker run -d --name mya-import-test-e2e-query --network mya-import-test-e2e -e TZ=America/New_York -v "$PWD/docker/demo-archive/myquery/context.xml:/usr/local/tomcat/conf/context.xml:ro" -v "$PWD/docker/demo-archive/myquery/deployment.properties:/usr/local/tomcat/lib/deployment.properties:ro" jeffersonlab/myquery:6.3.2
```

Once both services are ready:

```bash
DEMO_QUERY_TEST_DB=mya-import-test-e2e-db DEMO_QUERY_TEST_CONTAINER=mya-import-test-e2e-query .venv/bin/python -m unittest discover -s tools/demo_archive/tests -p test_myquery_integration.py
```

The environment names must start with `mya-import-test-`; do not point them at
application services. Stop and remove the disposable containers/volumes and
network afterward:

```bash
docker rm -f -v mya-import-test-e2e-query mya-import-test-e2e-db
docker network rm mya-import-test-e2e
```

Verified with the pinned images: Interval retains changes, Point carries the last
known value, MySampler recreates the one-second samples and carries values after
coverage ends, and MyStats returns the expected bin statistics. MySampler's
interval parameter is in **milliseconds**: `1000` means one second. These checks
exercise MyQuery HTTP endpoints, not the Flask/Globus delivery workflow.

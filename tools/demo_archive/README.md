# Demo Archive CSV Converter

Convert approved MySampler CSV data into per-PV SQL for the demo MYA database.
The converter uses synthetic metadata. A separate import command explicitly
loads generated bundles into the demo database.

The [behavioral contract](../../docs/demo-csv-import.md) records the agreed rules.

## Generate a SQL Bundle

From `globus-web-prototype/`, use the standard-library CLI:

```bash
python3 tools/demo_archive/demo_csv_import.py ../cebaf_linac_fe_2024/data-2024-05-09.csv --output-dir /tmp/demo-mya-may09
```

This command is an example; the approved datasets have not been converted as
part of development. Each output bundle has `<channel_id>_channel.sql` files,
`channels.json`, and `summary.json` with source name and per-PV event counts.
Source CSVs are read row by row, with memory proportional to the column count;
the converter keeps one output file open per PV. It does not query a database.

For the next CSV, reuse the previous mapping and choose a new output directory:

```bash
python3 tools/demo_archive/demo_csv_import.py ../cebaf_linac_fe_2024/data-2024-05-14.csv --mapping /tmp/demo-mya-may09/channels.json --output-dir /tmp/demo-mya-may14
```

- Each conversion accepts one CSV. Timestamps must be nondecreasing; equal
  encoded timestamps with identical values are skipped, and conflicts fail.
  Cross-file/database conflict checking is performed by the import command.
- Output is staged in a temporary sibling directory and published only after
  validation completes. Existing output directories are refused.
- Names use UTF-8 hex expressions in SQL and numeric filenames. Duplicate,
  empty, control-character, and reserved fixture PV headers are rejected.
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
.venv/bin/python -m unittest discover -s tests/demo_archive -p "test_*.py"
```

The database integration test is opt-in. Set `DEMO_IMPORT_TEST_CONTAINER` to the
name of a fresh disposable `mya-import-test-*` container running the pinned
image, then run `test_import_sql_integration.py`. The test writes channel ID
1000 and must never target a shared or application database.

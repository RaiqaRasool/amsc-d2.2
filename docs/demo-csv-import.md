# Demo CSV Import

## Purpose

Convert approved MySampler CSV exports into a synthetic MYA demo archive,
with reviewable SQL per PV and an explicit command for importing later files.
Timestamp helpers, channel mapping, and streaming CSV-to-SQL generation are
implemented, including an explicit repeat-safe demo database import command.

## Input

- Stream CSV rows; do not load whole datasets into memory or change source files.
- Expect a `Date` column and named scalar numeric PV columns. Similar PV names
  remain separate channels.
- Interpret timezone-naive dates in `America/New_York`. Reject ambiguous or
  nonexistent local times unless explicitly resolved rather than guessing.
- Validate headers, timestamps, and finite numeric values before publishing SQL.
- Reject missing or invalid measurements initially with a useful file/row/PV
  error; do not silently insert zero, skip them, or invent status events.

## Expected Behavior

- Generate one SQL file per PV containing synthetic channel metadata, the
  expected MYA data table definition, and retained events.
- Use stable channel IDs across conversions; maintain an explicit mapping and
  reject database ID/name collisions. Never infer identity from column order.
- Preserve the existing `channel100`, `channel101`, and `channel102` fixtures.
- Keep the first valid sample of each input file and subsequent numeric value
  changes independently for each PV. Treat numerically equal representations
  such as `0` and `0.0` as equal. Preserve returns to a previous value.
- Do not generate unavailable events at file boundaries or gaps. The latest
  retained measurement remains the latest known value across unobserved periods.
- Use synthetic scalar numeric metadata compatible with the demo archive;
  do not claim it reproduces original datatype, deadband, or device metadata.
- Verify timestamp encoding, numeric storage precision, required metadata, and
  normal-event codes against the archive implementation before emitting SQL.
- Skip identical PV/timestamp/value events on repeat imports; reject conflicting
  events or incompatible existing metadata instead of overwriting them.
- Import explicitly into the demo database. Adding or deleting SQL files does
  not automatically add or remove channels in an already initialized database.
- A removal command is outside the initial converter/import scope.

## Interpretation

- The generated archive is a change history derived from sampled values, not
  the original event history. Changes between samples cannot be reconstructed.
- Interval shows retained events. MySampler samples that synthetic history.
  Statistics describe the synthetic history and may differ from the source archive.
- Documentation and generated SQL identify the metadata and history as synthetic.

## Failure Behavior

- Invalid input must not leave partially published SQL presented as complete.
- Conflicts must fail with a clear diagnostic; the importer must report any
  already applied work rather than claiming an atomic import without proof.
- Generated SQL must safely quote PV names and use controlled identifiers.

## Planned Reviewable Steps

1. Record this contract and establish archive format requirements.
2. Implement and test timestamp conversion and stable channel mapping.
3. Implement streaming conversion and per-PV SQL generation with small fixtures.
4. Implement explicit import, rerun/conflict checks, and usage instructions.
5. Validate a small approved subset through MyQuery before a full-data import.

## Verification

- Test timestamp encoding against known archive timestamps and timezone cases.
- Test numeric deduplication, independent PV changes, file boundaries, and errors.
- Test stable IDs, safe SQL output, identical reruns, and conflicting imports.
- Confirm Channel, Point, Interval, MySampler, and supported MyStats queries
  against a small imported dataset.

## Implemented Format Helpers

- `tools/demo_archive/csv_to_sql.py` encodes Unix seconds in the upper bits and binary
  fractional seconds in the low 28 bits, using integer arithmetic and truncation.
  Timestamp text supports up to nine fractional digits and explicit UTC offsets.
- Naive dates use America/New_York; unresolved DST gaps and repeated hours fail.
  Negative times and values exceeding signed BIGINT storage are rejected.
- Timestamp format reference: [jmyapi TimeUtil.java](https://github.com/JeffersonLab/jmyapi/blob/7f2301e2e9acfee4853cfd27f689e7d1662d22ca/src/main/java/org/jlab/mya/TimeUtil.java).
  Its conversion methods use 28 fractional bits despite older introductory
  comments referring to 32 bits. Exported timestamps cannot always recover the
  original binary fraction exactly; the known fixture differs by one tick.
- Channel mapping helpers allocate IDs starting at 1000 in sorted PV-name order
  for newly encountered names, retaining all previously assigned IDs. This
  reserves the existing low-ID fixtures but does not prove database availability.
- JSON mappings can be loaded and saved explicitly. Saving refuses to overwrite
  an existing file; later conversion must publish the extended mapping alongside
  generated output. Import-time database collision checks remain a later step.
- Focused check: `.venv/bin/python -m unittest discover -s tools/demo_archive/tests -p test_csv_to_sql.py`.

## Usage

See [the demo archive tool README](../tools/demo_archive/README.md) for commands,
output format, and current limitations. Tool tests are colocated in `tools/demo_archive/tests/`, as explicitly requested.

## Implemented Import Command

- `tools/demo_archive/import_sql.py` validates generated bundles and invokes the
  selected Docker/Podman Compose demo database's MySQL client without a Python
  database-driver dependency. It checks metadata, ID/name collisions, event-table
  schema, and timestamp/code/FLOAT-value conflicts.
- Identical stored events are skipped. Incoming event values are compared at
  FLOAT storage precision. Conflicts fail without overwriting existing events.
- Each channel's event insertion uses an InnoDB transaction. DDL/metadata
  creation and previously completed channels can remain on failure; errors
  report the failing channel and channels already completed.
- The tool serializes its own import sessions with an advisory database lock;
  unrelated writers must be stopped for import. Existing sample fixtures remain.
- Verified initial import, repeat import, later-file append, event conflicts,
  incompatible metadata/schema, and ID collisions against an isolated
  `jeffersonlab/mycontainer:2.0.0` container. Approved CSVs and application
  databases were not used for those importer checks.
- End-to-end MyQuery validation is implemented in
  `tools/demo_archive/tests/test_myquery_integration.py`. It reads only five rows and
  the first two PV columns from the approved May 14 CSV into a temporary subset.
  Against pinned MYA 2.0.0 and MyQuery 6.3.2, all five query types passed:
  Channel metadata, Interval change events, Point after coverage ends,
  MySampler reconstruction, and one-bin MyStats min/max/mean/duration.
- Identical reimport inserted zero events, and project fixtures 100–102 remained
  discoverable. No full approved file was read or loaded. MyQuery is exercised
  directly over HTTP; Flask/Globus delivery is outside this tool validation.
- MySampler interval is milliseconds (`1000` for one second). The short
  one-second-source test verifies statistics against time-weighted sample values;
  MyStats event counters can include generated boundary events and must not be
  interpreted as a raw stored-row count.

## Folder Conversion

- A directory input streams its immediate CSV files sequentially with one shared
  mapping, then merges generated events into one SQL file per PV in timestamp
  order. Each file retains its first sample. Column sets may differ.
- The initial folder mode rejects overlapping/touching file ranges; it does not
  attempt to reconstruct or reconcile overlapping sampled histories. Invalid
  input leaves no published bundle. The output includes combined/source summaries.
- Generated artifacts live under the Git-ignored `tools/demo_archive/generated/`
  directory. Folder tests cover shared/new PVs, reordered columns, filename/time
  ordering, mapping reuse, invalid input, and overlap rejection.
- Validated the complete approved folder on 2026-10-15: three CSVs, 9,395
  sampled rows, 226 PVs, and 303,146 retained events. The generated combined
  bundle passed importer validation (about 28 MB of SQL). No database import
  was performed in this step.

## SQL Filenames

- Generated SQL filenames include both stable ID and readable PV name, such as
  `1002_INX2L07_gDsRt.sql`. Unsafe characters are percent-encoded and filename
  labels capped at 180 characters. IDs prevent filename collisions.
- Database table names remain `table_<chan_id>`; exact PV names remain unchanged
  in metadata, mappings, and website searches. The importer accepts older numeric
  filenames too. Existing generated files were renamed and the 226-PV bundle
  passed validation; event contents and channel assignments were unchanged.

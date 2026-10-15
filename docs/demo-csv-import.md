# Demo CSV Import

## Purpose

Convert approved MySampler CSV exports into a synthetic MYA demo archive,
with reviewable SQL per PV and an explicit command for importing later files.
Timestamp helpers, channel mapping, and streaming CSV-to-SQL generation are
implemented. Database importing is not implemented yet.

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

- `demo_csv_import.py` encodes Unix seconds in the upper bits and binary
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
- Focused check: `.venv/bin/python -m unittest discover -s tests -p test_demo_csv_import.py`.

## Generate a SQL Bundle

From `globus-web-prototype/`, use the standard-library CLI:

```bash
python3 demo_csv_import.py ../cebaf_linac_fe_2024/data-2024-05-09.csv --output-dir /tmp/demo-mya-may09
```

This command is an example; the approved datasets have not been converted as
part of development. Each output bundle has `<channel_id>_channel.sql` files,
`channels.json`, and `summary.json` with source name and per-PV event counts.
Source CSVs are read row by row, with memory proportional to the column count;
the converter keeps one output file open per PV. It does not query a database.

For the next CSV, reuse the previous mapping and choose a new output directory:

```bash
python3 demo_csv_import.py ../cebaf_linac_fe_2024/data-2024-05-14.csv --mapping /tmp/demo-mya-may09/channels.json --output-dir /tmp/demo-mya-may14
```

- Each conversion accepts one CSV. Timestamps must be nondecreasing; equal
  encoded timestamps with identical values are skipped, and conflicts fail.
  Cross-file/database conflict checking belongs to the later importer.
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
- Generated SQL currently uses plain INSERT/CREATE statements for initial
  loading. Do not run later bundles over existing PVs yet: the explicit
  repeat-safe importer is the next implementation step.

# Demo Archive CSV Converter

Convert approved MySampler CSV data into per-PV SQL for the demo MYA database.
The converter uses synthetic metadata and does not modify the database.

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

## Verification

Run from `globus-web-prototype/`:

```bash
.venv/bin/python -m unittest discover -s tests/demo_archive -p test_demo_csv_import.py
```

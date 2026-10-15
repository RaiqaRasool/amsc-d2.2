"""Stream a MySampler CSV into per-PV SQL files (no database writes)."""

import argparse
import csv
import json
import math
import struct
import shutil
import io
import tempfile
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Verified against JeffersonLab/jmyapi TimeUtil.java at 7f2301e2.
TICKS_PER_SECOND = 1 << 28
FIRST_DEMO_CHANNEL_ID = 1000
UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"(?:\.(?P<fraction>\d{1,9}))?(?:Z|[+-]\d{2}:\d{2})?"
)


def to_mya_timestamp(value, timezone_name="America/New_York"):
    """Encode ISO date/time text, rejecting unresolved local DST transitions."""
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid timestamp: {value!r}")
    fraction = match.group("fraction") or ""
    nanoseconds = int(fraction.ljust(9, "0"))
    # Parse whole seconds separately to preserve up to nine fractional digits.
    whole_seconds = value
    if fraction:
        whole_seconds = value[:match.start("fraction") - 1] + value[match.end("fraction"):]
    parsed = datetime.fromisoformat(whole_seconds)
    if parsed.tzinfo is None:
        zone = ZoneInfo(timezone_name)
        candidates = set()
        for fold in (0, 1):
            instant = parsed.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None) == parsed:
                candidates.add(instant)
        if len(candidates) != 1:
            raise ValueError(f"Ambiguous or nonexistent local timestamp: {value!r}")
        parsed = candidates.pop()
    delta = parsed.astimezone(timezone.utc) - UTC_EPOCH
    seconds = delta.days * 86400 + delta.seconds
    result = seconds * TICKS_PER_SECOND + nanoseconds * TICKS_PER_SECOND // 1_000_000_000
    if not 0 <= result <= (1 << 63) - 1:
        raise ValueError(f"Timestamp outside supported MYA range: {value!r}")
    return result


def extend_channel_mapping(pv_names, existing=None):
    """Return a stable mapping; callers must reuse it for subsequent conversions."""
    mapping = dict(existing or {})
    for name, channel_id in mapping.items():
        if not isinstance(name, str) or not name or name != name.strip():
            raise ValueError("Invalid PV name in channel mapping")
        if type(channel_id) is not int or not FIRST_DEMO_CHANNEL_ID <= channel_id <= 2**31 - 1:
            raise ValueError(f"Invalid demo channel ID for {name!r}")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Duplicate channel IDs in mapping")
    names = list(pv_names)
    if any(not isinstance(name, str) or not name or name != name.strip() for name in names):
        raise ValueError("Invalid PV name")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate PV names")
    next_id = max(mapping.values(), default=FIRST_DEMO_CHANNEL_ID - 1) + 1
    for name in sorted(set(names) - mapping.keys()):
        if next_id > 2**31 - 1:
            raise ValueError("Demo channel IDs exhausted")
        mapping[name] = next_id
        next_id += 1
    return mapping


def load_channel_mapping(path):
    """Load an explicit JSON mapping; a missing file is not silently replaced."""
    mapping = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise ValueError("Channel mapping must be a JSON object")
    return extend_channel_mapping([], mapping)


def save_channel_mapping(path, mapping):
    """Create a mapping file without overwriting a previously saved mapping."""
    validated = extend_channel_mapping([], mapping)
    with Path(path).open("x", encoding="utf-8") as output:
        json.dump(validated, output, indent=2, sort_keys=True)
        output.write("\n")


def _numeric_value(text):
    """Validate numeric text and the FLOAT storage used by existing MYA fixtures."""
    try:
        value = Decimal(text)
        if not value.is_finite():
            raise ValueError("measurement must be finite")
        stored = struct.unpack("!f", struct.pack("!f", float(value)))[0]
        if not math.isfinite(stored) or (value != 0 and stored == 0):
            raise ValueError("measurement outside supported FLOAT range")
    except (InvalidOperation, OverflowError, struct.error) as error:
        raise ValueError("invalid or out-of-range numeric measurement") from error
    return value


def _write_channel_schema(output, name, channel_id):
    # A UTF-8 hex literal avoids SQL mode-dependent quoting of approved PV names.
    name_sql = "CONVERT(0x" + name.encode("utf-8").hex() + " USING utf8mb4)"
    output.write(
        "-- Synthetic scalar metadata and change history derived from MySampler CSV.\n"
        "-- Initial-load SQL; use import_sql.py for existing database channels.\n"
        "USE archive;\n"
        "INSERT INTO channels "
        "(chan_id, name, type, adel, size, clip, active, request, alert, host, backup, ioc)\n"
        f"VALUES ({channel_id}, {name_sql}, 6, 0, 1, NULL, 1, 1, 0, 'mya', "
        "'6197335468200165376', NULL);\n"
        f"CREATE TABLE `table_{channel_id}` (\n"
        "  `time` BIGINT NOT NULL,\n"
        "  `code` TINYINT UNSIGNED NOT NULL DEFAULT 0,\n"
        "  `val1` FLOAT NOT NULL DEFAULT 0,\n"
        "  PRIMARY KEY (`time`)\n);\n"
    )


def convert_csv(csv_path, output_dir, mapping_path=None, timezone_name="America/New_York"):
    """Publish one complete SQL bundle for one ordered CSV, using bounded row memory.

    Reuse the previous bundle's channels.json for subsequent CSVs. Use the
    companion import_sql.py for database collision and rerun handling.
    """
    csv_path, output_dir = Path(csv_path), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    existing = load_channel_mapping(mapping_path) if mapping_path is not None else {}
    # Validate timezone even if all input timestamps happen to include offsets.
    ZoneInfo(timezone_name)
    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source, strict=True)
        header = next(reader, [])
        if len(header) < 2 or header[0] != "Date":
            raise ValueError(f"{csv_path}: expected Date followed by PV columns")
        names = header[1:]
        if any(any(ord(char) < 32 for char in name) for name in names):
            raise ValueError(f"{csv_path}: control characters in PV name")
        if set(names) & {"Date", "channel100", "channel101", "channel102"}:
            raise ValueError(f"{csv_path}: reserved PV name")
        mapping = extend_channel_mapping(names, existing)
        counts = dict.fromkeys(names, 0)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".demo-csv-", dir=output_dir.parent) as staging:
            bundle = Path(staging) / "bundle"
            bundle.mkdir()
            with ExitStack() as files:
                outputs = {}
                for name in names:
                    outputs[name] = files.enter_context(
                        (bundle / f"{mapping[name]}_channel.sql").open("w", encoding="utf-8")
                    )
                    _write_channel_schema(outputs[name], name, mapping[name])
                previous_time, previous_values = None, None
                first_time = None
                rows = 0
                for row in reader:
                    location = f"{csv_path}: row {reader.line_num}"
                    if len(row) != len(header):
                        raise ValueError(f"{location}: expected {len(header)} fields, got {len(row)}")
                    try:
                        timestamp = to_mya_timestamp(row[0], timezone_name)
                    except ValueError as error:
                        raise ValueError(f"{location}: {error}") from error
                    if previous_time is not None and timestamp < previous_time:
                        raise ValueError(f"{location}: timestamps must be nondecreasing")
                    values = []
                    for name, text in zip(names, row[1:]):
                        try:
                            values.append(_numeric_value(text))
                        except ValueError as error:
                            raise ValueError(f"{location}, PV {name!r}: {error}") from error
                    if timestamp == previous_time:
                        if values != previous_values:
                            raise ValueError(f"{location}: conflicting values at duplicate timestamp")
                        continue
                    for index, (name, value) in enumerate(zip(names, values)):
                        if previous_values is None or value != previous_values[index]:
                            outputs[name].write(
                                f"INSERT INTO `table_{mapping[name]}` (`time`, `code`, `val1`) "
                                f"VALUES ({timestamp}, 0, {value if value else 0});\n"
                            )
                            counts[name] += 1
                    if first_time is None:
                        first_time = timestamp
                    previous_time, previous_values = timestamp, values
                    rows += 1
                if rows == 0:
                    raise ValueError(f"{csv_path}: no measurement rows")
            save_channel_mapping(bundle / "channels.json", mapping)
            (bundle / "summary.json").write_text(json.dumps({
                "source": csv_path.name, "timezone": timezone_name,
                "synthetic_metadata": True, "rows": rows, "events_per_pv": counts,
                "storage": "FLOAT", "event_code": 0,
                "first_timestamp": first_time, "last_timestamp": previous_time,
            }, indent=2) + "\n", encoding="utf-8")
            if output_dir.exists():
                raise FileExistsError(f"Output directory already exists: {output_dir}")
            bundle.rename(output_dir)
    return counts



def convert_folder(csv_dir, output_dir, mapping_path=None, timezone_name="America/New_York"):
    """Combine non-overlapping CSV runs into one per-PV SQL bundle.

    Files are converted sequentially with a shared mapping, then merged by time.
    Overlapping ranges are refused rather than guessing at sampled-history conflicts.
    """
    csv_dir, output_dir = Path(csv_dir), Path(output_dir)
    sources = sorted(path for path in csv_dir.iterdir()
                     if path.is_file() and path.suffix.lower() == ".csv")
    if not sources:
        raise ValueError(f"{csv_dir}: no CSV files found")
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".demo-folder-", dir=output_dir.parent) as staging:
        staging = Path(staging)
        runs = []
        current_mapping = mapping_path
        for index, source in enumerate(sources):
            run_dir = staging / f"run-{index}"
            convert_csv(source, run_dir, current_mapping, timezone_name)
            current_mapping = run_dir / "channels.json"
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            runs.append((summary, run_dir))
        runs.sort(key=lambda run: run[0]["first_timestamp"])
        for previous, current in zip(runs, runs[1:]):
            if current[0]["first_timestamp"] <= previous[0]["last_timestamp"]:
                raise ValueError(
                    f"Overlapping CSV time ranges: {previous[0]['source']} and {current[0]['source']}; "
                    "convert/import separately to diagnose event conflicts"
                )
        mapping = load_channel_mapping(current_mapping)
        counts = {}
        for summary, _ in runs:
            for name, count in summary["events_per_pv"].items():
                counts[name] = counts.get(name, 0) + count
        bundle = staging / "bundle"
        bundle.mkdir()
        # Only one final output is open at a time, and copying is chunked.
        for name in sorted(counts):
            channel_id = mapping[name]
            filename = f"{channel_id}_channel.sql"
            schema = io.StringIO()
            _write_channel_schema(schema, name, channel_id)
            header = schema.getvalue()
            with (bundle / filename).open("w", encoding="utf-8") as output:
                output.write(header)
                for summary, run_dir in runs:
                    if name in summary["events_per_pv"]:
                        with (run_dir / filename).open(encoding="utf-8") as source:
                            if source.read(len(header)) != header:
                                raise ValueError(f"Inconsistent generated schema for {name!r}")
                            shutil.copyfileobj(source, output)
        save_channel_mapping(bundle / "channels.json", mapping)
        summary = {
            "sources": [run[0] for run in runs], "timezone": timezone_name,
            "synthetic_metadata": True, "rows": sum(run[0]["rows"] for run in runs),
            "events_per_pv": counts, "storage": "FLOAT", "event_code": 0,
            "first_timestamp": runs[0][0]["first_timestamp"],
            "last_timestamp": runs[-1][0]["last_timestamp"],
        }
        (bundle / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if output_dir.exists():
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        bundle.rename(output_dir)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="MySampler CSV or folder of CSVs (non-recursive)")
    parser.add_argument("--output-dir", required=True, help="New directory for generated SQL bundle")
    parser.add_argument("--mapping", help="Previous bundle's channels.json; reuse for later CSVs")
    parser.add_argument("--timezone", default="America/New_York")
    args = parser.parse_args()
    try:
        converter = convert_folder if Path(args.csv).is_dir() else convert_csv
        counts = converter(args.csv, args.output_dir, args.mapping, args.timezone)
    except (ValueError, OSError, KeyError, csv.Error) as error:
        parser.exit(1, f"Conversion failed: {error}\n")
    print(f"Generated {len(counts)} channel SQL files with {sum(counts.values())} events in {args.output_dir}")


if __name__ == "__main__":
    main()

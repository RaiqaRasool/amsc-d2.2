"""Format helpers for the planned demo CSV importer (no database writes)."""

import json
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

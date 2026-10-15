"""Import validated demo SQL files through the demo Compose service's MySQL client."""

import argparse
import io
import json
import re
import subprocess
import tempfile
from pathlib import Path

if __package__:
    from .demo_csv_import import _numeric_value, _write_channel_schema, channel_sql_filename, load_channel_mapping
else:
    from demo_csv_import import _numeric_value, _write_channel_schema, channel_sql_filename, load_channel_mapping

_EVENT = re.compile(
    r"INSERT INTO `table_(\d+)` \(`time`, `code`, `val1`\) VALUES \((\d+), 0, ([^;]+)\);\n?"
)


def validated_events(path, name, channel_id):
    """Accept only this tool's schema and numeric events, never arbitrary SQL."""
    expected = io.StringIO()
    _write_channel_schema(expected, name, channel_id)
    header = expected.getvalue()
    with path.open(encoding="utf-8") as source:
        if source.read(len(header)) != header:
            raise ValueError(f"{path.name}: schema does not match the generated channel metadata")
        previous_time = -1
        count = 0
        for line in source:
            match = _EVENT.fullmatch(line)
            if match is None or int(match[1]) != channel_id:
                raise ValueError(f"{path.name}: invalid event statement")
            timestamp = int(match[2])
            if not previous_time < timestamp <= 2**63 - 1:
                raise ValueError(f"{path.name}: event timestamps must increase within BIGINT range")
            value = _numeric_value(match[3])
            previous_time = timestamp
            count += 1
            yield timestamp, value
        if count == 0:
            raise ValueError(f"{path.name}: no events")


def validate_bundle(bundle):
    bundle = Path(bundle)
    mapping = load_channel_mapping(bundle / "channels.json")
    summary = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("Bundle summary must be a JSON object")
    counts = summary.get("events_per_pv")
    if not isinstance(counts, dict) or not counts:
        raise ValueError("Bundle summary must contain events_per_pv")
    channels = []
    for name, count in counts.items():
        if name not in mapping or type(count) is not int or count < 1:
            raise ValueError("Invalid channel or count in bundle summary")
        try:
            encoded_name = name.encode("latin1")
        except UnicodeEncodeError as error:
            raise ValueError(f"PV name {name!r} is not supported by the demo database's latin1 schema") from error
        if len(encoded_name) > 255:
            raise ValueError(f"PV name {name!r} exceeds the demo database's 255-character limit")
        channel_id = mapping[name]
        path = bundle / channel_sql_filename(name, channel_id)
        if not path.exists():
            path = bundle / f"{channel_id}_channel.sql"  # Older generated bundles.
        if sum(1 for _ in validated_events(path, name, channel_id)) != count:
            raise ValueError(f"{path.name}: event count differs from summary")
        channels.append((name, channel_id, path))
    if {p.name for p in bundle.glob("*.sql")} != {p.name for _, _, p in channels}:
        raise ValueError("SQL files do not match bundle summary")
    return channels


def write_import_sql(output, name, channel_id, path):
    """Stage FLOAT values, reject conflicts, then insert only missing events.

    Strict-mode NOT NULL guards support MariaDB 5.5 in the pinned demo image.
    Failed predicates insert NULL and stop the batch before event writes.
    """
    name_sql = "CONVERT(0x" + name.encode("utf-8").hex() + " USING utf8mb4)"
    table = f"table_{channel_id}"
    # Serialize this tool's importers. The connection must own the lock before
    # any persistent changes; it is automatically released on connection exit.
    output.write("USE archive;\nSET SESSION sql_mode='STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION';\n")
    output.write("CREATE TEMPORARY TABLE import_checks (\n"
                 " lock_ok INT NOT NULL DEFAULT 1,\n"
                 " identity_ok INT NOT NULL DEFAULT 1,\n"
                 " structure_ok INT NOT NULL DEFAULT 1,\n"
                 " events_ok INT NOT NULL DEFAULT 1\n) ENGINE=InnoDB;\n"
                 "INSERT INTO import_checks(lock_ok) VALUES (IF(GET_LOCK('demo_archive_import', 0)=1,1,NULL));\n")
    output.write(
        f"SET @channel_count = (SELECT COUNT(*) FROM channels WHERE chan_id={channel_id} OR name={name_sql});\n"
        f"SET @channel_match = (SELECT COUNT(*) FROM channels WHERE chan_id={channel_id} "
        f"AND BINARY CONVERT(name USING utf8mb4)=BINARY {name_sql} AND type=6 AND size=1 AND BINARY host=BINARY 'mya' "
        "AND BINARY adel=BINARY '0' AND clip IS NULL AND active=1 AND request=1 AND alert=0 "
        "AND backup='6197335468200165376' AND ioc IS NULL);\n"
        "INSERT INTO import_checks(identity_ok) VALUES "
        "(IF(@channel_count=0 OR (@channel_count=1 AND @channel_match=1),1,NULL));\n"
        f"SET @table_count = (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='archive' AND TABLE_NAME='{table}');\n"
        "INSERT INTO import_checks(structure_ok) VALUES (IF(@channel_count=@table_count,1,NULL));\n"
        f"INSERT INTO channels (chan_id,name,type,adel,size,clip,active,request,alert,host,backup,ioc) "
        f"SELECT {channel_id},{name_sql},6,0,1,NULL,1,1,0,'mya','6197335468200165376',NULL FROM DUAL WHERE @channel_count=0;\n"
        f"CREATE TABLE IF NOT EXISTS `{table}` (`time` BIGINT NOT NULL, `code` TINYINT UNSIGNED NOT NULL DEFAULT 0, "
        "`val1` FLOAT NOT NULL DEFAULT 0, PRIMARY KEY (`time`)) ENGINE=InnoDB;\n"
        "INSERT INTO import_checks(structure_ok) SELECT IF(\n"
        f" (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='archive' AND TABLE_NAME='{table}' AND ENGINE='InnoDB')=1\n"
        f" AND (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='archive' AND TABLE_NAME='{table}')=3\n"
        f" AND (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='archive' AND TABLE_NAME='{table}' AND IS_NULLABLE='NO' AND (\n"
        " (COLUMN_NAME='time' AND DATA_TYPE='bigint' AND COLUMN_TYPE NOT LIKE '%unsigned%') OR\n"
        " (COLUMN_NAME='code' AND DATA_TYPE='tinyint' AND COLUMN_TYPE LIKE '%unsigned%') OR\n"
        " (COLUMN_NAME='val1' AND DATA_TYPE='float'))) = 3\n"
        f" AND (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='archive' AND TABLE_NAME='{table}' AND INDEX_NAME='PRIMARY')=1\n"
        f" AND (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='archive' AND TABLE_NAME='{table}' AND INDEX_NAME='PRIMARY' AND COLUMN_NAME='time')=1,1,NULL);\n"
        "CREATE TEMPORARY TABLE incoming (`time` BIGINT PRIMARY KEY, `code` TINYINT UNSIGNED, `val1` FLOAT NOT NULL) ENGINE=InnoDB;\n"
    )
    for timestamp, value in validated_events(path, name, channel_id):
        output.write(f"INSERT INTO incoming VALUES ({timestamp},0,{value if value else 0});\n")
    output.write(
        "START TRANSACTION;\n"
        f"INSERT INTO import_checks(events_ok) SELECT IF(COUNT(*)=0,1,NULL) FROM incoming i JOIN `{table}` t USING (`time`) "
        "WHERE t.code<>i.code OR t.val1<>i.val1;\n"
        f"SET @skipped = (SELECT COUNT(*) FROM incoming i JOIN `{table}` t USING (`time`));\n"
        f"INSERT INTO `{table}` (`time`,`code`,`val1`) SELECT i.time,i.code,i.val1 FROM incoming i "
        f"LEFT JOIN `{table}` t USING (`time`) WHERE t.time IS NULL;\n"
        "SET @inserted = ROW_COUNT();\nCOMMIT;\n"
        "SELECT @inserted, @skipped;\n"
    )


def mysql_command(runtime="docker", compose_file="docker-compose.yml"):
    return [runtime, "compose", "-f", compose_file, "--profile", "demo", "exec", "-T", "mya",
            "sh", "-c", 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --batch --skip-column-names -u root archive']


def import_bundle(bundle, command):
    channels = validate_bundle(bundle)  # Validate all local files before database writes.
    version = subprocess.run(command, input="SELECT VERSION();\n", capture_output=True, text=True)
    if version.returncode:
        raise RuntimeError(f"Cannot connect to demo database: {version.stderr.strip()}")
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version.stdout.strip())
    if match is None or tuple(map(int, match.groups())) < (5, 5, 0):
        raise RuntimeError("Database version is unsupported; expected MySQL/MariaDB 5.5 or later")
    completed = []
    for name, channel_id, path in channels:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as sql:
            write_import_sql(sql, name, channel_id, path)
            sql.seek(0)
            result = subprocess.run(command, stdin=sql, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(
                f"Import stopped at {name!r} (ID {channel_id}); completed channels: {completed!r}. "
                "The failing channel may have newly created metadata/table, but its existing events are not overwritten. "
                f"MySQL: {result.stderr.strip()}"
            )
        completed.append(name)
        print(f"{name} (ID {channel_id}): inserted/skipped {result.stdout.strip()}")
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="Generated SQL bundle directory")
    parser.add_argument("--runtime", choices=("docker", "podman"), default="docker")
    parser.add_argument("--compose-file", default="docker-compose.yml")
    args = parser.parse_args()
    try:
        import_bundle(args.bundle, mysql_command(args.runtime, args.compose_file))
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()

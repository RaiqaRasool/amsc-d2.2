# Production Runtime

## Purpose

Run the public application with production process and image behavior while it
continues to use the containerized sample MyQuery and MYA services.

## Main Flow

1. The standalone production Compose file builds one application image with
   dependencies and source code.
2. Gunicorn serves the web application with debug mode disabled.
3. The worker and monitor run from the same immutable image.
4. All application services share persistent instance storage, while the web
   and worker share the configured export directory.

## Expected Behavior

- Development uses `podman compose --profile demo up --build`, shared SELinux
  source bind mounts, and Flask's development server.
- Development and production are complete, independent Compose configurations;
  neither includes or overrides another file or requires a sibling repository.
- The `demo` profile starts the bundled MYA/MyQuery backend in either runtime.
  MYA and MyQuery are reachable only on the internal Compose network.
- Only the web service publishes a host port, bound to `127.0.0.1:5000` for the
  host Nginx reverse proxy.
- Production containers run image-baked code and mount only persistent instance
  and export storage.
- Web, worker, and monitor use Podman's
  `keep-id:uid=10001,gid=10001` user namespace. Shared bind mounts use the
  SELinux `z` label.
- Web, worker, monitor, MYA, and MyQuery restart unless explicitly stopped.
- MYA stores its database in the Compose-managed `mya-data` volume at
  `/var/lib/mysql` in both runtimes. Restarts and container recreation retain
  imported channels when using the same Compose project and volume.
- Init SQL seeds only an empty database. Existing databases are updated through
  `tools/demo_archive/import_sql.py`; raw init SQL is not replayed on restart.

## Failure Behavior

- Compose fails during interpolation when `MYQUERY_SERVER` is unset. Demo
  deployments must set it to `myquery:8080`; external deployments must set the
  real endpoint.
- The worker handles an unavailable MyQuery endpoint through its normal job
  failure path; it does not require the optional demo service to be enabled.
- Production startup fails if the configured host export directory is not
  writable by UID/GID `10001`.
- TLS, reverse-proxy trust, and external secret storage remain infrastructure
  requirements and are not supplied by Compose.

## Key Components

- `Dockerfile`: self-contained non-root application image
- `docker-compose.yml`: standalone development runtime
- `docker-compose.production.yml`: standalone production runtime
- `docker/demo-archive/`: colocated MYA fixtures and MyQuery configuration

## Verification

- `podman compose --profile demo config`
- `podman compose -f docker-compose.production.yml --profile demo config`
- `python3 -m unittest discover -s tests`

## Adopt Persistent MYA Storage on Production

Run from the production checkout after deploying this change. Keep the existing
Compose project name and use the same runtime/account that owns the stack.
The commands use Podman; change `podman` to `docker` in both places if needed.
Run in a Bash shell. This procedure pauses application services during recovery.

Before recreating MYA, dump the current archive. Switching from the old anonymous
volume to the named volume does not migrate its contents automatically. Stop if
any command fails; do not recreate MYA if the backup fails.

```bash
set -e
runtime=podman
compose=("$runtime" compose -f docker-compose.production.yml --profile demo)
backup_dir="$HOME/mya-backups"
mkdir -p "$backup_dir"
backup="$backup_dir/archive-$(date +%Y%m%d-%H%M%S).sql"

"${compose[@]}" stop web worker monitor myquery
"${compose[@]}" exec -T mya sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -u root --lock-all-tables --databases archive' > "$backup"
test -s "$backup"

"${compose[@]}" up -d mya
# Wait up to two minutes for initial database setup to finish.
ready=0
for attempt in {1..60}; do
  if "${compose[@]}" exec -T mya sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -h 127.0.0.1 -u root archive -e "SELECT 1 FROM channels LIMIT 1"' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
test "$ready" = 1

"${compose[@]}" exec -T mya sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -u root' < "$backup"

# This bundle must exist on the production host, including its JSON manifests.
python3 tools/demo_archive/import_sql.py \
  tools/demo_archive/generated/cebaf_linac_fe_2024 \
  --runtime "$runtime" --compose-file docker-compose.production.yml

"${compose[@]}" up -d myquery web worker monitor
"${compose[@]}" exec -T myquery curl --fail 'http://localhost:8080/myquery/channel?q=INX2L04_gDsRt&l=&o=&m=docker'
```

MyQuery may need time to start before the final check succeeds. Verify that its
response includes the requested PV, then retry the original query.
The importer restores the missing bundle channels, skips identical events,
and refreshes the demo catalog. Repeat it for any other approved bundles.
Generated bundles are ignored by Git: copy the entire bundle from your retained
source, or regenerate it from the original CSV folder using `csv_to_sql.py`.
Do not add a directory mount over `/docker-entrypoint-initdb.d`, because that
would hide the image's base schema scripts.

Keep the SQL backup outside the repository. Never use `compose down -v` for a
routine deployment: it deletes named database and application volumes. A new
Compose project name selects different volumes. The volume preserves data but
is not a backup; retain database dumps and source bundles separately.

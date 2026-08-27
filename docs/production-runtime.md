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

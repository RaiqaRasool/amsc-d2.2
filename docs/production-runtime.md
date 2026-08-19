# Production Runtime

## Purpose

Run the public application with production process and image behavior while it
continues to use the containerized sample MyQuery and MYA services.

## Main Flow

1. Compose builds one application image with dependencies and source code.
2. Gunicorn serves the web application with debug mode disabled.
3. The worker and monitor run from the same immutable image.
4. All application services share persistent instance storage, while the web
   and worker share the configured export directory.

## Expected Behavior

- Development uses `docker compose up --build`, source bind mounts, and Flask's
  development server.
- The production override keeps the sample MYA/MyQuery backend but does not
  publish their database or HTTP ports on the host.
- Production containers run the copied image code as UID/GID `10001` and do not
  mount the source tree.
- Web, worker, monitor, MYA, and MyQuery restart unless explicitly stopped.

## Failure Behavior

- The worker waits for the sample MyQuery health check before starting.
- Production startup fails if the configured host export directory is not
  writable by UID/GID `10001`.
- TLS, reverse-proxy trust, and external secret storage remain infrastructure
  requirements and are not supplied by Compose.

## Key Components

- `Dockerfile`: self-contained non-root application image
- `docker-compose.yml`: development and shared sandbox services
- `docker-compose.production.yml`: production runtime overrides

## Verification

- `docker compose config --quiet`
- `docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet`
- `python3 -m unittest discover -s tests`

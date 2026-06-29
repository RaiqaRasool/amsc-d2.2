# Globus Web Prototype

Minimal Flask prototype for AmSC data delivery via Globus.

## Current Goal

Build one small step at a time:

1. Confirm the web OAuth approach against official Globus docs.
2. Implement `/login` and `/callback`.
3. Reuse or translate working logic from `../globus_cli_demo/`.
4. Add destination collection search and path browsing.
5. Submit a transfer for a known test file.
6. Bring in the minimal MYA archive/export logic after the Globus web flow works.

## Local Configuration

For MYA export and transfer, set these local-only values in `.env`:

```text
SOURCE_COLLECTION_ID=<source-collection-id>
SOURCE_DIRECTORY=/directory/as-seen-by-globus
MYA_EXPORT_HOST_DIR=/host/folder/exposed-by-globus-connect-personal
```

Compose mounts `MYA_EXPORT_HOST_DIR` at `/mya-output` inside the web container.
Each MYA query writes a unique file there using a generated UUID.
`SOURCE_DIRECTORY` identifies that host folder from the source collection's
view. These paths may differ because the container and Globus Connect Personal
see the shared host folder through different filesystem paths.

If `MYA_EXPORT_HOST_DIR` is omitted, Compose uses `./mya-output`. The selected
destination folder comes from the web UI. The app submits the source file into
that folder using the source filename.

Submitted transfers are labeled with this prefix so the app can find recent
app-created transfers from Globus:

```text
AmSC MYA Delivery - <user label>
```

The Transfers table shows app-level statuses derived from Globus task statuses,
such as `IN PROGRESS`, `SUCCEEDED`, `FAILED`, and `QUEUED`.

## Run With Docker

Use Docker Compose for local development. This keeps every developer on the
same Python and Globus SDK versions.

Start the app:

```bash
docker compose up --build
```

For later runs, when `Dockerfile` and dependencies have not changed:

```bash
docker compose up
```

Stop the app with `Ctrl+C`, or from another terminal:

```bash
docker compose down
```

The app is available at `http://localhost:5000`. Keep the Globus redirect URI
registered as:

```text
http://localhost:5000/callback
```

The image only provides Python. Compose mounts this directory into the
container, installs `requirements.txt` from the mounted checkout, and runs
`python app.py`.

## Reference Prototype

`../globus_cli_demo/` is the source of verified project behavior for:

- Globus login
- Transfer API token use
- source collection data-access consent
- collection search
- destination path browsing
- transfer submission
- task status and event retrieval

Keep this prototype as reference code; do not polish CLI-only behavior unless explicitly asked.

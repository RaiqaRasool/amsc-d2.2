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

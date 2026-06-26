# AmSC Globus Data Delivery Guidance

## Active Scope

Primary implementation work belongs in this `globus-web-prototype/` directory.

Keep project-specific documentation, context, and development instructions in this directory. Treat sibling folders as read-only reference material unless explicitly asked to modify them.

Hard editing rule: run file reads, patches, and Git commands with `globus-web-prototype/` as the working directory whenever the tool supports it. When adding or editing files, target this directory only. Do not create, patch, move, or delete files in the parent repo or sibling folders unless explicitly instructed.

Use these sibling folders as references:

- `../globus_cli_demo/`: working CLI prototype for Globus Auth, Transfer API usage, transfer submission, task status, task events, destination search, path browsing, and consent-required handling.
- `../mya-rest-api/`, `../mya-worker/`, `../mya-workflow-orchestrator/`: earlier MYA/backend architecture experiments and reusable implementation ideas.

## Globus References

Use official Globus documentation as the primary source of truth:

- Globus Auth developer guide: https://docs.globus.org/api/auth/developer-guide/
- Globus Transfer overview: https://docs.globus.org/api/transfer/overview/

If documentation is unclear, say so instead of guessing. Prefer verified official behavior over assumptions or memory.

## Development Style

- Work in small, reviewable steps.
- Reuse the CLI prototype where appropriate.
- Avoid broad refactors and speculative features.
- Prefer the smallest change that correctly advances the current milestone.
- Add dependencies only when the current step clearly needs them.
- Before starting a new logical step, check `git status --short`. If the previous step is still uncommitted, stop and ask the user whether to commit it before continuing.
- Explain every code change: files modified, what changed, why, how it works, how it fits the architecture, and alternatives considered.
- When asked for a commit message, use the `git-commit-formatter` skill if it is available. If it is not available, provide a short imperative commit message that clearly names the change.

## Current Direction

The CLI prototype is a native/thick-client implementation. The web prototype is expected to use a Globus Auth client appropriate for a Science Gateway / Web Application (Portal), pending confirmation from the official Globus docs during implementation.

Near-term goal: a minimal Flask flow where a user authenticates with Globus, selects a destination collection/path, submits a transfer from an application-controlled source collection, and sees transfer status.

Long-term vision: Jefferson Lab accelerator data is retrieved from the MYA archive, packaged as pandas/HDF5-style files, delivered through Globus to a destination facility such as Brookhaven, and then used by downstream AI/model workflows. Use this as architectural context, not as an immediate implementation checklist.

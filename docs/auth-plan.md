# Globus Web Auth Plan

This note records the first implementation decision for the web prototype.

## Decision

Use a new Globus Auth application registration for this web app, separate from the CLI prototype's native/thick-client registration.

Register it as a Portal / Science Gateway style application. Do not mark it as a native app if it will run as a server-side Flask web app that can keep a client secret.

## Local Redirect URI

For local development, register this redirect URI:

```text
http://localhost:5000/callback
```

Globus requires registered redirect URIs to match the redirect sent during OAuth. The official docs require HTTPS redirects in general, with an exception for `http://localhost/*` during development and testing.

## Values Needed From Globus Registration

The app will need these values, but they must not be committed with real secrets:

```text
GLOBUS_CLIENT_ID=<web-app-client-id>
GLOBUS_CLIENT_SECRET=<web-app-client-secret>
GLOBUS_REDIRECT_URI=http://localhost:5000/callback
```

The client secret belongs in local environment configuration only.

## First OAuth Flow

The first Flask implementation should stay minimal:

1. `/login` creates an authorization URL and redirects the user to Globus.
2. Globus redirects back to `/callback` with `code` and `state`.
3. `/callback` verifies `state`.
4. The app exchanges `code` for tokens using the web app client credentials.
5. The app stores the Transfer API access token in the Flask session for the prototype.

The first requested Transfer scope should be:

```text
urn:globus:auth:scope:transfer.api.globus.org:all
```

Source collection data-access consent can be requested proactively or handled after a consent-required response. The CLI prototype already demonstrates both the source collection scope pattern and retry-after-consent behavior.

## Official References

- Globus Auth Developer Guide: https://docs.globus.org/api/auth/developer-guide/
- Globus Transfer API Overview: https://docs.globus.org/api/transfer/overview/
- Globus Transfer Task Submission: https://docs.globus.org/api/transfer/task_submit/

## Current Non-Goals

- No MYA archive integration yet.
- No transfer submission yet.
- No persistent token database yet.
- No production deployment configuration yet.

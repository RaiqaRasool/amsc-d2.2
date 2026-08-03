# Globus Authentication Design

This document records the current Globus authentication, consent, and token
storage design for the web prototype.

## Application Registration

The Flask server uses a Globus confidential client registration because it can
keep a client secret. This registration should remain separate from any native
or CLI application registration.

The required local configuration is:

```text
GLOBUS_CLIENT_ID=<confidential-client-id>
GLOBUS_CLIENT_SECRET=<confidential-client-secret>
GLOBUS_REDIRECT_URI=http://localhost:5000/callback
```

Never commit the client secret. For local development, register this exact
redirect URI with Globus:

```text
http://localhost:5000/callback
```

Production deployments must register their deployed callback URI and use HTTPS.

## OAuth Flow

1. `/login` generates an OAuth state value and starts the confidential-client
   authorization-code flow.
2. The authorization request includes the Globus Transfer scope and requests
   refresh tokens.
3. Globus redirects the browser to `/callback` with an authorization code and
   the original state.
4. `/callback` validates and consumes the state before exchanging the code.
   State values are limited to 128 characters and authorization codes to 2,048
   characters. Invalid callbacks return a generic response without diagnostics.
5. The complete token response is stored in server-side SDK-managed SQLite
   token storage under a generated namespace.
6. Flask stores that namespace as `token_reference` in the session. Jobs copy
   the reference into their durable job record when they are queued.

The Flask session contains only the opaque token-storage reference. OAuth
access and refresh tokens are never written to Flask's browser-side session
cookie. Web and background requests both load authorization from server-side
token storage.

## Scopes and Collection Consent

The base authorization request uses the Globus Transfer `all` scope:

```text
urn:globus:auth:scope:transfer.api.globus.org:all
```

Some collections require an additional collection `data_access` scope. When a
collection browse request returns a consent-required response, the app records
the collection ID, sends the user through Globus Auth again with that dependent
scope, and resumes the original browse request afterward.

Query-and-transfer jobs require a durable `token_reference` before queueing so
the worker can authorize a later transfer after the browser request has ended.

## Server-Side Token Storage

Globus tokens are stored separately from application jobs:

```text
instance/globus-tokens.sqlite3
```

`globus_sdk.token_storage.SQLiteTokenStorage` owns this database. Each login is
stored under a generated namespace, and only that namespace is copied into the
Flask session and job database.

The worker and monitor use the namespace to load the stored Transfer refresh
token and construct a `RefreshTokenAuthorizer`. Refreshed token responses are
written back to the same SDK-managed storage automatically.

The web service uses the same reference-based client construction for
collection searches and browsing. There is no browser-session access-token
fallback.

The Jobs API removes `token_reference` from serialized responses.

## Service Responsibilities

- **web** starts OAuth, handles callbacks and reactive consent, stores tokens,
  and attaches token references to transfer jobs.
- **worker** uses the stored authorization to submit requested transfers.
- **monitor** uses the stored authorization to inspect submitted Globus tasks.

No background service imports Flask session state.

## Prototype Limitations

The following are acceptable for local development but require hardening before
production deployment:

- OAuth state values are held in process memory. They are lost on restart and
  are not shared across multiple web processes.
- Token database access depends on host filesystem permissions rather than a
  dedicated secrets service or encrypted database.
- Flask's development server and debug mode are not production deployment
  configurations.

## Official References

- Globus Auth Developer Guide: https://docs.globus.org/api/auth/developer-guide/
- Globus Transfer API Overview: https://docs.globus.org/api/transfer/overview/
- Globus Transfer task submission: https://docs.globus.org/api/transfer/task_submit/
- Globus Python SDK authorization guide: https://globus-sdk-python.readthedocs.io/en/stable/authorization.html

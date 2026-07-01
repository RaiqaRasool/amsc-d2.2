# MYA Transfer Jobs

This note records the intended product-shaped flow for combining an MYA query and
a Globus transfer into one durable request.

## Goal

Allow a user to submit one request that includes:

- MYA query parameters
- Globus destination collection
- Globus destination path

The server should create a job, run the MYA query, submit the generated export to
Globus, and let the user leave the page while status remains visible later.

## Authorization Before Queueing

A job should not enter `queued` until the app has Globus authorization that can
submit the eventual transfer.

In the browser flow, the app should try to satisfy missing consent before the
job is created. If the user lacks required rights for the selected source or
destination, the app should redirect them through Globus Auth immediately and
only create the job after they return successfully.

Before queueing, the app should know:

- the source collection ID
- the destination collection ID
- the destination path
- the required Globus Transfer scope
- the required source and destination collection `data_access` scopes
- which authenticated Globus identity owns the request
- how the server will access a valid Globus token when the transfer is submitted

If the current authorization is missing required collection consent, the app
should send the user through Globus Auth first, then resume job creation after
consent is granted.

This is required because the transfer may be submitted after the user leaves the
page. The worker cannot depend on browser session state alone at transfer time.

For the main browser path, this means `queued` should be the first normal
persisted job state.

## Token Lifetime

The design should assume that a Globus access token may expire before a long MYA
query finishes.

The app should not treat access tokens as durable job credentials. Instead, it
should treat them as short-lived credentials that can be refreshed when the job
needs to submit or inspect a transfer.

The important product rule is:

- request `offline_access` during Globus login
- store a server-side refresh token reference for the job owner
- refresh the access token when later job steps need Globus

This avoids tying long-running jobs to the lifetime of the browser session or
the original access token.

Refresh tokens are the long-lived mechanism. Access-token lifetime may vary, so
the job system should rely on the returned expiration metadata instead of
assuming one fixed duration.

## First Shape

The HTTP request should create a job and return a job ID quickly instead of
waiting for the query and transfer to finish.

```text
POST /mya-transfer-requests
GET  /mya-transfer-requests
GET  /mya-transfer-requests/<job_id>
```

## Job State

Each job should store enough information to reconstruct progress:

- job ID
- user identity
- Globus identity ID or username
- MYA query parameters
- source collection ID
- destination collection ID
- destination path
- required Globus scopes
- server-side Globus token reference
- access token expiration metadata
- generated source path
- Globus transfer task ID
- status
- error message
- created and updated timestamps

Useful statuses:

```text
queued
query_running
query_failed
query_complete
transfer_submitting
transfer_auth_failed
transfer_submitted
transfer_active
transfer_succeeded
transfer_failed
expired_authorization
```

`auth_required` can still exist later for interrupted API-driven flows if
needed, but it should not be the normal browser-state entry point.

## Important Boundary

The app owns the MYA query, export creation, and Globus transfer submission.
Globus owns the actual transfer after submission. Once a Globus task ID exists,
the app can refresh status by asking Globus for that task.

## Implementation Direction

Start with persistent job records before adding worker infrastructure. A later
step can move query and transfer work into a background worker without changing
the user-facing job model.

The first real implementation should already use server-side job storage because
users are expected to leave and come back later or query status directly via
API.

The main simplification in the first slice should be execution strategy, not job
storage. In other words:

- the job record should be durable from day one
- the combined route and status endpoint should be real from day one
- the internal query and transfer execution may stay simple at first
- background workers, retries, and periodic refresh can come later

Token storage can be phased depending on how quickly the flow moves from
immediate submission to true background execution, but the long-term direction
is server-side durable token handling.

## Suggested Phases

Keep this as a sequence of small steps instead of one large redesign.

1. Define the durable job model and status lifecycle.
2. Add auth/consent checks before job creation for the combined request flow.
3. Add a combined request endpoint that creates one durable MYA transfer job
   record.
4. Keep the actual query and transfer path simple at first, even if submission
   still happens in the request path after the job is created.
5. Move token handling to fully server-side durable storage as background
   execution becomes real.
6. Move query and transfer submission into background execution.
7. Add job-history and job-status views so users can leave and come back.
8. Add periodic Globus task refresh for submitted transfers.

## What The First Slice Achieves

The first slice is meant to make the app look like a job system from the
outside, even if the inside is still simple.

That first slice should give us:

- one combined submit route
- one durable server-side job record
- one status endpoint
- one stable status lifecycle for the UI or direct API clients

The first slice does not need to solve everything at once:

- it does not need a full worker system
- it does not need retries yet
- it does not need periodic Globus refresh yet
- it does not need the final token-storage architecture on day one

## First Product-Shaped Contract

Even before full background execution exists, the app should move toward this
API shape:

```text
POST /mya-transfer-requests
  creates a job and returns quickly

GET /mya-transfer-requests
  lists recent jobs for the current user

GET /mya-transfer-requests/<job_id>
  returns detailed status for one job
```

The eventual `POST` response should be product-shaped even if the backend is
still evolving internally:

```json
{
  "job_id": "abc123",
  "status": "queued"
}
```

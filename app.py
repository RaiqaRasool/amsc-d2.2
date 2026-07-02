import json
import os
import posixpath
import secrets
import sqlite3
import uuid
from datetime import datetime
from urllib.parse import quote

import globus_sdk
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from globus_sdk.exc import GlobusAPIError
from globus_sdk.scopes import GCSCollectionScopes, TransferScopes
from globus_sdk.token_storage import SQLiteTokenStorage

from mya_query import run_mysampler

load_dotenv()

TRANSFER_RESOURCE_SERVER = "transfer.api.globus.org"
TRANSFER_LABEL_PREFIX = "AmSC MYA Delivery - "
MYA_OUTPUT_DIR = "/mya-output"

# ponytail: in-memory state store for local dev; use server-side session storage
# if this runs with multiple processes or restarts between login and callback.
PENDING_OAUTH_STATES = set()


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


app = Flask(__name__)
app.secret_key = required_env("FLASK_SECRET_KEY")
os.makedirs(app.instance_path, exist_ok=True)
JOBS_DB_PATH = os.environ.get(
    "JOBS_DB_PATH",
    os.path.join(app.instance_path, "mya-transfer-jobs.sqlite3"),
)
TOKEN_DB_PATH = os.environ.get(
    "TOKEN_DB_PATH",
    os.path.join(app.instance_path, "globus-tokens.sqlite3"),
)


def jobs_db():
    connection = sqlite3.connect(JOBS_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_jobs_db():
    with jobs_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mya_transfer_jobs (
                job_id TEXT PRIMARY KEY,
                user_identity TEXT,
                globus_identity TEXT,
                query_type TEXT NOT NULL,
                query_params TEXT NOT NULL,
                source_collection_id TEXT,
                source_path TEXT,
                destination_collection_id TEXT,
                destination_collection_name TEXT,
                destination_path TEXT,
                transfer_label TEXT,
                transfer_requested INTEGER NOT NULL DEFAULT 0,
                required_scopes TEXT,
                token_reference TEXT,
                access_token_expires_at TEXT,
                globus_task_id TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(mya_transfer_jobs)")
        }
        if "destination_collection_name" not in columns:
            connection.execute(
                "ALTER TABLE mya_transfer_jobs "
                "ADD COLUMN destination_collection_name TEXT"
            )
        if "transfer_label" not in columns:
            connection.execute(
                "ALTER TABLE mya_transfer_jobs ADD COLUMN transfer_label TEXT"
            )
        if "transfer_requested" not in columns:
            connection.execute(
                "ALTER TABLE mya_transfer_jobs "
                "ADD COLUMN transfer_requested INTEGER NOT NULL DEFAULT 0"
            )


def job_row(row):
    if row is None:
        return None
    job = dict(row)
    job["query_params"] = json.loads(job["query_params"])
    job["transfer_requested"] = bool(job["transfer_requested"])
    return job


def create_job(
    *,
    job_id,
    status,
    query_type,
    query_params,
    user_identity=None,
    globus_identity=None,
    source_collection_id=None,
    source_path=None,
    destination_collection_id=None,
    destination_collection_name=None,
    destination_path=None,
    transfer_label=None,
    transfer_requested=False,
    required_scopes=None,
    token_reference=None,
    access_token_expires_at=None,
    globus_task_id=None,
    error_message=None,
):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with jobs_db() as connection:
        connection.execute(
            """
            INSERT INTO mya_transfer_jobs (
                job_id,
                user_identity,
                globus_identity,
                query_type,
                query_params,
                source_collection_id,
                source_path,
                destination_collection_id,
                destination_collection_name,
                destination_path,
                transfer_label,
                transfer_requested,
                required_scopes,
                token_reference,
                access_token_expires_at,
                globus_task_id,
                status,
                error_message,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_identity,
                globus_identity,
                query_type,
                json.dumps(query_params, sort_keys=True),
                source_collection_id,
                source_path,
                destination_collection_id,
                destination_collection_name,
                destination_path,
                transfer_label,
                int(transfer_requested),
                required_scopes,
                token_reference,
                access_token_expires_at,
                globus_task_id,
                status,
                error_message,
                now,
                now,
            ),
        )
    return get_job(job_id)


def get_job(job_id):
    with jobs_db() as connection:
        row = connection.execute(
            "SELECT * FROM mya_transfer_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return job_row(row)


def list_jobs(limit=20):
    with jobs_db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [job_row(row) for row in rows]


def list_refreshable_transfer_jobs():
    with jobs_db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            WHERE globus_task_id IS NOT NULL
              AND (
                status NOT IN ('transfer_succeeded', 'transfer_failed')
                OR destination_collection_name IS NULL
                OR transfer_label IS NULL
              )
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [job_row(row) for row in rows]


def claim_next_job():
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with jobs_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT * FROM mya_transfer_jobs
            WHERE status = 'queued'
            ORDER BY created_at
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None

        connection.execute(
            """
            UPDATE mya_transfer_jobs
            SET status = 'query_running', updated_at = ?
            WHERE job_id = ? AND status = 'queued'
            """,
            (now, row["job_id"]),
        )
        claimed_row = connection.execute(
            "SELECT * FROM mya_transfer_jobs WHERE job_id = ?",
            (row["job_id"],),
        ).fetchone()
    return job_row(claimed_row)


def update_job(job_id, **fields):
    if not fields:
        return get_job(job_id)

    fields["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [job_id]

    with jobs_db() as connection:
        connection.execute(
            f"UPDATE mya_transfer_jobs SET {assignments} WHERE job_id = ?",
            values,
        )
    return get_job(job_id)


def execute_mya_query(job):
    query_params = job["query_params"]
    try:
        data = run_mysampler(
            datetime.fromisoformat(query_params["start"]),
            int(query_params["interval"]),
            int(query_params["num_samples"]),
            query_params["pvlist"],
        )
        filename = f"mya-{uuid.uuid4()}.csv"
        output_path = os.path.join(MYA_OUTPUT_DIR, filename)
        source_path = posixpath.join(
            required_env("SOURCE_DIRECTORY").rstrip("/") or "/",
            filename,
        )
        os.makedirs(MYA_OUTPUT_DIR, exist_ok=True)
        data.to_csv(output_path)
    except Exception as error:
        return update_job(
            job["job_id"],
            status="query_failed",
            error_message=f"MYA query failed: {error}",
        )

    completed_job = update_job(
        job["job_id"],
        source_path=source_path,
        status="query_complete",
        error_message=None,
    )
    completed_job["row_count"] = len(data)
    return completed_job


init_jobs_db()


def auth_client():
    return globus_sdk.ConfidentialAppAuthClient(
        required_env("GLOBUS_CLIENT_ID"),
        required_env("GLOBUS_CLIENT_SECRET"),
    )


def transfer_client(token_reference=None):
    token_reference = token_reference or session.get("token_reference")
    if token_reference:
        storage = SQLiteTokenStorage(TOKEN_DB_PATH, namespace=token_reference)
        token_data = storage.get_token_data(TRANSFER_RESOURCE_SERVER)
        if token_data and token_data.refresh_token:
            authorizer = globus_sdk.RefreshTokenAuthorizer(
                token_data.refresh_token,
                auth_client(),
                access_token=token_data.access_token,
                expires_at=token_data.expires_at_seconds,
                on_refresh=storage.store_token_response,
            )
            return globus_sdk.TransferClient(authorizer=authorizer)

    if not has_request_context():
        return None
    access_token = session.get("transfer_access_token")
    if not access_token:
        return None
    authorizer = globus_sdk.AccessTokenAuthorizer(access_token)
    return globus_sdk.TransferClient(authorizer=authorizer)


def requested_transfer_scope(destination_collection_ids=None):
    if not destination_collection_ids:
        return TransferScopes.all
    data_access_scopes = [
        GCSCollectionScopes(collection_id).data_access
        for collection_id in destination_collection_ids
    ]
    return TransferScopes.all.with_dependencies(data_access_scopes)


def child_path(parent_path, name):
    return posixpath.join(parent_path.rstrip("/") or "/", name)


def collection_browse_error(error):
    message = error.message or "The collection did not respond."
    if any(
        phrase in message.lower()
        for phrase in ("not connected", "offline", "timed out", "unavailable")
    ):
        return (
            "This collection is currently unavailable. If it is on a personal "
            "computer, make sure Globus Connect Personal is running, then try again."
        )
    if error.code == "OperationPaused":
        return f"This collection is currently paused. {message}"
    return f"Globus could not browse this collection. {message}"


def destination_file_path(destination_folder, source_path):
    filename = posixpath.basename(source_path.rstrip("/"))
    return posixpath.join(destination_folder.rstrip("/") or "/", filename)


def transfer_label(user_label):
    user_label = user_label.strip()
    if not user_label:
        user_label = "Transfer"
    if user_label.startswith(TRANSFER_LABEL_PREFIX):
        return user_label
    return f"{TRANSFER_LABEL_PREFIX}{user_label}"


def transfer_error_message(error):
    if error.code == "NotLicensedException":
        return (
            "Globus could not submit this transfer because transfers between two "
            "unsubscribed Globus Connect Personal collections require membership "
            "in a Globus subscription group. Choose a Globus Connect Server "
            "collection or use a subscribed account."
        )

    message = error.message or "Globus could not submit the transfer."
    if error.request_id:
        return f"{message} Globus request ID: {error.request_id}"
    return message


def task_source_collection_id(task):
    return task.get("source_endpoint_id", task.get("source_endpoint"))


def app_transfer_status(task):
    status = task.get("status", "UNKNOWN")
    failed = int(task.get("subtasks_failed", 0) or 0)

    if status == "FAILED":
        return "FAILED"
    if status == "SUCCEEDED":
        return "SUCCEEDED"
    if status == "ACTIVE" and failed:
        return "ACTIVE WITH ERRORS"
    if status == "ACTIVE":
        return "IN PROGRESS"
    if status == "INACTIVE":
        return "QUEUED"
    return status


def job_transfer_status(task):
    return "transfer_" + app_transfer_status(task).lower().replace(" ", "_")


def status_class(app_status):
    return "status-" + app_status.lower().replace(" ", "-").replace("_", "-")


def transfer_row(task):
    app_status = app_transfer_status(task)
    return {
        **task,
        "app_status": app_status,
        "status_class": status_class(app_status),
    }


def app_transfers(client):
    source_collection_id = required_env("SOURCE_COLLECTION_ID")
    tasks = client.task_list(
        limit=20,
        orderby="request_time DESC",
        filter={
            "type": "TRANSFER",
            "endpoint_id": source_collection_id,
            "label": f"~{TRANSFER_LABEL_PREFIX}*",
        },
    )
    return [
        transfer_row(task)
        for task in tasks
        if task_source_collection_id(task) == source_collection_id
    ]


def globus_file_manager_url(collection_id, path):
    if not collection_id or not path:
        return None
    return (
        "https://app.globus.org/file-manager"
        f"?origin_id={quote(collection_id)}"
        f"&origin_path={quote(path, safe='')}"
    )


def globus_task_url(task_id):
    if not task_id:
        return None
    return f"https://app.globus.org/activity/{quote(task_id, safe='')}"


def submit_transfer_for_job(
    client,
    *,
    job_id,
    source_collection_id,
    source_path,
    destination_collection_id,
    destination_collection_name,
    destination_folder,
    transfer_label_value,
):
    destination_path = destination_file_path(destination_folder, source_path)
    resolved_transfer_label = transfer_label(transfer_label_value)
    task_data = globus_sdk.TransferData(
        source_endpoint=source_collection_id,
        destination_endpoint=destination_collection_id,
        label=resolved_transfer_label,
    )
    task_data["store_base_path_info"] = True
    task_data.add_item(source_path, destination_path)

    try:
        response = client.submit_transfer(task_data)
    except GlobusAPIError as error:
        if job_id:
            update_job(
                job_id,
                destination_collection_id=destination_collection_id,
                destination_collection_name=destination_collection_name,
                destination_path=destination_path,
                transfer_label=resolved_transfer_label,
                status="transfer_failed",
                error_message=transfer_error_message(error),
            )
        return None, transfer_error_message(error)

    if job_id:
        update_job(
            job_id,
            destination_collection_id=destination_collection_id,
            destination_collection_name=destination_collection_name,
            destination_path=destination_path,
            transfer_label=resolved_transfer_label,
            globus_task_id=response["task_id"],
            status="transfer_submitted",
            error_message=None,
        )
    return response, None


def execute_job_transfer(job):
    if not job.get("transfer_requested"):
        return job
    required_fields = (
        "source_collection_id",
        "source_path",
        "destination_collection_id",
        "destination_path",
    )
    if any(not job.get(field) for field in required_fields):
        return update_job(
            job["job_id"],
            status="transfer_failed",
            error_message="Job is missing required transfer details.",
        )
    if not job.get("token_reference"):
        return update_job(
            job["job_id"],
            status="transfer_auth_failed",
            error_message="No durable Globus authorization is available.",
        )

    client = transfer_client(job["token_reference"])
    if client is None:
        return update_job(
            job["job_id"],
            status="transfer_auth_failed",
            error_message="Stored Globus authorization is unavailable.",
        )

    update_job(job["job_id"], status="transfer_submitting", error_message=None)
    submit_transfer_for_job(
        client,
        job_id=job["job_id"],
        source_collection_id=job["source_collection_id"],
        source_path=job["source_path"],
        destination_collection_id=job["destination_collection_id"],
        destination_collection_name=job["destination_collection_name"],
        destination_folder=job["destination_path"],
        transfer_label_value=job["transfer_label"] or "",
    )
    return get_job(job["job_id"])


def job_for_display(job):
    if job is None:
        return None
    display_job = dict(job)
    display_job["status_class"] = status_class(display_job["status"])
    source_path = display_job.get("source_path")
    destination_path = display_job.get("destination_path")
    display_job["export_name"] = (
        posixpath.basename(source_path) if source_path else None
    )
    display_job["export_url"] = (
        globus_file_manager_url(
            display_job.get("source_collection_id"),
            posixpath.dirname(source_path) or "/",
        )
        if source_path
        else None
    )
    display_job["destination_url"] = (
        globus_file_manager_url(
            display_job.get("destination_collection_id"),
            posixpath.dirname(destination_path) or "/",
        )
        if destination_path
        else None
    )
    display_job["task_url"] = globus_task_url(display_job.get("globus_task_id"))
    return display_job


def job_for_api(job):
    api_job = dict(job)
    api_job.pop("token_reference", None)
    return api_job


@app.get("/")
def index():
    client = transfer_client()
    latest_job_id = session.get("latest_job_id")
    latest_job = job_for_display(get_job(latest_job_id)) if latest_job_id else None
    return render_template(
        "index.html",
        logged_in=session.get("logged_in"),
        destination_collection_id=session.get("destination_collection_id"),
        destination_collection_name=session.get("destination_collection_name"),
        destination_path=session.get("destination_path"),
        jobs=[job_for_display(job) for job in list_jobs()],
        source_path=session.get("source_path"),
        latest_job=latest_job,
        latest_export_name=latest_job.get("export_name") if latest_job else None,
        latest_export_url=latest_job.get("export_url") if latest_job else None,
        transfers=app_transfers(client) if client is not None else [],
    )


@app.get("/login")
def login():
    state = secrets.token_urlsafe(32)
    PENDING_OAUTH_STATES.add(state)

    client = auth_client()
    client.oauth2_start_flow(
        redirect_uri=required_env("GLOBUS_REDIRECT_URI"),
        requested_scopes=requested_transfer_scope(
            session.get("consent_collection_ids")
        ),
        refresh_tokens=True,
        state=state,
    )
    return redirect(client.oauth2_get_authorize_url())


@app.get("/callback")
def callback():
    returned_state = request.args.get("state")
    if not returned_state or returned_state not in PENDING_OAUTH_STATES:
        return (
            "Invalid OAuth state. "
            f"returned_state_present={returned_state is not None} "
            f"known_state={returned_state in PENDING_OAUTH_STATES}"
        ), 400
    PENDING_OAUTH_STATES.remove(returned_state)

    code = request.args.get("code")
    if not code:
        return "Missing OAuth code.", 400

    client = auth_client()
    client.oauth2_start_flow(
        redirect_uri=required_env("GLOBUS_REDIRECT_URI"),
        requested_scopes=requested_transfer_scope(
            session.get("consent_collection_ids")
        ),
        refresh_tokens=True,
        state=returned_state,
    )
    token_response = client.oauth2_exchange_code_for_tokens(code)
    transfer_tokens = token_response.by_resource_server[TRANSFER_RESOURCE_SERVER]
    token_reference = uuid.uuid4().hex
    token_storage = SQLiteTokenStorage(TOKEN_DB_PATH, namespace=token_reference)
    token_storage.store_token_response(token_response)
    token_storage.close()

    session["logged_in"] = True
    session["transfer_access_token"] = transfer_tokens["access_token"]
    session["transfer_access_token_expires_at"] = transfer_tokens[
        "expires_at_seconds"
    ]
    session["token_reference"] = token_reference

    session.pop("consent_collection_ids", None)
    return redirect(session.pop("post_auth_redirect", url_for("index")))


@app.get("/collections/search")
def search_collections():
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()
    if not query:
        return redirect(url_for("index"))

    results = list(
        client.endpoint_search(filter_fulltext=query, filter_non_functional=False)
    )[:10]
    return render_template("collection_search.html", query=query, results=results)


@app.post("/mya/query")
def query_mya():
    if transfer_client() is None:
        return redirect(url_for("login"))

    try:
        start = datetime.fromisoformat(request.form.get("start", ""))
        interval = int(request.form.get("interval", ""))
        num_samples = int(request.form.get("num_samples", ""))
        pvlist = [
            pv.strip()
            for pv in request.form.get("pvlist", "").split(",")
            if pv.strip()
        ]
        if interval <= 0 or num_samples <= 0 or not pvlist:
            raise ValueError
    except ValueError:
        return "Invalid MYA query parameters.", 400

    transfer_requested = request.form.get("submit_action") == "query_and_transfer"
    destination_collection_id = session.get("destination_collection_id")
    destination_collection_name = session.get("destination_collection_name")
    destination_folder = session.get("destination_path")
    transfer_label_value = request.form.get("transfer_label", "")
    if transfer_requested and (
        not destination_collection_id or not destination_folder
    ):
        flash("Choose a destination folder before running query and transfer.", "error")
        return redirect(url_for("index"))
    if transfer_requested and not session.get("token_reference"):
        flash(
            "Sign in again before queueing a background Globus transfer.",
            "error",
        )
        session["post_auth_redirect"] = url_for("index")
        return redirect(url_for("login"))

    job_id = str(uuid.uuid4())
    create_job(
        job_id=job_id,
        status="queued",
        query_type="mysampler",
        query_params={
            "start": start.isoformat(),
            "interval": interval,
            "num_samples": num_samples,
            "pvlist": pvlist,
        },
        source_collection_id=required_env("SOURCE_COLLECTION_ID"),
        destination_collection_id=(
            destination_collection_id if transfer_requested else None
        ),
        destination_collection_name=(
            destination_collection_name if transfer_requested else None
        ),
        destination_path=destination_folder if transfer_requested else None,
        transfer_label=(
            transfer_label(transfer_label_value) if transfer_requested else None
        ),
        transfer_requested=transfer_requested,
        token_reference=session.get("token_reference"),
        access_token_expires_at=session.get("transfer_access_token_expires_at"),
    )
    session["latest_job_id"] = job_id
    session.pop("source_path", None)
    flash(f"MYA job queued: {job_id}", "success")
    return redirect(url_for("index"))


@app.get("/collections/<collection_id>/browse")
def browse_collection(collection_id):
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    path = request.args.get("path", "/").strip() or "/"
    if not path.startswith("/"):
        path = "/" + path

    browse_error = None
    try:
        entries = list(client.operation_ls(collection_id, path=path))
    except GlobusAPIError as error:
        if error.info.consent_required:
            collection_ids = session.get("consent_collection_ids", [])
            if collection_id not in collection_ids:
                session["consent_collection_ids"] = collection_ids + [collection_id]
            session["post_auth_redirect"] = url_for(
                "browse_collection",
                collection_id=collection_id,
                path=path,
            )
            return redirect(url_for("login"))
        entries = []
        browse_error = collection_browse_error(error)
    parent_path = posixpath.dirname(path.rstrip("/")) or "/"

    return render_template(
        "collection_browse.html",
        collection_id=collection_id,
        path=path,
        parent_path=parent_path,
        entries=entries,
        browse_error=browse_error,
        child_path=child_path,
    )


@app.post("/destination/select")
def select_destination():
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    collection_id = request.form.get("collection_id", "").strip()
    path = request.form.get("path", "").strip() or "/"
    if not collection_id:
        return "Missing destination collection.", 400
    if not path.startswith("/"):
        path = "/" + path

    collection = client.get_endpoint(
        collection_id,
        query_params={"fields": "display_name,canonical_name"},
    )
    session["destination_collection_id"] = collection_id
    session["destination_collection_name"] = (
        collection.get("display_name")
        or collection.get("canonical_name")
        or "Unknown collection"
    )
    session["destination_path"] = path

    return redirect(url_for("index"))


@app.post("/destination/reset")
def reset_destination():
    session.pop("destination_collection_id", None)
    session.pop("destination_collection_name", None)
    session.pop("destination_path", None)
    return redirect(url_for("index"))


@app.post("/transfer/submit")
def submit_transfer():
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    job_id = session.get("latest_job_id")
    source_collection_id = required_env("SOURCE_COLLECTION_ID")
    source_path = session.get("source_path")
    destination_collection_id = session.get("destination_collection_id")
    destination_folder = session.get("destination_path")
    if not source_path:
        return "Run a MYA query before submitting a transfer.", 400
    if not destination_collection_id or not destination_folder:
        return "Choose a destination folder before submitting a transfer.", 400

    _, transfer_error = submit_transfer_for_job(
        client,
        job_id=job_id,
        source_collection_id=source_collection_id,
        source_path=source_path,
        destination_collection_id=destination_collection_id,
        destination_collection_name=session.get("destination_collection_name"),
        destination_folder=destination_folder,
        transfer_label_value=request.form.get("transfer_label", ""),
    )
    if transfer_error:
        flash(transfer_error, "error")
        return redirect(url_for("index"))

    return redirect(url_for("index"))


@app.post("/transfers/refresh")
def refresh_transfers():
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    refreshed = 0
    failed = 0
    for job in list_refreshable_transfer_jobs():
        try:
            task = client.get_task(job["globus_task_id"])
        except GlobusAPIError:
            failed += 1
            continue

        fields = {"status": job_transfer_status(task)}
        destination_collection_name = task.get(
            "destination_endpoint_display_name"
        )
        if destination_collection_name:
            fields["destination_collection_name"] = destination_collection_name
        if task.get("label"):
            fields["transfer_label"] = task["label"]
        update_job(job["job_id"], **fields)
        refreshed += 1

    if failed:
        flash(
            f"Refreshed {refreshed} transfer jobs; {failed} status checks failed.",
            "error",
        )
    else:
        flash(f"Refreshed {refreshed} transfer jobs.", "success")
    return redirect(url_for("index"))


@app.get("/jobs/<job_id>")
def job_status(job_id):
    if transfer_client() is None:
        return "", 401

    job = get_job(job_id)
    if job is None:
        return {"error": "Job not found."}, 404
    return jsonify(job_for_api(job))


@app.get("/jobs")
def jobs():
    if transfer_client() is None:
        return "", 401
    return jsonify([job_for_api(job) for job in list_jobs()])


@app.get("/jobs/table")
def jobs_table():
    if not session.get("logged_in"):
        return "", 401
    return render_template(
        "_jobs.html",
        jobs=[job_for_display(job) for job in list_jobs()],
    )


@app.get("/transfers")
def transfers():
    client = transfer_client()
    if client is None:
        return "", 401
    return render_template("_transfers.html", transfers=app_transfers(client))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_RUN_PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )

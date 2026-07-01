import json
import os
import posixpath
import secrets
import sqlite3
import uuid
from datetime import datetime

import globus_sdk
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from globus_sdk.exc import GlobusAPIError
from globus_sdk.scopes import GCSCollectionScopes, TransferScopes

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
                destination_path TEXT,
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


def job_row(row):
    if row is None:
        return None
    job = dict(row)
    job["query_params"] = json.loads(job["query_params"])
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
    destination_path=None,
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
                destination_path,
                required_scopes,
                token_reference,
                access_token_expires_at,
                globus_task_id,
                status,
                error_message,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                destination_path,
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


init_jobs_db()


def auth_client():
    return globus_sdk.ConfidentialAppAuthClient(
        required_env("GLOBUS_CLIENT_ID"),
        required_env("GLOBUS_CLIENT_SECRET"),
    )


def transfer_client():
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


def status_class(app_status):
    return "status-" + app_status.lower().replace(" ", "-")


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


@app.get("/")
def index():
    client = transfer_client()
    return render_template(
        "index.html",
        logged_in=session.get("logged_in"),
        destination_collection_id=session.get("destination_collection_id"),
        destination_collection_name=session.get("destination_collection_name"),
        destination_path=session.get("destination_path"),
        source_path=session.get("source_path"),
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
        state=returned_state,
    )
    token_response = client.oauth2_exchange_code_for_tokens(code)
    transfer_tokens = token_response.by_resource_server[TRANSFER_RESOURCE_SERVER]

    session["logged_in"] = True
    session["transfer_access_token"] = transfer_tokens["access_token"]

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

    try:
        data = run_mysampler(start, interval, num_samples, pvlist)
    except Exception as error:
        flash(f"MYA query failed: {error}", "error")
        return redirect(url_for("index"))

    job_id = str(uuid.uuid4())
    filename = f"mya-{uuid.uuid4()}.csv"
    output_path = os.path.join(MYA_OUTPUT_DIR, filename)
    source_path = posixpath.join(
        required_env("SOURCE_DIRECTORY").rstrip("/") or "/",
        filename,
    )
    os.makedirs(MYA_OUTPUT_DIR, exist_ok=True)
    data.to_csv(output_path)
    session["source_path"] = source_path
    session["latest_job_id"] = job_id

    create_job(
        job_id=job_id,
        status="query_complete",
        query_type="mysampler",
        query_params={
            "start": start.isoformat(),
            "interval": interval,
            "num_samples": num_samples,
            "pvlist": pvlist,
        },
        source_collection_id=required_env("SOURCE_COLLECTION_ID"),
        source_path=source_path,
    )

    flash(
        f"MYA export created with {len(data)} rows: {filename} (job {job_id})",
        "success",
    )
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

    label = transfer_label(request.form.get("transfer_label", ""))

    destination_path = destination_file_path(destination_folder, source_path)
    task_data = globus_sdk.TransferData(
        source_endpoint=source_collection_id,
        destination_endpoint=destination_collection_id,
        label=label,
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
                destination_path=destination_path,
                status="transfer_failed",
                error_message=transfer_error_message(error),
            )
        flash(transfer_error_message(error), "error")
        return redirect(url_for("index"))

    if job_id:
        update_job(
            job_id,
            destination_collection_id=destination_collection_id,
            destination_path=destination_path,
            globus_task_id=response["task_id"],
            status="transfer_submitted",
            error_message=None,
        )

    return redirect(url_for("index"))


@app.post("/transfers/refresh")
def refresh_transfers():
    if transfer_client() is None:
        return redirect(url_for("login"))
    return redirect(url_for("index"))


@app.get("/jobs/<job_id>")
def job_status(job_id):
    if transfer_client() is None:
        return "", 401

    job = get_job(job_id)
    if job is None:
        return {"error": "Job not found."}, 404
    return jsonify(job)


@app.get("/jobs")
def jobs():
    if transfer_client() is None:
        return "", 401
    return jsonify(list_jobs())


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

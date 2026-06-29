import os
import posixpath
import secrets

import globus_sdk
from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for
from globus_sdk.scopes import GCSCollectionScopes, TransferScopes

load_dotenv()

TRANSFER_RESOURCE_SERVER = "transfer.api.globus.org"
TRANSFER_LABEL_PREFIX = "AmSC MYA Delivery - "

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


def child_path(parent_path, name):
    return posixpath.join(parent_path.rstrip("/") or "/", name)


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
        destination_path=session.get("destination_path"),
        transfers=app_transfers(client) if client is not None else [],
    )


@app.get("/login")
def login():
    state = secrets.token_urlsafe(32)
    PENDING_OAUTH_STATES.add(state)

    client = auth_client()
    source_data_access = GCSCollectionScopes(required_env("SOURCE_COLLECTION_ID")).data_access
    client.oauth2_start_flow(
        redirect_uri=required_env("GLOBUS_REDIRECT_URI"),
        requested_scopes=TransferScopes.all.with_dependencies([source_data_access]),
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
    source_data_access = GCSCollectionScopes(required_env("SOURCE_COLLECTION_ID")).data_access
    client.oauth2_start_flow(
        redirect_uri=required_env("GLOBUS_REDIRECT_URI"),
        requested_scopes=TransferScopes.all.with_dependencies([source_data_access]),
        state=returned_state,
    )
    token_response = client.oauth2_exchange_code_for_tokens(code)
    transfer_tokens = token_response.by_resource_server[TRANSFER_RESOURCE_SERVER]

    session["logged_in"] = True
    session["transfer_access_token"] = transfer_tokens["access_token"]

    return redirect(url_for("index"))


@app.get("/collections/search")
def search_collections():
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()
    if not query:
        return redirect(url_for("index"))

    results = list(client.endpoint_search(filter_fulltext=query))[:10]
    return render_template("collection_search.html", query=query, results=results)


@app.get("/collections/<collection_id>/browse")
def browse_collection(collection_id):
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    path = request.args.get("path", "/").strip() or "/"
    if not path.startswith("/"):
        path = "/" + path

    entries = list(client.operation_ls(collection_id, path=path))
    parent_path = posixpath.dirname(path.rstrip("/")) or "/"

    return render_template(
        "collection_browse.html",
        collection_id=collection_id,
        path=path,
        parent_path=parent_path,
        entries=entries,
        child_path=child_path,
    )


@app.post("/destination/select")
def select_destination():
    if transfer_client() is None:
        return redirect(url_for("login"))

    collection_id = request.form.get("collection_id", "").strip()
    path = request.form.get("path", "").strip() or "/"
    if not collection_id:
        return "Missing destination collection.", 400
    if not path.startswith("/"):
        path = "/" + path

    session["destination_collection_id"] = collection_id
    session["destination_path"] = path

    return redirect(url_for("index"))


@app.post("/transfer/submit")
def submit_transfer():
    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))

    source_collection_id = required_env("SOURCE_COLLECTION_ID")
    source_path = required_env("SOURCE_PATH")
    destination_collection_id = session.get("destination_collection_id")
    destination_folder = session.get("destination_path")
    if not destination_collection_id or not destination_folder:
        return "Choose a destination folder before submitting a transfer.", 400

    label = transfer_label(request.form.get("transfer_label", ""))

    destination_path = destination_file_path(destination_folder, source_path)
    task_data = globus_sdk.TransferData(
        source_endpoint=source_collection_id,
        destination_endpoint=destination_collection_id,
        label=label,
    )
    task_data.add_item(source_path, destination_path)

    client.submit_transfer(task_data)

    return redirect(url_for("index"))


@app.post("/transfers/refresh")
def refresh_transfers():
    if transfer_client() is None:
        return redirect(url_for("login"))
    return redirect(url_for("index"))


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

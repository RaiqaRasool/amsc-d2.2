import os
import posixpath
import secrets
import uuid
from datetime import datetime

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from globus_sdk.exc import GlobusAPIError

from config import (
    COLLECTION_BROWSE_RATE_LIMITS,
    COLLECTION_SEARCH_RATE_LIMITS,
    LOGIN_RATE_LIMITS,
    MAX_PENDING_JOBS_GLOBAL,
    MAX_PENDING_JOBS_PER_USER,
    MYA_SUBMISSION_RATE_LIMITS,
    required_env,
)
from csrf import CSRF_SESSION_KEY, csrf_tokens_match, new_csrf_token
from globus_service import (
    auth_client,
    globus_file_manager_url,
    globus_task_url,
    requested_auth_scopes,
    revoke_and_delete_token_reference,
    status_class,
    store_token_response,
    transfer_client_from_token_reference,
    transfer_label,
)
from jobs import (
    QueueCapacityError,
    TokenReferenceRetiredError,
    create_job,
    get_job_for_identity,
    list_jobs,
    schedule_token_cleanup,
)
from query_validation import validate_query_params
from rate_limits import RateLimitExceeded, record_request
from token_cleanup import cleanup_token_reference_if_ready
from web_validation import (
    validate_collection_id,
    validate_collection_search,
    validate_destination_path,
    validate_oauth_code,
    validate_oauth_state,
    validate_transfer_label,
)

# ponytail: in-memory state store for local dev; use server-side session storage
# if this runs with multiple processes or restarts between login and callback.
PENDING_OAUTH_STATES = set()

app = Flask(__name__)
app.secret_key = required_env("FLASK_SECRET_KEY")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024


@app.context_processor
def inject_csrf_token():
    if CSRF_SESSION_KEY not in session:
        session[CSRF_SESSION_KEY] = new_csrf_token()
    return {"csrf_token": session[CSRF_SESSION_KEY]}


@app.before_request
def protect_post_requests():
    if request.method == "POST" and not csrf_tokens_match(
        session.get(CSRF_SESSION_KEY),
        request.form.get(CSRF_SESSION_KEY),
    ):
        flash("This form expired or could not be verified. Please try again.", "error")
        return redirect(url_for("index"))


def transfer_client():
    return transfer_client_from_token_reference(session.get("token_reference"))


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


def parse_form_datetime(field_name):
    return datetime.fromisoformat(request.form.get(field_name, ""))


def parse_pvlist(value):
    return [pv.strip() for pv in value.split(",") if pv.strip()]


def rate_limit_response(scope_key, action, limits):
    try:
        record_request(scope_key, action, limits)
    except RateLimitExceeded as error:
        return (
            render_template("429.html", retry_after=error.retry_after),
            429,
            {"Retry-After": str(error.retry_after)},
        )
    return None


@app.get("/")
def index():
    globus_identity = session.get("globus_identity")
    logged_in = bool(session.get("logged_in") and globus_identity)
    return render_template(
        "index.html",
        logged_in=logged_in,
        destination_collection_id=session.get("destination_collection_id"),
        destination_collection_name=session.get("destination_collection_name"),
        destination_path=session.get("destination_path"),
        jobs=[job_for_display(job) for job in list_jobs(globus_identity)],
    )


@app.get("/login")
def login():
    limited = rate_limit_response(
        f"ip:{request.remote_addr or 'unknown'}",
        "login",
        LOGIN_RATE_LIMITS,
    )
    if limited is not None:
        return limited

    state = secrets.token_urlsafe(32)
    PENDING_OAUTH_STATES.add(state)

    client = auth_client()
    client.oauth2_start_flow(
        redirect_uri=required_env("GLOBUS_REDIRECT_URI"),
        requested_scopes=requested_auth_scopes(
            session.get("consent_collection_ids")
        ),
        refresh_tokens=True,
        state=state,
    )
    return redirect(client.oauth2_get_authorize_url())


@app.get("/callback")
def callback():
    returned_state = request.args.get("state")
    try:
        validate_oauth_state(returned_state)
    except ValueError as error:
        return render_template("400.html", message=str(error)), 400
    if returned_state not in PENDING_OAUTH_STATES:
        return render_template(
            "400.html",
            message="Invalid or expired OAuth state.",
        ), 400
    PENDING_OAUTH_STATES.remove(returned_state)

    code = request.args.get("code")
    try:
        validate_oauth_code(code)
    except ValueError as error:
        return render_template("400.html", message=str(error)), 400

    client = auth_client()
    client.oauth2_start_flow(
        redirect_uri=required_env("GLOBUS_REDIRECT_URI"),
        requested_scopes=requested_auth_scopes(
            session.get("consent_collection_ids")
        ),
        refresh_tokens=True,
        state=returned_state,
    )
    token_response = client.oauth2_exchange_code_for_tokens(code)
    identity_claims = token_response.decode_id_token()
    token_reference = store_token_response(token_response)

    session["logged_in"] = True
    session["token_reference"] = token_reference
    session["globus_identity"] = identity_claims["sub"]
    session["user_identity"] = identity_claims.get(
        "preferred_username", identity_claims["sub"]
    )

    session.pop("consent_collection_ids", None)
    return redirect(session.pop("post_auth_redirect", url_for("index")))


@app.get("/collections/search")
def search_collections():
    globus_identity = session.get("globus_identity")
    if not globus_identity or not session.get("token_reference"):
        return redirect(url_for("login"))
    limited = rate_limit_response(
        f"identity:{globus_identity}",
        "collection_search",
        COLLECTION_SEARCH_RATE_LIMITS,
    )
    if limited is not None:
        return limited

    query = request.args.get("q", "").strip()
    try:
        validate_collection_search(query)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("index"))

    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))
    results = list(
        client.endpoint_search(filter_fulltext=query, filter_non_functional=False)
    )[:10]
    return render_template("collection_search.html", query=query, results=results)


@app.post("/mya/query")
def query_mya():
    globus_identity = session.get("globus_identity")
    if transfer_client() is None or not globus_identity:
        return redirect(url_for("login"))
    limited = rate_limit_response(
        f"identity:{globus_identity}",
        "mya_submission",
        MYA_SUBMISSION_RATE_LIMITS,
    )
    if limited is not None:
        return limited

    query_type = request.form.get("query_type", "mysampler").strip().lower()
    try:
        if query_type == "mysampler":
            interval = int(request.form.get("mysampler_interval", ""))
            num_samples = int(request.form.get("mysampler_num_samples", ""))
            pvlist = parse_pvlist(request.form.get("mysampler_pvlist", ""))
            if interval <= 0 or num_samples <= 0 or not pvlist:
                raise ValueError
            query_params = {
                "start": parse_form_datetime("mysampler_start").isoformat(),
                "interval": interval,
                "num_samples": num_samples,
                "pvlist": pvlist,
            }
        elif query_type == "interval":
            begin = parse_form_datetime("interval_begin")
            end = parse_form_datetime("interval_end")
            pvlist = parse_pvlist(request.form.get("interval_pvlist", ""))
            channel = request.form.get("interval_channel", "").strip()
            if end <= begin or (not pvlist and not channel):
                raise ValueError
            query_params = {
                "begin": begin.isoformat(),
                "end": end.isoformat(),
                "prior_point": request.form.get("interval_prior_point") == "true",
                "pvlist": pvlist,
                "channel": channel,
            }
        elif query_type == "mystats":
            start = parse_form_datetime("mystats_start")
            end = parse_form_datetime("mystats_end")
            num_bins = int(request.form.get("mystats_num_bins", ""))
            pvlist = parse_pvlist(request.form.get("mystats_pvlist", ""))
            if end <= start or num_bins <= 0 or not pvlist:
                raise ValueError
            query_params = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "num_bins": num_bins,
                "pvlist": pvlist,
            }
        elif query_type == "point":
            channel = request.form.get("point_channel", "").strip()
            if not channel:
                raise ValueError
            query_params = {
                "channel": channel,
                "time": parse_form_datetime("point_time").isoformat(),
            }
        elif query_type == "channel":
            pattern = request.form.get("channel_pattern", "").strip()
            if not pattern:
                raise ValueError
            query_params = {"pattern": pattern}
        else:
            raise ValueError
        validate_query_params(query_type, query_params)
    except ValueError as error:
        message = str(error) or f"Check the values in the {query_type} query."
        flash(message, "error")
        return redirect(url_for("index"))

    transfer_requested = request.form.get("submit_action") == "query_and_transfer"
    destination_collection_id = session.get("destination_collection_id")
    destination_collection_name = session.get("destination_collection_name")
    destination_folder = session.get("destination_path")
    transfer_label_value = request.form.get("transfer_label", "")
    resolved_transfer_label = None
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
    if transfer_requested:
        try:
            destination_collection_id = validate_collection_id(
                destination_collection_id
            )
            validate_destination_path(destination_folder)
            resolved_transfer_label = transfer_label(transfer_label_value)
            validate_transfer_label(resolved_transfer_label)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("index"))

    job_id = str(uuid.uuid4())
    try:
        create_job(
            job_id=job_id,
            status="queued",
            query_type=query_type,
            query_params=query_params,
            user_identity=session.get("user_identity"),
            globus_identity=globus_identity,
            source_collection_id=required_env("SOURCE_COLLECTION_ID"),
            destination_collection_id=(
                destination_collection_id if transfer_requested else None
            ),
            destination_collection_name=(
                destination_collection_name if transfer_requested else None
            ),
            destination_path=destination_folder if transfer_requested else None,
            transfer_label=resolved_transfer_label,
            transfer_requested=transfer_requested,
            token_reference=session.get("token_reference"),
            max_pending_per_user=MAX_PENDING_JOBS_PER_USER,
            max_pending_global=MAX_PENDING_JOBS_GLOBAL,
        )
    except QueueCapacityError as error:
        if error.scope == "user":
            message = (
                f"You already have {MAX_PENDING_JOBS_PER_USER} MYA jobs pending. "
                "Wait for one to finish before submitting another."
            )
        else:
            message = "The MYA queue is currently at capacity. Please try again later."
        flash(message, "error")
        return redirect(url_for("index"))
    except TokenReferenceRetiredError:
        flash("Sign in again before queueing another transfer.", "error")
        return redirect(url_for("login"))
    flash(f"MYA job queued: {job_id}", "success")
    return redirect(url_for("index"))


@app.get("/collections/<collection_id>/browse")
def browse_collection(collection_id):
    globus_identity = session.get("globus_identity")
    if not globus_identity or not session.get("token_reference"):
        return redirect(url_for("login"))
    limited = rate_limit_response(
        f"identity:{globus_identity}",
        "collection_browse",
        COLLECTION_BROWSE_RATE_LIMITS,
    )
    if limited is not None:
        return limited

    path = request.args.get("path", "/") or "/"
    if not path.startswith("/"):
        path = "/" + path
    try:
        collection_id = validate_collection_id(collection_id)
        validate_destination_path(path)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("index"))

    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))
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
    if not session.get("globus_identity") or not session.get("token_reference"):
        return redirect(url_for("login"))

    collection_id = request.form.get("collection_id", "").strip()
    path = request.form.get("path", "") or "/"
    if not path.startswith("/"):
        path = "/" + path
    try:
        collection_id = validate_collection_id(collection_id)
        validate_destination_path(path)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("index"))

    client = transfer_client()
    if client is None:
        return redirect(url_for("login"))
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


@app.get("/jobs/<job_id>")
def job_status(job_id):
    globus_identity = session.get("globus_identity")
    if transfer_client() is None or not globus_identity:
        return "", 401

    job = get_job_for_identity(job_id, globus_identity)
    if job is None:
        return {"error": "Job not found."}, 404
    return jsonify(job_for_api(job))


@app.get("/jobs")
def jobs():
    globus_identity = session.get("globus_identity")
    if transfer_client() is None or not globus_identity:
        return "", 401
    return jsonify([job_for_api(job) for job in list_jobs(globus_identity)])


@app.get("/jobs/table")
def jobs_table():
    globus_identity = session.get("globus_identity")
    if not session.get("logged_in") or not globus_identity:
        return "", 401
    return render_template(
        "_jobs.html",
        jobs=[job_for_display(job) for job in list_jobs(globus_identity)],
    )


@app.post("/logout")
def logout():
    token_reference = session.get("token_reference")
    if token_reference:
        schedule_token_cleanup(token_reference)
    session.clear()
    if token_reference:
        cleanup_token_reference_if_ready(
            token_reference,
            revoke_and_delete_token_reference,
        )
    return redirect(url_for("index"))


@app.errorhandler(500)
def internal_server_error(error):
    original_error = getattr(error, "original_exception", None)
    if original_error is not None:
        app.logger.error(
            "Unhandled web request exception.",
            exc_info=(
                type(original_error),
                original_error,
                original_error.__traceback__,
            ),
        )
    else:
        app.logger.error("Internal server error: %s", error)
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_RUN_PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )

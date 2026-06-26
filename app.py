import os
import secrets
from html import escape

import globus_sdk
from dotenv import load_dotenv
from flask import Flask, redirect, request, session, url_for
from globus_sdk.scopes import TransferScopes

load_dotenv()

TRANSFER_RESOURCE_SERVER = "transfer.api.globus.org"

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


@app.get("/")
def index():
    if session.get("logged_in"):
        return (
            "<h1>AmSC Globus Data Delivery</h1>"
            "<p>Logged in with Globus.</p>"
            '<form action="/collections/search" method="get">'
            '<label>Destination collection search: '
            '<input name="q" required></label> '
            '<button type="submit">Search</button>'
            "</form>"
            '<p><a href="/logout">Logout</a></p>'
        )

    return (
        "<h1>AmSC Globus Data Delivery</h1>"
        "<p>Not logged in.</p>"
        '<p><a href="/login">Login with Globus</a></p>'
    )


@app.get("/login")
def login():
    state = secrets.token_urlsafe(32)
    PENDING_OAUTH_STATES.add(state)

    client = auth_client()
    client.oauth2_start_flow(
        redirect_uri=required_env("GLOBUS_REDIRECT_URI"),
        requested_scopes=TransferScopes.all,
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
        requested_scopes=TransferScopes.all,
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
    items = "".join(
        "<li>"
        f"<strong>{escape(result.get('display_name', 'Unnamed collection'))}</strong>"
        f"<br><code>{escape(result.get('id', ''))}</code>"
        "</li>"
        for result in results
    )
    if not items:
        items = "<li>No collections found.</li>"

    return (
        "<h1>Collection Search</h1>"
        f"<p>Search: <strong>{escape(query)}</strong></p>"
        f"<ol>{items}</ol>"
        '<p><a href="/">Back</a></p>'
    )


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

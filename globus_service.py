import posixpath
import uuid
from urllib.parse import quote

import globus_sdk
from globus_sdk.exc import GlobusAPIError
from globus_sdk.scopes import AuthScopes, GCSCollectionScopes, TransferScopes
from globus_sdk.token_storage import SQLiteTokenStorage

from config import (
    TOKEN_DB_PATH,
    TRANSFER_LABEL_PREFIX,
    TRANSFER_RESOURCE_SERVER,
    required_env,
)
from jobs import update_job


def auth_client():
    return globus_sdk.ConfidentialAppAuthClient(
        required_env("GLOBUS_CLIENT_ID"),
        required_env("GLOBUS_CLIENT_SECRET"),
    )


def store_token_response(token_response):
    token_reference = uuid.uuid4().hex
    token_storage = SQLiteTokenStorage(TOKEN_DB_PATH, namespace=token_reference)
    token_storage.store_token_response(token_response)
    token_storage.close()
    return token_reference


def revoke_and_delete_token_reference(token_reference):
    token_storage = SQLiteTokenStorage(TOKEN_DB_PATH, namespace=token_reference)
    try:
        token_data_by_resource_server = (
            token_storage.get_token_data_by_resource_server()
        )
        if not token_data_by_resource_server:
            return
        client = auth_client()
        revoked_tokens = set()
        for token_data in token_data_by_resource_server.values():
            for token in (token_data.access_token, token_data.refresh_token):
                if token and token not in revoked_tokens:
                    client.oauth2_revoke_token(token)
                    revoked_tokens.add(token)
        for resource_server in token_data_by_resource_server:
            token_storage.remove_token_data(resource_server)
    finally:
        token_storage.close()


def transfer_client_from_token_reference(token_reference):
    if not token_reference:
        return None

    storage = SQLiteTokenStorage(TOKEN_DB_PATH, namespace=token_reference)
    token_data = storage.get_token_data(TRANSFER_RESOURCE_SERVER)
    if not token_data or not token_data.refresh_token:
        storage.close()
        return None

    authorizer = globus_sdk.RefreshTokenAuthorizer(
        token_data.refresh_token,
        auth_client(),
        access_token=token_data.access_token,
        expires_at=token_data.expires_at_seconds,
        on_refresh=storage.store_token_response,
    )
    return globus_sdk.TransferClient(authorizer=authorizer)


def requested_auth_scopes(destination_collection_ids=None):
    transfer_scope = TransferScopes.all
    if destination_collection_ids:
        data_access_scopes = [
            GCSCollectionScopes(collection_id).data_access
            for collection_id in destination_collection_ids
        ]
        transfer_scope = transfer_scope.with_dependencies(data_access_scopes)
    return [AuthScopes.openid, AuthScopes.profile, transfer_scope]


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

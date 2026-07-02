import json
import os
import posixpath
import uuid

from config import MYA_OUTPUT_DIR, required_env
from globus_service import (
    submit_transfer_for_job,
    transfer_client_from_token_reference,
)
from jobs import get_job, update_job
from mya_query import run_mya_query


def execute_mya_query(job):
    try:
        data = run_mya_query(job["query_type"], job["query_params"])
        extension = "json" if job["query_type"] in ("point", "channel") else "csv"
        filename = f"mya-{uuid.uuid4()}.{extension}"
        output_path = os.path.join(MYA_OUTPUT_DIR, filename)
        source_path = posixpath.join(
            required_env("SOURCE_DIRECTORY").rstrip("/") or "/",
            filename,
        )
        os.makedirs(MYA_OUTPUT_DIR, exist_ok=True)
        if extension == "json":
            with open(output_path, "w") as output_file:
                json.dump(data, output_file, indent=2, default=str)
        else:
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
    completed_job["row_count"] = len(data) if hasattr(data, "__len__") else 1
    return completed_job


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

    client = transfer_client_from_token_reference(job["token_reference"])
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

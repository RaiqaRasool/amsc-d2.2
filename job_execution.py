import os
import posixpath
import uuid
from datetime import datetime

from config import MYA_OUTPUT_DIR, required_env
from globus_service import (
    submit_transfer_for_job,
    transfer_client_from_token_reference,
)
from jobs import get_job, update_job
from mya_query import run_mysampler


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

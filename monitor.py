import os
import time

from globus_sdk.exc import GlobusAPIError

from globus_service import (
    job_transfer_status,
    revoke_and_delete_token_reference,
    transfer_client_from_token_reference,
)
from jobs import list_refreshable_transfer_jobs, update_job
from token_cleanup import cleanup_scheduled_token_references


POLL_INTERVAL_SECONDS = float(os.environ.get("MONITOR_POLL_INTERVAL", "15"))


def refresh_transfer_job(job):
    if not job.get("globus_task_id"):
        return job
    if not job.get("token_reference"):
        raise RuntimeError("Job has no durable Globus authorization.")

    client = transfer_client_from_token_reference(job["token_reference"])
    if client is None:
        raise RuntimeError("Stored Globus authorization is unavailable.")

    task = client.get_task(job["globus_task_id"])
    fields = {"status": job_transfer_status(task)}
    destination_collection_name = task.get("destination_endpoint_display_name")
    if destination_collection_name:
        fields["destination_collection_name"] = destination_collection_name
    if task.get("label"):
        fields["transfer_label"] = task["label"]
    return update_job(job["job_id"], **fields)


def refresh_transfer_jobs():
    for job in list_refreshable_transfer_jobs():
        try:
            refreshed_job = refresh_transfer_job(job)
        except GlobusAPIError as error:
            print(
                f"Globus status check failed for job {job['job_id']}: {error}",
                flush=True,
            )
            continue
        except Exception as error:
            print(
                f"Status monitor failed for job {job['job_id']}: {error}",
                flush=True,
            )
            continue

        if refreshed_job["status"] != job["status"]:
            print(
                f"Job {job['job_id']} changed from {job['status']} "
                f"to {refreshed_job['status']}",
                flush=True,
            )


def main():
    print("Globus transfer monitor started.", flush=True)
    while True:
        refresh_transfer_jobs()
        cleanup_scheduled_token_references(revoke_and_delete_token_reference)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

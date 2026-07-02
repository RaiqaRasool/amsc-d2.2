import os
import time

from job_execution import execute_job_transfer, execute_mya_query
from jobs import claim_next_job, update_job


POLL_INTERVAL_SECONDS = float(os.environ.get("WORKER_POLL_INTERVAL", "2"))


def process_next_job():
    job = claim_next_job()
    if job is None:
        return False

    try:
        completed_job = execute_mya_query(job)
    except Exception as error:
        completed_job = update_job(
            job["job_id"],
            status="query_failed",
            error_message=f"Worker failed: {error}",
        )

    if (
        completed_job["status"] == "query_complete"
        and completed_job["transfer_requested"]
    ):
        try:
            completed_job = execute_job_transfer(completed_job)
        except Exception as error:
            completed_job = update_job(
                job["job_id"],
                status="transfer_failed",
                error_message=f"Worker transfer failed: {error}",
            )

    print(
        f"Job {completed_job['job_id']} finished with "
        f"status {completed_job['status']}",
        flush=True,
    )
    return True


def main():
    print("MYA job worker started.", flush=True)
    while True:
        if not process_next_job():
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

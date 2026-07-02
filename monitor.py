import os
import time

from globus_sdk.exc import GlobusAPIError

from app import list_refreshable_transfer_jobs, refresh_transfer_job


POLL_INTERVAL_SECONDS = float(os.environ.get("MONITOR_POLL_INTERVAL", "15"))


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
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

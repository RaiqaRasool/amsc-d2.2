import os

from dotenv import load_dotenv


load_dotenv()


def positive_int_env(name, default):
    value = int(os.environ.get(name, default))
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

TRANSFER_RESOURCE_SERVER = "transfer.api.globus.org"
TRANSFER_LABEL_PREFIX = "AmSC MYA Delivery - "
MYA_OUTPUT_DIR = "/mya-output"
MYQUERY_PROTOCOL = os.environ.get("MYQUERY_PROTOCOL", "http")
MYQUERY_SERVER = os.environ.get("MYQUERY_SERVER", "myquery:8080")
MYA_DEPLOYMENT = os.environ.get("MYA_DEPLOYMENT", "docker")
WORKER_QUERY_TIMEOUT_SECONDS = positive_int_env("WORKER_QUERY_TIMEOUT_SECONDS", 3600)
MAX_MYA_OUTPUT_BYTES = positive_int_env(
    "MAX_MYA_OUTPUT_BYTES",
    1024 * 1024 * 1024,
)
JOB_RETENTION_DAYS = positive_int_env("JOB_RETENTION_DAYS", 30)
CLEANUP_INTERVAL_SECONDS = positive_int_env("CLEANUP_INTERVAL_SECONDS", 60 * 60)
MAX_PENDING_JOBS_PER_USER = positive_int_env("MAX_PENDING_JOBS_PER_USER", 10)
MAX_PENDING_JOBS_GLOBAL = positive_int_env("MAX_PENDING_JOBS_GLOBAL", 500)
MYA_SUBMISSION_RATE_LIMITS = (
    (positive_int_env("MYA_SUBMISSIONS_PER_MINUTE", 5), 60),
    (positive_int_env("MYA_SUBMISSIONS_PER_HOUR", 30), 60 * 60),
)
COLLECTION_SEARCH_RATE_LIMITS = (
    (positive_int_env("COLLECTION_SEARCHES_PER_MINUTE", 20), 60),
)
COLLECTION_BROWSE_RATE_LIMITS = (
    (positive_int_env("COLLECTION_BROWSES_PER_MINUTE", 60), 60),
)
LOGIN_RATE_LIMITS = (
    (positive_int_env("LOGIN_ATTEMPTS_PER_MINUTE", 10), 60),
)
OAUTH_STATE_TTL_SECONDS = positive_int_env("OAUTH_STATE_TTL_SECONDS", 10 * 60)
JOBS_DB_PATH = os.environ.get(
    "JOBS_DB_PATH",
    os.path.join(INSTANCE_DIR, "mya-transfer-jobs.sqlite3"),
)
RATE_LIMIT_DB_PATH = os.environ.get(
    "RATE_LIMIT_DB_PATH",
    os.path.join(INSTANCE_DIR, "request-rate-limits.sqlite3"),
)
OAUTH_STATE_DB_PATH = os.environ.get(
    "OAUTH_STATE_DB_PATH",
    os.path.join(INSTANCE_DIR, "oauth-states.sqlite3"),
)
TOKEN_DB_PATH = os.environ.get(
    "TOKEN_DB_PATH",
    os.path.join(INSTANCE_DIR, "globus-tokens.sqlite3"),
)


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

import os

from dotenv import load_dotenv


load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

TRANSFER_RESOURCE_SERVER = "transfer.api.globus.org"
TRANSFER_LABEL_PREFIX = "AmSC MYA Delivery - "
MYA_OUTPUT_DIR = "/mya-output"
JOBS_DB_PATH = os.environ.get(
    "JOBS_DB_PATH",
    os.path.join(INSTANCE_DIR, "mya-transfer-jobs.sqlite3"),
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

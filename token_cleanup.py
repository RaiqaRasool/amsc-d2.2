import logging

from jobs import (
    complete_token_cleanup,
    list_pending_token_cleanups,
    token_reference_has_unfinished_transfers,
)


LOGGER = logging.getLogger(__name__)


def cleanup_token_reference_if_ready(token_reference, revoke_and_delete):
    if token_reference_has_unfinished_transfers(token_reference):
        return False
    try:
        revoke_and_delete(token_reference)
    except Exception:
        LOGGER.exception("Could not revoke tokens for a logged-out session.")
        return False
    complete_token_cleanup(token_reference)
    return True


def cleanup_scheduled_token_references(revoke_and_delete):
    cleaned = 0
    for token_reference in list_pending_token_cleanups():
        if cleanup_token_reference_if_ready(token_reference, revoke_and_delete):
            cleaned += 1
    return cleaned

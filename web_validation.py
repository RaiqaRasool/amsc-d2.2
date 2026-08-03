import uuid


MAX_COLLECTION_SEARCH_LENGTH = 128
MAX_DESTINATION_PATH_BYTES = 1024
MAX_TRANSFER_LABEL_LENGTH = 128
MAX_OAUTH_CODE_LENGTH = 2048
MAX_OAUTH_STATE_LENGTH = 128


def contains_control_characters(value):
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def validate_collection_search(value):
    if not value:
        raise ValueError("Enter a collection search term.")
    if len(value) > MAX_COLLECTION_SEARCH_LENGTH:
        raise ValueError(
            f"Collection searches must be {MAX_COLLECTION_SEARCH_LENGTH} "
            "characters or fewer."
        )
    if contains_control_characters(value):
        raise ValueError("Collection searches cannot contain control characters.")
    return value


def validate_collection_id(value):
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Choose a valid Globus collection.") from None
    if len(value) != 36 or str(parsed) != value.lower():
        raise ValueError("Choose a valid Globus collection.")
    return str(parsed)


def validate_destination_path(value):
    try:
        byte_length = len(value.encode("utf-8"))
    except (AttributeError, UnicodeEncodeError):
        raise ValueError("Choose a valid destination path.") from None
    if byte_length > MAX_DESTINATION_PATH_BYTES:
        raise ValueError(
            f"Destination paths must be {MAX_DESTINATION_PATH_BYTES:,} UTF-8 "
            "bytes or fewer."
        )
    if contains_control_characters(value):
        raise ValueError("Destination paths cannot contain control characters.")
    return value


def validate_transfer_label(value):
    if len(value) > MAX_TRANSFER_LABEL_LENGTH:
        raise ValueError(
            f"Transfer labels must be {MAX_TRANSFER_LABEL_LENGTH} characters or fewer."
        )
    if contains_control_characters(value):
        raise ValueError("Transfer labels cannot contain control characters.")
    return value


def validate_oauth_state(value):
    if not value or len(value) > MAX_OAUTH_STATE_LENGTH:
        raise ValueError("Invalid or expired OAuth state.")
    return value


def validate_oauth_code(value):
    if not value or len(value) > MAX_OAUTH_CODE_LENGTH:
        raise ValueError("Invalid OAuth authorization response.")
    return value

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from web_validation import (  # noqa: E402
    MAX_DESTINATION_PATH_BYTES,
    MAX_OAUTH_CODE_LENGTH,
    MAX_TRANSFER_LABEL_LENGTH,
    validate_collection_id,
    validate_collection_search,
    validate_destination_path,
    validate_oauth_code,
    validate_transfer_label,
)


class WebValidationTests(unittest.TestCase):
    def test_collection_id_requires_canonical_uuid(self):
        collection_id = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(validate_collection_id(collection_id), collection_id)
        for invalid in ("not-a-uuid", "{12345678-1234-1234-1234-123456789abc}"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_collection_id(invalid)

    def test_search_rejects_length_and_control_characters(self):
        validate_collection_search("x" * 128)
        with self.assertRaises(ValueError):
            validate_collection_search("x" * 129)
        with self.assertRaises(ValueError):
            validate_collection_search("collection\nname")

    def test_path_limit_counts_utf8_bytes_and_preserves_value(self):
        path = "/" + "é" * ((MAX_DESTINATION_PATH_BYTES - 1) // 2)
        self.assertEqual(validate_destination_path(path), path)
        with self.assertRaises(ValueError):
            validate_destination_path(path + "é")
        with self.assertRaises(ValueError):
            validate_destination_path("/folder\0name")

    def test_transfer_label_checks_resolved_length(self):
        validate_transfer_label("x" * MAX_TRANSFER_LABEL_LENGTH)
        with self.assertRaises(ValueError):
            validate_transfer_label("x" * (MAX_TRANSFER_LABEL_LENGTH + 1))

    def test_oauth_code_is_bounded(self):
        validate_oauth_code("x" * MAX_OAUTH_CODE_LENGTH)
        with self.assertRaises(ValueError):
            validate_oauth_code("x" * (MAX_OAUTH_CODE_LENGTH + 1))


if __name__ == "__main__":
    unittest.main()

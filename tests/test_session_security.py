import unittest
from pathlib import Path


class SessionSecurityTests(unittest.TestCase):
    def test_oauth_access_token_is_not_stored_in_flask_session(self):
        app_source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text()
        self.assertNotIn("transfer_access_token", app_source)


if __name__ == "__main__":
    unittest.main()

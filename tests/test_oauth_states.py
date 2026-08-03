import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

import oauth_states  # noqa: E402


class OAuthStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_db_path = oauth_states.OAUTH_STATE_DB_PATH
        cls.original_ttl = oauth_states.OAUTH_STATE_TTL_SECONDS
        cls.temporary_directory = tempfile.TemporaryDirectory()
        oauth_states.OAUTH_STATE_DB_PATH = str(
            Path(cls.temporary_directory.name) / "oauth-states.sqlite3"
        )
        oauth_states.OAUTH_STATE_TTL_SECONDS = 600
        oauth_states.init_oauth_state_db()

    @classmethod
    def tearDownClass(cls):
        oauth_states.OAUTH_STATE_DB_PATH = cls.original_db_path
        oauth_states.OAUTH_STATE_TTL_SECONDS = cls.original_ttl
        cls.temporary_directory.cleanup()

    def setUp(self):
        with oauth_states.oauth_state_db() as connection:
            connection.execute("DELETE FROM pending_oauth_states")

    def test_state_is_consumed_only_once(self):
        oauth_states.store_oauth_state("state-1", now=1_000)
        self.assertTrue(oauth_states.consume_oauth_state("state-1", now=1_001))
        self.assertFalse(oauth_states.consume_oauth_state("state-1", now=1_002))

    def test_expired_state_is_rejected(self):
        oauth_states.store_oauth_state("state-1", now=1_000)
        self.assertFalse(oauth_states.consume_oauth_state("state-1", now=1_600))

    def test_only_one_concurrent_callback_can_consume_state(self):
        oauth_states.store_oauth_state("state-1", now=1_000)
        barrier = threading.Barrier(2)
        results = []

        def consume():
            barrier.wait()
            results.append(
                oauth_states.consume_oauth_state("state-1", now=1_001)
            )

        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(results), [False, True])

    def test_database_stores_digest_instead_of_raw_state(self):
        oauth_states.store_oauth_state("secret-state", now=1_000)
        with oauth_states.oauth_state_db() as connection:
            stored_value = connection.execute(
                "SELECT state_digest FROM pending_oauth_states"
            ).fetchone()[0]
        self.assertNotEqual(stored_value, "secret-state")
        self.assertEqual(len(stored_value), 64)

    def test_app_binds_state_to_browser_session(self):
        app_source = PROJECT_ROOT.joinpath("app.py").read_text()
        self.assertIn("secrets.compare_digest(returned_state", app_source)
        self.assertIn("consume_oauth_state(returned_state)", app_source)


if __name__ == "__main__":
    unittest.main()

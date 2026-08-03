import unittest
from pathlib import Path


class WebErrorHandlingTests(unittest.TestCase):
    def test_error_page_is_generic(self):
        project_dir = Path(__file__).resolve().parents[1]
        app_source = project_dir.joinpath("app.py").read_text()
        template_source = project_dir.joinpath("templates", "500.html").read_text()

        self.assertIn('@app.errorhandler(500)', app_source)
        self.assertIn("Please try again", template_source)
        self.assertNotIn("{{ error", template_source)
        self.assertNotIn("traceback", template_source.lower())


if __name__ == "__main__":
    unittest.main()

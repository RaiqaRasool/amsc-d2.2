import re
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from csrf import csrf_tokens_match, new_csrf_token  # noqa: E402


class CsrfTests(unittest.TestCase):
    def test_only_matching_nonempty_tokens_are_accepted(self):
        token = new_csrf_token()
        self.assertTrue(csrf_tokens_match(token, token))
        self.assertFalse(csrf_tokens_match(token, "changed"))
        self.assertFalse(csrf_tokens_match(token, None))
        self.assertFalse(csrf_tokens_match(None, token))

    def test_every_post_form_contains_a_csrf_token(self):
        for template in PROJECT_ROOT.joinpath("templates").glob("*.html"):
            post_forms = re.findall(
                r'<form[^>]*method="post"[^>]*>.*?</form>',
                template.read_text(),
                flags=re.DOTALL,
            )
            for form in post_forms:
                with self.subTest(template=template.name):
                    self.assertIn('name="csrf_token"', form)


if __name__ == "__main__":
    unittest.main()

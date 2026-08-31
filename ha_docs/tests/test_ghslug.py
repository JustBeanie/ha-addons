import unittest

import ghslug


class GitHubSlugTests(unittest.TestCase):
    def test_preserves_github_gap_behavior(self):
        self.assertEqual(
            ghslug.slugify("⚠️ Nightlight script ID desync"),
            "-nightlight-script-id-desync",
        )
        self.assertEqual(
            ghslug.slugify("Dusk and away rules — per window"),
            "dusk-and-away-rules--per-window",
        )

    def test_removes_format_and_unsupported_number_characters(self):
        self.assertEqual(ghslug.slugify("A\u200dB ² ½"), "ab--")

    def test_honours_custom_separator_for_mkdocs_callback(self):
        self.assertEqual(ghslug.slugify("Two words", separator="_"), "two_words")


if __name__ == "__main__":
    unittest.main()

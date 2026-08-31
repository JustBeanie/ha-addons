import unittest
from pathlib import Path


class RuntimePolicyTests(unittest.TestCase):
    def test_git_token_is_not_embedded_in_persistent_remote_url(self):
        run_script = (Path(__file__).resolve().parents[1] / "run.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("GIT_CONFIG_KEY_0=http.extraHeader", run_script)
        self.assertIn("GIT_CONFIG_VALUE_0=\"Authorization: Basic ${GIT_AUTH}\"", run_script)
        self.assertIn("GIT_TERMINAL_PROMPT=0", run_script)
        self.assertIn("printf 'x-access-token:%s'", run_script)
        self.assertIn('git -C "${REPO_DIR}" remote set-url origin "${REPO}"', run_script)
        self.assertNotIn("AUTH_REPO", run_script)
        self.assertNotIn("Authorization: Bearer", run_script)
        self.assertNotIn("https://$(bashio::config 'git_token')@", run_script)


if __name__ == "__main__":
    unittest.main()

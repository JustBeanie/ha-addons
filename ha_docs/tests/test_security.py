import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]


class AppSecurityTests(unittest.TestCase):
    def test_published_image_and_custom_apparmor_profile_are_declared(self):
        config = (APP_DIR / "config.yaml").read_text(encoding="utf-8")
        profile = (APP_DIR / "apparmor.txt").read_text(encoding="utf-8")

        self.assertIn('image: "ghcr.io/justbeanie/ha-docs"', config)
        self.assertIn("profile ha_docs", profile)
        self.assertIn("/data/** rwk", profile)
        self.assertNotIn("full_access:", config)
        self.assertNotIn("host_network:", config)

    def test_ingress_only_accepts_supervisor_and_loopback(self):
        nginx = (APP_DIR / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("allow 172.30.32.2;", nginx)
        self.assertIn("allow 127.0.0.1;", nginx)
        self.assertIn("deny all;", nginx)

    def test_main_workflow_publishes_the_declared_image(self):
        workflow = (APP_DIR.parent / ".github" / "workflows" / "ha-docs.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("prepare-publish:", workflow)
        self.assertIn("publish-manifest:", workflow)
        self.assertIn("publish-multi-arch-manifest@2026.06.0", workflow)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = APP_DIR.parent

# Rules the Home Assistant base image needs in order to start at all. `file,`
# is the one that matters most: the `ix` entries below govern exec transitions,
# they do not grant read access, so without a base grant the shell cannot open
# /init and the container restart-loops on
# `/bin/sh: can't open '/init': Permission denied`. The container mount
# namespace, not the profile, is what bounds the visible filesystem.
REQUIRED_BASE_RULES = frozenset(
    {
        "file,",
        "/init ix,",
        "/bin/** ix,",
        "/usr/bin/** ix,",
        "/package/** ix,",
        "/command/** ix,",
        "/run/{,**} rwk,",
        "/usr/lib/bashio/** ix,",
    }
)


def profile_rules(path):
    """Rule lines of an AppArmor profile, without comments or indentation."""
    rules = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        rule = line.strip()
        if rule and not rule.startswith("#"):
            rules.add(rule)
    return rules


class AppArmorProfileTests(unittest.TestCase):
    def test_app_profile_grants_what_the_base_image_needs(self):
        rules = profile_rules(APP_DIR / "apparmor.txt")

        self.assertIn("profile ha_docs flags=(attach_disconnected,mediate_deleted) {", rules)
        self.assertEqual(set(), REQUIRED_BASE_RULES - rules)
        self.assertIn("/data/** rwk,", rules)

    def test_sibling_profiles_share_the_same_base_rules(self):
        # The two profiles are written from one template. Pin them together so a
        # rule cannot quietly go missing from one of them.
        sibling = REPO_DIR / "bacnet_mqtt_gateway" / "apparmor.txt"
        self.assertEqual(set(), REQUIRED_BASE_RULES - profile_rules(sibling))


class AppSecurityTests(unittest.TestCase):
    def test_published_image_is_declared(self):
        config = (APP_DIR / "config.yaml").read_text(encoding="utf-8")

        self.assertIn('image: "ghcr.io/justbeanie/ha-docs"', config)
        self.assertNotIn("full_access:", config)
        self.assertNotIn("host_network:", config)

    def test_ingress_only_accepts_supervisor_and_loopback(self):
        nginx = (APP_DIR / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("allow 172.30.32.2;", nginx)
        self.assertIn("allow 127.0.0.1;", nginx)
        self.assertIn("deny all;", nginx)

    def test_main_workflow_publishes_the_declared_image(self):
        workflow = (REPO_DIR / ".github" / "workflows" / "ha-docs.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("prepare-publish:", workflow)
        self.assertIn("publish-manifest:", workflow)
        self.assertIn("publish-multi-arch-manifest@2026.06.0", workflow)

    def test_main_workflow_runs_the_image_under_its_own_profile(self):
        # A profile that is never loaded and an image that is never started are
        # exactly how the 1.16.0 init denial reached the live app.
        workflow = (REPO_DIR / ".github" / "workflows" / "ha-docs.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("apparmor_parser -r -W ha_docs/apparmor.txt", workflow)
        self.assertIn("--security-opt apparmor=ha_docs", workflow)


if __name__ == "__main__":
    unittest.main()

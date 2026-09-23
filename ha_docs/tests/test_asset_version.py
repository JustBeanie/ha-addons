import pathlib
import re
import tempfile
import unittest
from types import SimpleNamespace

import asset_version

APP_DIR = pathlib.Path(__file__).resolve().parents[1]


class Script:
    """Stands in for mkdocs' ExtraScriptValue: a mapping-style entry."""

    def __init__(self, path):
        self.path = path


class AssetVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / "assets").mkdir()
        (self.tmp / "assets" / "annotate.js").write_text("one", encoding="utf-8")
        (self.tmp / "assets" / "mermaid.min.js").write_text("runtime", encoding="utf-8")

    def config(self):
        return SimpleNamespace(
            theme=SimpleNamespace(custom_dir=str(self.tmp)),
            extra_css=["assets/annotate.css", "https://elsewhere/x.css"],
            extra_javascript=["assets/annotate.js", Script("assets/checker.js")],
        )

    def test_only_local_assets_are_versioned_and_both_entry_kinds_work(self):
        config = asset_version.on_config(self.config())
        version = asset_version.digest(self.tmp / "assets")

        self.assertEqual(f"assets/annotate.css?v={version}", config.extra_css[0])
        self.assertEqual("https://elsewhere/x.css", config.extra_css[1])
        self.assertEqual(f"assets/annotate.js?v={version}", config.extra_javascript[0])
        self.assertEqual(f"assets/checker.js?v={version}", config.extra_javascript[1].path)
        self.assertRegex(version, r"^[0-9a-f]{12}$")

    def test_any_asset_change_moves_the_version_including_the_runtime(self):
        # mermaid-init.js hands its own ?v= to the runtime, so the runtime has
        # to be inside the digest or a Mermaid upgrade would be cached forever.
        before = asset_version.digest(self.tmp / "assets")
        (self.tmp / "assets" / "mermaid.min.js").write_text("runtime 2", encoding="utf-8")
        self.assertNotEqual(before, asset_version.digest(self.tmp / "assets"))

    def test_an_already_versioned_entry_is_left_alone(self):
        self.assertEqual("assets/a.js?v=1", asset_version.versioned("assets/a.js?v=1", "2"))

    def test_the_real_config_wires_the_hook(self):
        mkdocs = (APP_DIR / "mkdocs.yml").read_text(encoding="utf-8")
        dockerfile = (APP_DIR / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(mkdocs, r"(?m)^hooks:\n  - asset_version\.py$")
        self.assertRegex(dockerfile, r"COPY [^\n]*asset_version\.py[^\n]* /opt/ha_docs/")

    def test_browser_suite_caches_by_the_same_rules_as_nginx(self):
        # The page-change test is only meaningful if its server marks the same
        # URLs immutable as nginx does.
        nginx = (APP_DIR / "nginx.conf").read_text(encoding="utf-8")
        runner = (APP_DIR / "tests" / "browser" / "run.mjs").read_text(encoding="utf-8")
        nginx_patterns = re.findall(r'"~(\^[^"]+)" "public, max-age=31536000, immutable";', nginx)
        block = re.search(r"const IMMUTABLE = \[(.*?)\];", runner, re.S).group(1)
        runner_patterns = [p.replace("\\/", "/") for p in re.findall(r"/(\^.*?\$)/", block)]
        self.assertEqual(2, len(nginx_patterns))
        self.assertEqual(nginx_patterns, runner_patterns)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PanelControlTests(unittest.TestCase):
    def test_panel_assets_are_built_and_target_material_sidebars(self):
        config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        script = (ROOT / "overrides" / "assets" / "panels.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (ROOT / "overrides" / "assets" / "panels.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("- assets/panels.js", config)
        self.assertIn("- assets/panels.css", config)
        self.assertIn('selector: ".md-sidebar--primary"', script)
        self.assertIn('selector: ".md-sidebar--secondary"', script)
        self.assertIn("window.localStorage", script)
        self.assertIn("data-ha-docs-navigation-collapsed", stylesheet)
        self.assertIn("data-ha-docs-contents-collapsed", stylesheet)


if __name__ == "__main__":
    unittest.main()

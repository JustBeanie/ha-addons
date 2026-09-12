"""Manifest checks for the ToneWatch Home Assistant app."""

import unittest
from pathlib import Path

import yaml


APP_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_OPTIONS = {"log_level", "public_base_url", "mqtt_mode", "ui_password"}


def read_yaml(relative_path: str):
    with (APP_ROOT / relative_path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class ToneWatchManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = read_yaml("config.yaml")
        self.translations = read_yaml("translations/en.yaml")

    def test_identity_and_runtime_contract(self):
        self.assertEqual(self.manifest["name"], "ToneWatch")
        self.assertEqual(self.manifest["slug"], "tonewatch")
        self.assertEqual(self.manifest["version"], "0.3.0")
        self.assertEqual(sorted(self.manifest["arch"]), ["aarch64", "amd64"])
        self.assertEqual(self.manifest["image"], "ghcr.io/justbeanie/tonewatch")
        self.assertNotIn("{arch}", self.manifest["image"])
        self.assertFalse(self.manifest["init"])
        self.assertTrue(self.manifest["ingress"])
        self.assertEqual(self.manifest["ingress_port"], 8099)
        self.assertEqual(self.manifest["panel_icon"], "mdi:fire-truck")
        self.assertEqual(self.manifest["panel_title"], "ToneWatch")

    def test_devices_services_media_and_backup(self):
        self.assertTrue(self.manifest["audio"])
        self.assertTrue(self.manifest["usb"])
        self.assertEqual(self.manifest["services"], ["mqtt:want"])
        self.assertEqual(self.manifest["discovery"], ["tonewatch"])
        self.assertIn(
            {"type": "media", "read_only": False, "path": "/media"},
            self.manifest["map"],
        )
        self.assertEqual(self.manifest["backup_pre"], "tonewatch db checkpoint")
        self.assertNotIn("backup", self.manifest)
        self.assertNotEqual(self.manifest.get("backup"), "cold")

    def test_options_schema_and_translations_match_exactly(self):
        self.assertEqual(set(self.manifest["options"]), EXPECTED_OPTIONS)
        self.assertEqual(set(self.manifest["schema"]), EXPECTED_OPTIONS)
        self.assertEqual(set(self.translations["configuration"]), EXPECTED_OPTIONS)
        self.assertEqual(self.manifest["schema"]["ui_password"], "password?")

    def test_manifest_is_image_only(self):
        self.assertFalse((APP_ROOT / "Dockerfile").exists())

    def test_presentation_assets_are_pngs(self):
        for name in ("icon.png", "logo.png"):
            data = (APP_ROOT / name).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        icon = (APP_ROOT / "icon.png").read_bytes()
        self.assertEqual((int.from_bytes(icon[16:20], "big"), int.from_bytes(icon[20:24], "big")), (256, 256))


if __name__ == "__main__":
    unittest.main()

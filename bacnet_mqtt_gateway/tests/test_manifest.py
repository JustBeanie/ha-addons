"""Manifest checks for the BACnet MQTT Gateway app.

The application source moved to JustBeanie/bacnet-mqtt-gateway, so the Jest
suite that used to assert against config.yaml no longer sees it. These tests
replace __tests__/app_manifest.test.js and cover the half that stayed here.
"""

import re
import unittest
from pathlib import Path

import yaml


APP_ROOT = Path(__file__).resolve().parents[1]


def read_yaml(relative_path):
    with (APP_ROOT / relative_path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class AppManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = read_yaml("config.yaml")
        self.translations = read_yaml("translations/en.yaml")

    def test_uses_the_current_supervisor_app_contract(self):
        self.assertEqual(self.manifest["name"], "BACnet MQTT Gateway")
        self.assertEqual(self.manifest["slug"], "bacnet_mqtt_gateway")
        self.assertEqual(sorted(self.manifest["arch"]), ["aarch64", "amd64"])
        self.assertTrue(self.manifest["host_network"])
        self.assertTrue(self.manifest["ingress"])
        self.assertEqual(self.manifest["ingress_port"], 18082)
        self.assertEqual(self.manifest["ingress_entry"], "admin/")
        self.assertEqual(self.manifest["services"], ["mqtt:want"])

    def test_maps_app_config_under_the_current_naming(self):
        self.assertIn(
            {"type": "app_config", "read_only": False, "path": "/config"},
            self.manifest["map"],
        )
        self.assertFalse(
            any(entry["type"] == "addon_config" for entry in self.manifest["map"]),
            "app_config was renamed in Supervisor 2026.07; addon_config is stale",
        )

    def test_defines_defaults_and_translations_for_every_option(self):
        self.assertEqual(
            sorted(self.translations["configuration"]),
            sorted(self.manifest["schema"]),
        )
        for option_name in self.manifest["options"]:
            self.assertIn(option_name, self.manifest["schema"])

    def test_installs_a_published_image_rather_than_building_on_the_host(self):
        # The source and the container build live in
        # JustBeanie/bacnet-mqtt-gateway; Supervisor substitutes {arch} and
        # appends `version:` to pick the tag.
        self.assertEqual(
            self.manifest["image"],
            "ghcr.io/justbeanie/bacnet-mqtt-gateway-{arch}",
        )
        self.assertFalse(
            (APP_ROOT / "Dockerfile").exists(),
            "a Dockerfile here would make Supervisor build locally and ignore image:",
        )

    def test_omits_keys_the_app_linter_rejects(self):
        # Restating a default is an error, not a warning, and `watchdog:` is
        # obsolete in favour of the image's HEALTHCHECK. Each of these has a
        # default that matches what the app used to state explicitly, so
        # removing them changed nothing about how it runs.
        for key in ("startup", "boot", "panel_admin", "apparmor", "watchdog"):
            self.assertNotIn(
                key,
                self.manifest,
                f"{key} makes the Home Assistant app linter fail",
            )

    def test_version_is_a_plain_release_tag(self):
        # The workflow resolves this value against GHCR, so it has to be a tag
        # the release workflow in the source repository can actually publish.
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()

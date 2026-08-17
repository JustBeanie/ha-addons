"""Fixture tests for HA Docs-link validation and conservative repair."""

import copy
import importlib.util
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ha_docs"))
SPEC = importlib.util.spec_from_file_location("check_anchors", ROOT / "scripts" / "check_anchors.py")
CHECK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(CHECK)

BASE = "https://github.com/example/docs/blob/main"


class FakeApi:
    def __init__(self, configs, conflict=None):
        self.configs = copy.deepcopy(configs)
        self.conflict = conflict
        self.reads = {key: 0 for key in configs}
        self.writes = []

    def entity_ids(self):
        return sorted(self.configs)

    def get_config(self, entity_id):
        self.reads[entity_id] += 1
        value = copy.deepcopy(self.configs[entity_id])
        if entity_id == self.conflict and self.reads[entity_id] == 2:
            value["sequence"] = [{"action": "light.turn_on"}]
            self.configs[entity_id] = copy.deepcopy(value)
        return value

    def set_config(self, entity_id, config):
        self.writes.append((entity_id, copy.deepcopy(config)))
        self.configs[entity_id] = copy.deepcopy(config)


class CheckAnchorsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "foo.md").write_text("# Target Title\n\n## Other heading\n", encoding="utf-8")
        (self.repo / "ENTITY-INDEX.md").write_text(
            "| `script.index_case` | [Foo](docs/foo.md) | [link](docs/foo.md#target-title) |\n",
            encoding="utf-8",
        )
        self.audit = self.repo / "audit.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, marker="📖 Docs:", url=f"{BASE}/docs/foo.md#target-title"):
        return {"alias": "Fixture", "sequence": [{"stop": "ok"}], "description": f"Test\n\n{marker} {url}"}

    def reconcile(self, configs, repair=True, conflict=None):
        api = FakeApi(configs, conflict)
        failures = CHECK.check_ha(self.repo, api, BASE, repair, self.audit)
        return failures, api

    def test_valid_link_is_not_written(self):
        failures, api = self.reconcile({"script.valid": self.config()})
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])

    def test_legacy_marker_is_normalized_only(self):
        original = self.config(marker="Docs:")
        failures, api = self.reconcile({"script.legacy": original})
        self.assertEqual(failures, 0)
        self.assertEqual(len(api.writes), 1)
        changed = api.writes[0][1]
        self.assertIn("📖 Docs:", changed["description"])
        self.assertEqual(changed["sequence"], original["sequence"])

    def test_unambiguous_index_target_repairs_url(self):
        failures, api = self.reconcile({"script.index_case": self.config(url=f"{BASE}/docs/missing.md#nope")})
        self.assertEqual(failures, 0)
        self.assertIn("docs/foo.md#target-title", api.writes[0][1]["description"])

    def test_unique_heading_repairs_separator_only_anchor(self):
        failures, api = self.reconcile({"script.heading": self.config(url=f"{BASE}/docs/foo.md#target_title")})
        self.assertEqual(failures, 0)
        self.assertIn("#target-title", api.writes[0][1]["description"])

    def test_ambiguous_heading_is_left_unchanged(self):
        (self.repo / "docs" / "foo.md").write_text("# Target Title\n\n## Target Title\n", encoding="utf-8")
        failures, api = self.reconcile({"script.ambiguous": self.config(url=f"{BASE}/docs/foo.md#target_title")})
        self.assertEqual(failures, 1)
        self.assertEqual(api.writes, [])

    def test_missing_target_is_left_unchanged(self):
        failures, api = self.reconcile({"script.missing": self.config(url=f"{BASE}/docs/missing.md#nope")})
        self.assertEqual(failures, 1)
        self.assertEqual(api.writes, [])

    def test_conflict_is_left_unchanged(self):
        failures, api = self.reconcile({"script.conflict": self.config(marker="Docs:")}, conflict="script.conflict")
        self.assertEqual(failures, 1)
        self.assertEqual(api.writes, [])


if __name__ == "__main__":
    unittest.main()

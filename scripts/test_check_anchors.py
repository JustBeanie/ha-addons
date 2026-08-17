"""Fixture tests for HA Docs-link validation and conservative repair."""

import copy
import importlib.util
import io
import pathlib
import re
import sys
import tempfile
import threading
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ha_docs"))
SPEC = importlib.util.spec_from_file_location("check_anchors", ROOT / "ha_docs" / "check_anchors.py")
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
        self.services = []

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

    def call_service(self, domain, service, data):
        self.services.append((domain, service, copy.deepcopy(data)))


class RoutingCoreApi(CHECK.CoreApi):
    """Exercise config-ID routing without making an HTTP request."""

    def __init__(self):
        super().__init__("http://example/api", "token")
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "states":
            return [
                {"entity_id": "automation.example", "attributes": {"id": "1740000000001"}},
                {"entity_id": "script.example", "attributes": {}},
            ]
        return {"alias": "Fixture", "sequence": []}


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
        self.assertEqual(api.services, [("repairs", "remove", {"issue_id": "ha_docs_link_script_valid"})])

    def test_legacy_marker_raises_repair_without_writing(self):
        original = self.config(marker="Docs:")
        failures, api = self.reconcile({"script.legacy": original})
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])
        self.assertEqual(api.services[0][0:2], ("repairs", "create"))
        self.assertIn("Replace `Docs:` with `📖 Docs:`", api.services[0][2]["description"])
        self.assertEqual(api.services[0][2]["issue_id"], "ha_docs_link_script_legacy")
        self.assertEqual(api.services[0][2]["severity"], "warning")
        self.assertTrue(api.services[0][2]["persistent"])

    def test_unambiguous_index_target_repairs_url(self):
        failures, api = self.reconcile({"script.index_case": self.config(url=f"{BASE}/docs/missing.md#nope")})
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])
        self.assertIn("docs/foo.md#target-title", api.services[0][2]["description"])

    def test_unique_heading_repairs_separator_only_anchor(self):
        failures, api = self.reconcile({"script.heading": self.config(url=f"{BASE}/docs/foo.md#target_title")})
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])
        self.assertIn("docs/foo.md#target-title", api.services[0][2]["description"])

    def test_ambiguous_heading_is_left_unchanged(self):
        (self.repo / "docs" / "foo.md").write_text("# Target Title\n\n## Target Title\n", encoding="utf-8")
        failures, api = self.reconcile({"script.ambiguous": self.config(url=f"{BASE}/docs/foo.md#target_title")})
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])

    def test_missing_target_is_left_unchanged(self):
        failures, api = self.reconcile({"script.missing": self.config(url=f"{BASE}/docs/missing.md#nope")})
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])

    def test_candidate_never_writes_configuration(self):
        failures, api = self.reconcile({"script.conflict": self.config(marker="Docs:")}, conflict="script.conflict")
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])

    def test_core_api_uses_automation_config_id_and_script_key(self):
        api = RoutingCoreApi()
        self.assertEqual(api.entity_ids(), ["automation.example", "script.example"])
        api.get_config("automation.example")
        api.set_config("script.example", {"sequence": []})
        self.assertIn(("GET", "config/automation/config/1740000000001", None), api.calls)
        self.assertIn(("POST", "config/script/config/example", {"sequence": []}), api.calls)

    def test_read_failure_does_not_block_a_later_repair(self):
        api = FakeApi({"automation.unreadable": self.config(), "script.legacy": self.config(marker="Docs:")})
        original_get = api.get_config

        def get_config(entity_id):
            if entity_id == "automation.unreadable":
                raise RuntimeError("HA GET: 502")
            return original_get(entity_id)

        api.get_config = get_config
        failures = CHECK.check_ha(self.repo, api, BASE, True, self.audit)
        self.assertEqual(failures, 1)
        self.assertEqual(api.writes, [])
        self.assertEqual([call[1] for call in api.services], ["create"])

    def test_spook_create_failure_is_reported_without_writing(self):
        api = FakeApi({"script.failed_report": self.config(marker="Docs:")})

        def call_service(domain, service, data):
            raise RuntimeError("repairs.create unavailable")

        api.call_service = call_service
        failures = CHECK.check_ha(self.repo, api, BASE, True, self.audit)
        self.assertEqual(failures, 1)
        self.assertEqual(api.writes, [])

    def test_repair_content_explains_broken_link_and_report_only_behavior(self):
        failures, api = self.reconcile({"script.missing": self.config(url=f"{BASE}/docs/missing.md#nope")})
        self.assertEqual(failures, 0)
        description = api.services[0][2]["description"]
        self.assertIn("Problem: broken or ambiguous Docs target.", description)
        self.assertIn("Manually add exactly one valid", description)
        self.assertIn("did not modify the entity", description)
        self.assertEqual(api.writes, [])

    def test_info_logs_are_timestamped_and_include_scan_lifecycle(self):
        stream = io.StringIO()
        CHECK.configure_logging("info", stream)
        try:
            failures, _ = self.reconcile({"script.valid": self.config()})
        finally:
            CHECK.configure_logging()
        self.assertEqual(failures, 0)
        output = stream.getvalue()
        self.assertRegex(output, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d \[INFO\] \[ha\] Docs-link Repair scan started", re.MULTILINE)
        self.assertIn("Docs-link scan progress", output)
        self.assertIn("Docs-link Repair scan complete", output)

    def test_debug_logs_include_per_entity_decisions_but_info_does_not(self):
        info_stream = io.StringIO()
        CHECK.configure_logging("info", info_stream)
        self.reconcile({"script.valid": self.config()})
        debug_stream = io.StringIO()
        CHECK.configure_logging("debug", debug_stream)
        try:
            self.reconcile({"script.valid": self.config()})
        finally:
            CHECK.configure_logging()
        self.assertNotIn("Docs link valid", info_stream.getvalue())
        self.assertIn("Docs link valid: entity=script.valid", debug_stream.getvalue())

    def test_config_reads_respect_bounded_concurrency(self):
        configs = {f"script.test_{index}": self.config() for index in range(8)}
        api = FakeApi(configs)
        original_get = api.get_config
        lock = threading.Lock()
        current = maximum = 0

        def slow_get(entity_id):
            nonlocal current, maximum
            with lock:
                current += 1
                maximum = max(maximum, current)
            try:
                time.sleep(0.02)
                return original_get(entity_id)
            finally:
                with lock:
                    current -= 1

        api.get_config = slow_get
        failures = CHECK.check_ha(self.repo, api, BASE, True, self.audit, concurrency=3, progress_interval=2)
        self.assertEqual(failures, 0)
        self.assertGreater(maximum, 1)
        self.assertLessEqual(maximum, 3)

    def test_runner_starts_ingress_before_background_refresh_worker(self):
        runner = (ROOT / "ha_docs" / "run.sh").read_text(encoding="utf-8")
        self.assertLess(runner.index("nginx &"), runner.index("refresh_worker &"))
        self.assertIn("Initial documentation sync is in progress", runner)
        self.assertIn("wait \"${WORKER_PID}\"", runner)

    def test_issue_ids_are_stable_and_entity_specific(self):
        self.assertEqual(CHECK.repair_issue_id("script.Wake-Up Stage 1"), "ha_docs_link_script_wake_up_stage_1")
        self.assertNotEqual(CHECK.repair_issue_id("script.one"), CHECK.repair_issue_id("script.two"))


if __name__ == "__main__":
    unittest.main()

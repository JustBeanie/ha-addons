"""Fixture tests for HA Docs-link validation and conservative repair."""

import asyncio
import copy
import importlib.util
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ha_docs"))
SPEC = importlib.util.spec_from_file_location("check_anchors", ROOT / "ha_docs" / "check_anchors.py")
CHECK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(CHECK)

# check_anchors imports both, so these are the same module objects the scanner
# writes and reads through - setting the environment or swapping a function here
# reaches it too.
import entity_watch as WATCH  # noqa: E402
import repairs_registry as REGISTRY  # noqa: E402
import scan_status as SCAN  # noqa: E402

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

    def test_missing_storage_config_is_skipped_and_does_not_fail_scan(self):
        api = FakeApi({"script.orphan": self.config(), "script.legacy": self.config(marker="Docs:")})
        original_get = api.get_config

        def get_config(entity_id):
            if entity_id == "script.orphan":
                raise CHECK.CoreApiError("GET", "config/script/config/orphan", 404, "not found")
            return original_get(entity_id)

        api.get_config = get_config
        failures = CHECK.check_ha(self.repo, api, BASE, True, self.audit)
        self.assertEqual(failures, 0)
        self.assertEqual(api.writes, [])
        self.assertIn(("repairs", "remove", {"issue_id": "ha_docs_link_script_orphan"}), api.services)
        creates = [data for domain, service, data in api.services if (domain, service) == ("repairs", "create")]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["issue_id"], "ha_docs_link_script_legacy")
        audit = self.audit.read_text(encoding="utf-8")
        self.assertIn('"outcome": "skipped-missing-config"', audit)

    def test_targeted_scan_checks_only_requested_entity(self):
        api = FakeApi({"script.valid": self.config(), "script.legacy": self.config(marker="Docs:")})
        failures = CHECK.check_ha(
            self.repo, api, BASE, True, self.audit, selected_entity_ids=["script.legacy"]
        )
        self.assertEqual(failures, 0)
        self.assertEqual(api.reads["script.valid"], 0)
        self.assertEqual(api.reads["script.legacy"], 1)
        self.assertEqual([call[1] for call in api.services], ["create"])

    def test_targeted_scan_of_a_deleted_entity_withdraws_its_repair(self):
        api = FakeApi({"script.valid": self.config()})

        def prepare_entity(entity_id):
            raise CHECK.CoreApiError("GET", f"states/{entity_id}", 404, "not found")

        api.prepare_entity = prepare_entity
        failures = CHECK.check_ha(
            self.repo, api, BASE, True, self.audit, selected_entity_ids=["automation.deleted"]
        )
        self.assertEqual(failures, 0)
        self.assertEqual(
            api.services, [("repairs", "remove", {"issue_id": "ha_docs_link_automation_deleted"})]
        )
        self.assertIn('"outcome": "skipped-missing-entity"', self.audit.read_text(encoding="utf-8"))

    def test_a_scan_that_is_not_reporting_withdraws_nothing(self):
        api = FakeApi({"script.valid": self.config()})

        def prepare_entity(entity_id):
            raise CHECK.CoreApiError("GET", f"states/{entity_id}", 404, "not found")

        api.prepare_entity = prepare_entity
        failures = CHECK.check_ha(
            self.repo, api, BASE, False, self.audit, selected_entity_ids=["automation.deleted"]
        )
        self.assertEqual(failures, 0)
        self.assertEqual(api.services, [])

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

    def test_scan_heartbeat_reports_a_stalled_config_api(self):
        stream = io.StringIO()
        CHECK.configure_logging("info", stream)
        api = FakeApi({"script.valid": self.config()})
        original_get = api.get_config

        def slow_get(entity_id):
            time.sleep(1.05)
            return original_get(entity_id)

        api.get_config = slow_get
        try:
            failures = CHECK.check_ha(self.repo, api, BASE, True, self.audit,
                                      concurrency=1, progress_interval=1, heartbeat_interval=1)
        finally:
            CHECK.configure_logging()
        self.assertEqual(failures, 0)
        self.assertIn("Docs-link scan dispatched", stream.getvalue())
        self.assertIn("waiting for HA config API", stream.getvalue())

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
        self.assertIn("entity_watch.py", runner)
        self.assertIn("HA_DOCS_READY_FILE", runner)

    def test_orphan_sweep_runs_every_poll_and_ahead_of_the_source_gate(self):
        runner = (ROOT / "ha_docs" / "run.sh").read_text(encoding="utf-8")
        self.assertIn("check_anchors.py --reap", runner)
        body = runner[runner.index("refresh() {"):runner.index("# nginx needs something to serve")]
        # Ahead of sync_repo, and so ahead of the source check that returns
        # early: a site frozen by a broken anchor must still withdraw Repairs
        # for automations that no longer exist.
        self.assertLess(
            body.index("if ! reap_orphan_doc_link_repairs; then"),
            body.index("if ! sync_repo; then"),
        )

    def test_issue_ids_are_stable_and_entity_specific(self):
        self.assertEqual(CHECK.repair_issue_id("script.Wake-Up Stage 1"), "ha_docs_link_script_wake_up_stage_1")
        self.assertNotEqual(CHECK.repair_issue_id("script.one"), CHECK.repair_issue_id("script.two"))


class EntityWatcherEventTests(unittest.TestCase):
    """Which state_changed events count as a configuration edit.

    This predicate is the whole of the targeted checker's trigger: whatever it
    calls runtime activity is dropped and never checked. Through 1.13.0 that
    included saving an automation, which is the one event it exists to catch.
    """

    @staticmethod
    def state(value, **attributes):
        return {"state": value, "attributes": attributes}

    def test_script_execution_is_runtime_activity(self):
        for old_value, new_value in (("off", "on"), ("on", "off")):
            self.assertTrue(WATCH.is_runtime_state_change({
                "entity_id": "script.example",
                "old_state": self.state(old_value),
                "new_state": self.state(new_value),
            }))

    def test_last_run_metadata_alone_is_runtime_activity(self):
        self.assertTrue(WATCH.is_runtime_state_change({
            "entity_id": "automation.example",
            "old_state": self.state("on", mode="single", last_triggered="1", current=0),
            "new_state": self.state("on", mode="single", last_triggered="2", current=1),
        }))

    def test_a_changed_configuration_attribute_is_not_runtime_activity(self):
        self.assertFalse(WATCH.is_runtime_state_change({
            "entity_id": "automation.example",
            "old_state": self.state("on", mode="single"),
            "new_state": self.state("on", mode="restart"),
        }))

    def test_both_halves_of_a_reload_are_not_runtime_activity(self):
        # Saving one reloads it as off -> unavailable -> off within about two
        # milliseconds, because its registry entry outlives the platform
        # entity. Read as two state flips it is indistinguishable from a script
        # running, which is how every edit came to be discarded.
        for old_value, new_value in (("off", "unavailable"), ("unavailable", "off")):
            self.assertFalse(WATCH.is_runtime_state_change({
                "entity_id": "script.example",
                "old_state": self.state(old_value),
                "new_state": self.state(new_value),
            }))

    def test_an_outright_removal_is_not_runtime_activity(self):
        self.assertFalse(WATCH.is_runtime_state_change({
            "entity_id": "automation.example",
            "old_state": self.state("unavailable"),
            "new_state": None,
        }))

    def test_an_entity_appearing_is_not_runtime_activity(self):
        self.assertFalse(WATCH.is_runtime_state_change({
            "entity_id": "automation.example",
            "old_state": None,
            "new_state": self.state("on"),
        }))

    def test_an_event_without_an_entity_id_stays_visible(self):
        self.assertFalse(WATCH.is_runtime_state_change({"old_state": None, "new_state": None}))

    def test_the_watcher_module_imports_without_its_websocket_dependency(self):
        """Every test above is only reachable while that import stays local."""
        watcher = (ROOT / "ha_docs" / "entity_watch.py").read_text(encoding="utf-8")
        self.assertNotIn("\nimport websockets\n", watcher)


class EntityWatcherBatchTests(unittest.IsolatedAsyncioTestCase):
    """One check per burst of events, rather than one per entity.

    A saved automation arrives as a pair of events, but a Home Assistant restart
    adds every automation and script back at once, and a subprocess each would
    be around two hundred of them doing the work of one scan.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ready = pathlib.Path(self.tmp.name) / "ready"
        ready.write_text("", encoding="utf-8")
        environment = {
            "SUPERVISOR_TOKEN": "token",
            "HA_DOCS_REPO_DIR": self.tmp.name,
            "HA_DOCS_GITHUB_BASE": BASE,
            "HA_DOC_LINK_AUDIT": str(pathlib.Path(self.tmp.name) / "audit.jsonl"),
            "HA_DOCS_READY_FILE": str(ready),
            "HA_DOCS_ENTITY_DEBOUNCE": "0",
        }
        for name, value in environment.items():
            self.addCleanup(os.environ.pop, name, None)
            os.environ[name] = value

    async def drain(self, watcher):
        """Let the surviving debounce run, then the check it spawns."""
        await watcher.debounce
        await asyncio.gather(*watcher.running, return_exceptions=True)

    async def test_a_burst_of_events_becomes_a_single_check(self):
        watcher = WATCH.EntityWatcher()
        calls = []

        class FakeProcess:
            async def wait(self):
                return 0

        async def create_subprocess_exec(*args, **kwargs):
            calls.append(args)
            return FakeProcess()

        with mock.patch.object(asyncio, "create_subprocess_exec", create_subprocess_exec):
            watcher.queue_check("automation.beta")
            watcher.queue_check("automation.alpha")
            # The same entity twice is one entry, not two: saving one produces a
            # removal and an addition, and both mean the same check.
            watcher.queue_check("automation.beta")
            await self.drain(watcher)

        self.assertEqual(len(calls), 1)
        argv = calls[0]
        selected = [argv[i + 1] for i, value in enumerate(argv) if value == "--entity-id"]
        self.assertEqual(selected, ["automation.alpha", "automation.beta"])
        self.assertEqual(watcher.pending, set())

    async def test_a_batch_is_named_by_its_entity_only_when_there_is_one(self):
        watcher = WATCH.EntityWatcher()
        self.assertEqual(watcher.described(["script.only"]), "script.only")
        self.assertEqual(watcher.described(["script.a", "script.b"]), "2 changed entities")


class RepairsRegistryTests(unittest.TestCase):
    """Reading open issue ids out of a repairs/list_issues result."""

    def test_spooks_user_prefix_is_stripped_and_other_issues_ignored(self):
        payload = {"result": {"issues": [
            {"issue_id": "user_ha_docs_link_automation_gone", "domain": "spook"},
            {"issue_id": "ha_docs_link_script_bare", "domain": "spook"},
            {"issue_id": "user_ha_docs_source_anchors", "domain": "spook"},
            {"issue_id": "restart_required_1_tags/v1", "domain": "hacs"},
            "not a dict at all",
        ]}}
        self.assertEqual(
            REGISTRY.link_issue_ids(payload, CHECK.ISSUE_PREFIX),
            {"ha_docs_link_automation_gone", "ha_docs_link_script_bare"},
        )

    def test_the_source_issue_can_never_be_swept(self):
        self.assertFalse(CHECK.SOURCE_REPAIR_ISSUE_ID.startswith(CHECK.ISSUE_PREFIX))

    def test_a_malformed_result_reads_as_empty_rather_than_raising(self):
        for payload in (None, {}, {"result": {}}, {"result": {"issues": {}}}):
            self.assertEqual(REGISTRY.link_issue_ids(payload, CHECK.ISSUE_PREFIX), set())


class OrphanSweepTests(unittest.TestCase):
    """Withdrawing a Repair whose automation or script no longer exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = pathlib.Path(self.tmp.name) / "audit.jsonl"
        self.addCleanup(
            setattr, REGISTRY, "open_link_issue_ids", REGISTRY.open_link_issue_ids
        )

    def registry(self, value):
        REGISTRY.open_link_issue_ids = lambda *args, **kwargs: value

    def reap(self, api):
        CHECK.reap_orphan_issues(api, "ws://example/websocket", "token", self.audit)

    def test_an_issue_without_an_entity_is_withdrawn_and_a_live_one_is_left(self):
        self.registry({"ha_docs_link_automation_gone", "ha_docs_link_script_valid"})
        api = FakeApi({"script.valid": {}})
        self.reap(api)
        self.assertEqual(
            api.services, [("repairs", "remove", {"issue_id": "ha_docs_link_automation_gone"})]
        )
        self.assertIn('"outcome": "repair-reaped"', self.audit.read_text(encoding="utf-8"))

    def test_an_unreadable_registry_withdraws_nothing(self):
        self.registry(None)
        api = FakeApi({"script.valid": {}})
        self.reap(api)
        self.assertEqual(api.services, [])
        self.assertFalse(self.audit.exists())

    def test_an_unavailable_entity_list_withdraws_nothing(self):
        self.registry({"ha_docs_link_automation_gone"})
        api = FakeApi({})

        def entity_ids():
            raise RuntimeError("HA is restarting")

        api.entity_ids = entity_ids
        self.reap(api)
        self.assertEqual(api.services, [])

    def test_one_failed_withdrawal_does_not_abandon_the_rest(self):
        self.registry({"ha_docs_link_automation_first", "ha_docs_link_automation_second"})
        api = FakeApi({})
        original = api.call_service

        def call_service(domain, service, data):
            if data["issue_id"].endswith("_first"):
                raise RuntimeError("repairs.remove unavailable")
            original(domain, service, data)

        api.call_service = call_service
        self.reap(api)
        self.assertEqual(
            api.services, [("repairs", "remove", {"issue_id": "ha_docs_link_automation_second"})]
        )


class ScanStatusTests(unittest.TestCase):
    """The status files the site panel reads, and how they merge."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        (self.repo / "docs").mkdir(parents=True)
        (self.repo / "docs" / "foo.md").write_text("# Target Title\n", encoding="utf-8")
        (self.repo / "README.md").write_text("[ok](docs/foo.md#target-title)\n", encoding="utf-8")
        self.audit = pathlib.Path(self.tmp.name) / "audit.jsonl"
        self.status = pathlib.Path(self.tmp.name) / "status"
        os.environ["HA_DOCS_SCAN_STATUS_DIR"] = str(self.status)
        # Module state outlives a single scan, so a test that left one open
        # would otherwise leak into the next.
        SCAN._full = None

    def tearDown(self):
        os.environ.pop("HA_DOCS_SCAN_STATUS_DIR", None)
        SCAN._full = None
        self.tmp.cleanup()

    def read(self, *parts):
        return json.loads(self.status.joinpath(*parts).read_text(encoding="utf-8"))

    def config(self, marker="\U0001F4D6 Docs:", url=f"{BASE}/docs/foo.md#target-title"):
        return {"alias": "Fixture", "sequence": [{"stop": "ok"}], "description": f"Test\n\n{marker} {url}"}

    def write_entity_record(self, entity_id, verdict, finished, **extra):
        """A per-entity file with an explicit timestamp, so merge order is exact."""
        path = self.status / "entity" / (SCAN.entity_slug(entity_id) + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"entity_id": entity_id, "verdict": verdict, "finished": finished}
        record.update(extra)
        path.write_text(json.dumps(record), encoding="utf-8")

    def finish_full_with(self, issues):
        SCAN.begin_full(len(issues), 10)
        SCAN.finish_full("complete", issues, healthy=0, raised=len(issues))
        return self.read("full.json")["issues_at"]

    def test_begin_full_publishes_a_running_record(self):
        SCAN.begin_full(7, 10)
        record = self.read("full.json")
        self.assertEqual(record["state"], "running")
        self.assertEqual(record["total"], 7)
        self.assertEqual(record["completed"], 0)
        self.assertTrue(record["heartbeat"])

    def test_full_scan_terminal_record_matches_its_summary(self):
        api = FakeApi({"script.valid": self.config(), "script.legacy": self.config(marker="Docs:")})
        failures = CHECK.check_ha(self.repo, api, BASE, True, self.audit)
        self.assertEqual(failures, 0)
        record = self.read("full.json")
        self.assertEqual(record["state"], "complete")
        self.assertEqual(record["healthy"], 1)
        self.assertEqual(record["raised"], 1)
        self.assertEqual(record["failures"], 0)
        self.assertEqual([issue["entity_id"] for issue in record["issues"]], ["script.legacy"])
        self.assertEqual(record["issues"][0]["rule"], "legacy-marker")

    def test_targeted_scan_records_a_healthy_verdict(self):
        # The audit file deliberately never records a healthy link, so without
        # this the panel could not tell a repaired entity is now fine.
        api = FakeApi({"script.valid": self.config()})
        CHECK.check_ha(self.repo, api, BASE, True, self.audit, selected_entity_ids=["script.valid"])
        self.assertEqual(self.read("entity", "script_valid.json")["verdict"], "valid")
        self.assertFalse((self.status / "full.json").exists())

    def test_targeted_scan_records_a_raised_repair(self):
        api = FakeApi({"script.legacy": self.config(marker="Docs:")})
        CHECK.check_ha(self.repo, api, BASE, True, self.audit, selected_entity_ids=["script.legacy"])
        record = self.read("entity", "script_legacy.json")
        self.assertEqual(record["verdict"], "repair-raised")
        self.assertEqual(record["rule"], "legacy-marker")

    def test_newer_valid_verdict_clears_a_row_from_the_full_scan(self):
        at = self.finish_full_with([{"entity_id": "script.legacy", "reason": "legacy", "rule": "legacy-marker"}])
        self.write_entity_record("script.legacy", "valid", at + 5)
        self.assertEqual(SCAN.read_status()["repairs"]["issues"], [])

    def test_newer_raised_verdict_adds_a_row(self):
        at = self.finish_full_with([])
        self.write_entity_record("automation.late", "repair-raised", at + 5,
                                 reason="broken", rule=None, config_id="1740000000001")
        issues = SCAN.read_status()["repairs"]["issues"]
        self.assertEqual([issue["entity_id"] for issue in issues], ["automation.late"])
        self.assertEqual(issues[0]["config_id"], "1740000000001")

    def test_verdict_older_than_the_full_scan_is_ignored(self):
        at = self.finish_full_with([{"entity_id": "script.legacy", "reason": "legacy", "rule": "legacy-marker"}])
        self.write_entity_record("script.legacy", "valid", at - 5)
        self.assertEqual(len(SCAN.read_status()["repairs"]["issues"]), 1)

    def test_failed_verdict_leaves_a_known_row_alone(self):
        # A check that could not reach a conclusion is not evidence the entity
        # is fine, so it must not clear the row.
        at = self.finish_full_with([{"entity_id": "script.legacy", "reason": "legacy", "rule": "legacy-marker"}])
        self.write_entity_record("script.legacy", "failed", at + 5)
        self.assertEqual(len(SCAN.read_status()["repairs"]["issues"]), 1)

    def test_stale_heartbeat_reads_as_stalled(self):
        SCAN.begin_full(5, 10)
        record = self.read("full.json")
        record["heartbeat"] = time.time() - (3 * 10 + SCAN.STALE_GRACE + 5)
        (self.status / "full.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(SCAN.read_status()["repairs"]["state"], "stalled")

    def test_running_scan_that_is_still_reporting_is_not_stalled(self):
        SCAN.begin_full(5, 10)
        self.assertEqual(SCAN.read_status()["repairs"]["state"], "running")

    def test_running_scan_keeps_showing_the_previous_repairs(self):
        # Otherwise the panel blanks its list for the minutes a full scan takes.
        self.finish_full_with([{"entity_id": "script.legacy", "reason": "legacy", "rule": "legacy-marker"}])
        SCAN.begin_full(5, 10)
        status = SCAN.read_status()
        self.assertEqual(status["repairs"]["state"], "running")
        self.assertEqual([issue["entity_id"] for issue in status["repairs"]["issues"]], ["script.legacy"])

    def test_finishing_a_full_scan_prunes_superseded_entity_files(self):
        self.write_entity_record("script.legacy", "repair-raised", time.time())
        SCAN.begin_full(1, 10)
        SCAN.finish_full("complete", [], healthy=1, raised=0)
        self.assertEqual(list((self.status / "entity").glob("*.json")), [])

    def test_source_check_records_its_broken_links(self):
        (self.repo / "README.md").write_text(
            "[bad](docs/foo.md#no-such-heading)\n[gone](docs/missing.md#x)\n", encoding="utf-8")
        bad = CHECK.check_source(self.repo)
        record = self.read("source.json")
        self.assertEqual(bad, 2)
        self.assertEqual(record["broken"], 2)
        self.assertEqual(record["checked"], 2)
        self.assertFalse(record["truncated"])
        self.assertEqual(
            sorted(example["problem"] for example in record["examples"]),
            ["broken anchor", "missing file"],
        )

    def test_clean_source_check_records_zero(self):
        self.assertEqual(CHECK.check_source(self.repo), 0)
        record = self.read("source.json")
        self.assertEqual(record["broken"], 0)
        self.assertEqual(record["examples"], [])

    def test_status_writing_is_opt_in(self):
        # Unset means every writer is a no-op, so running the checker by hand on
        # a workstation cannot scatter status files across it.
        os.environ.pop("HA_DOCS_SCAN_STATUS_DIR")
        self.assertEqual(CHECK.check_source(self.repo), 0)
        self.assertFalse(self.status.exists())
        self.assertEqual(SCAN.read_status()["repairs"], {"state": "unknown", "issues": []})

    def test_unwritable_status_dir_never_changes_a_result(self):
        blocker = pathlib.Path(self.tmp.name) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        os.environ["HA_DOCS_SCAN_STATUS_DIR"] = str(blocker / "scan")
        self.assertEqual(CHECK.check_source(self.repo), 0)
        api = FakeApi({"script.valid": self.config()})
        self.assertEqual(CHECK.check_ha(self.repo, api, BASE, True, self.audit), 0)

if __name__ == "__main__":
    unittest.main()

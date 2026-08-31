import unittest
from unittest import mock

import scan_status


class ScanStatusTests(unittest.TestCase):
    def test_merge_applies_new_targeted_verdicts(self):
        full = {
            "state": "complete",
            "issues_at": 100,
            "issues": [{"entity_id": "automation.old", "reason": "broken"}],
        }
        entities = [
            {"entity_id": "automation.old", "verdict": "valid", "finished": 101},
            {
                "entity_id": "script.new",
                "verdict": "repair-raised",
                "reason": "bad target",
                "rule": None,
                "config_id": "new",
                "finished": 102,
            },
        ]

        merged = scan_status._merge(full, entities)

        self.assertEqual(
            merged["issues"],
            [{
                "entity_id": "script.new",
                "reason": "bad target",
                "rule": None,
                "config_id": "new",
            }],
        )

    def test_stalled_running_scan_is_reported(self):
        record = {"heartbeat": 100, "heartbeat_interval": 10}
        with mock.patch.object(scan_status.time, "time", return_value=1000):
            self.assertTrue(scan_status._stalled(record))

    def test_entity_slug_is_filesystem_safe_and_case_insensitive(self):
        self.assertEqual(
            scan_status.entity_slug("Automation.My-Lamp"),
            "automation_my_lamp",
        )


if __name__ == "__main__":
    unittest.main()

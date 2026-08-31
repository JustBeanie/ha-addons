import unittest

import entity_watch


class EntityWatchTests(unittest.TestCase):
    def test_add_and_remove_events_are_configuration_events(self):
        self.assertFalse(entity_watch.is_runtime_state_change({"entity_id": "automation.a"}))
        self.assertFalse(entity_watch.is_runtime_state_change({
            "entity_id": "automation.a",
            "old_state": None,
            "new_state": {"state": "on"},
        }))

    def test_state_flip_is_runtime_activity(self):
        self.assertTrue(entity_watch.is_runtime_state_change({
            "entity_id": "automation.a",
            "old_state": {"state": "off", "attributes": {}},
            "new_state": {"state": "on", "attributes": {}},
        }))

    def test_runtime_only_attribute_changes_are_ignored(self):
        self.assertTrue(entity_watch.is_runtime_state_change({
            "entity_id": "script.a",
            "old_state": {"state": "off", "attributes": {"last_triggered": 1}},
            "new_state": {"state": "off", "attributes": {"last_triggered": 2}},
        }))

    def test_configuration_attribute_changes_are_visible(self):
        self.assertFalse(entity_watch.is_runtime_state_change({
            "entity_id": "script.a",
            "old_state": {"state": "off", "attributes": {"icon": "mdi:old"}},
            "new_state": {"state": "off", "attributes": {"icon": "mdi:new"}},
        }))

    def test_reload_round_trip_is_configuration_activity(self):
        for old_value, new_value in (("off", "unavailable"), ("unavailable", "off")):
            self.assertFalse(entity_watch.is_runtime_state_change({
                "entity_id": "script.a",
                "old_state": {"state": old_value, "attributes": {}},
                "new_state": {"state": new_value, "attributes": {}},
            }))


if __name__ == "__main__":
    unittest.main()

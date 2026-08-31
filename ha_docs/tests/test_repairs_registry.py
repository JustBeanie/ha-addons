import unittest

import repairs_registry


class RepairsRegistryTests(unittest.TestCase):
    def test_link_issue_ids_normalizes_spook_prefix_and_filters_domain(self):
        payload = {
            "result": {
                "issues": [
                    {"issue_id": "user_ha_docs_link_automation.a"},
                    {"issue_id": "ha_docs_link_script.b"},
                    {"issue_id": "other_domain_issue"},
                    {"issue_id": "user_other_domain_issue"},
                    "malformed",
                ]
            }
        }

        self.assertEqual(
            repairs_registry.link_issue_ids(payload, "ha_docs_link_"),
            {"ha_docs_link_automation.a", "ha_docs_link_script.b"},
        )

    def test_malformed_payload_is_empty(self):
        self.assertEqual(repairs_registry.link_issue_ids({}, "ha_docs_link_"), set())
        self.assertEqual(repairs_registry.link_issue_ids({"result": None}, "ha_docs_link_"), set())


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from unittest import mock
import urllib.error
from pathlib import Path

import check_anchors


class AnchorCheckerTests(unittest.TestCase):
    def make_repo(self, files):
        root = Path(tempfile.mkdtemp())
        for name, contents in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        return root

    def test_collect_headings_disambiguates_duplicate_slugs(self):
        repo = self.make_repo({
            "README.md": "# Same heading\n# Same heading\n```md\n# Ignored\n```\n",
        })

        self.assertEqual(
            check_anchors.collect_headings(repo)[Path("README.md")],
            {"same-heading", "same-heading-1"},
        )

    def test_source_check_ignores_external_and_fenced_links(self):
        repo = self.make_repo({
            "README.md": (
                "# Home\n"
                "[ok](#home) [external](https://example.com/#missing)\n"
                "```md\n[ignored](#missing)\n```\n"
            ),
        })

        self.assertEqual(check_anchors.check_source(repo), 0)

    def test_source_check_reports_missing_files_and_anchors(self):
        repo = self.make_repo({
            "README.md": "# Home\n[bad anchor](#missing)\n[bad file](other.md#home)\n",
        })

        self.assertEqual(check_anchors.check_source(repo), 2)

    def test_reconcile_description_repairs_only_safe_cases(self):
        repo = self.make_repo({
            "docs/page.md": "# Correct heading\n## Repeated\n## Repeated\n",
        })
        base = "https://github.com/example/docs/blob/main"
        headings = check_anchors.collect_headings(repo)
        detailed = check_anchors.headings_with_text(repo)

        outcome, replacement, rule = check_anchors.reconcile_description(
            "automation.example",
            {"description": f"Docs: {base}/docs/page.md#correct-heading"},
            repo,
            base,
            headings,
            detailed,
            {},
        )
        self.assertEqual((outcome, rule), ("repair", "legacy-marker"))
        self.assertIn("📖 Docs:", replacement)

        outcome, replacement, rule = check_anchors.reconcile_description(
            "automation.example",
            {"description": f"📖 Docs: {base}/docs/page.md#correct_heading"},
            repo,
            base,
            headings,
            detailed,
            {},
        )
        self.assertEqual((outcome, rule), ("repair", "unique-heading"))
        self.assertTrue(replacement.endswith("#correct-heading"))

        outcome, replacement, rule = check_anchors.reconcile_description(
            "automation.example",
            {"description": f"📖 Docs: {base}/docs/page.md#repeated_heading"},
            repo,
            base,
            headings,
            detailed,
            {},
        )
        self.assertEqual(outcome, "broken or ambiguous Docs target")
        self.assertIsNone(replacement)
        self.assertIsNone(rule)

    def test_document_url_must_resolve_inside_known_headings(self):
        repo = self.make_repo({"docs/page.md": "# Heading\n"})
        base = "https://github.com/example/docs/blob/main"
        headings = check_anchors.collect_headings(repo)

        self.assertTrue(
            check_anchors.valid_doc_url(
                f"{base}/docs/page.md#heading", repo, base, headings
            )
        )
        self.assertFalse(
            check_anchors.valid_doc_url(
                f"{base}/../secrets.md#heading", repo, base, headings
            )
        )

    def test_core_api_wraps_transport_failures_without_leaking_token(self):
        api = check_anchors.CoreApi("http://supervisor/core/api", "secret-token")
        with mock.patch.object(
            check_anchors.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            with self.assertRaises(check_anchors.CoreApiError) as raised:
                api.request("GET", "states")

        self.assertEqual(raised.exception.status, 0)
        self.assertNotIn("secret-token", str(raised.exception))

    def test_core_api_quotes_path_components_and_rejects_bad_shapes(self):
        api = check_anchors.CoreApi("http://supervisor/core/api", "token")
        api.request = mock.Mock(return_value={
            "entity_id": "automation.foo/bar",
            "attributes": {"id": "config/id"},
        })

        self.assertTrue(api.prepare_entity("automation.foo/bar"))
        self.assertEqual(api.request.call_args.args[1], "states/automation.foo%2Fbar")

        api.request = mock.Mock(return_value=None)
        with self.assertRaises(check_anchors.CoreApiError):
            api.entity_ids()


if __name__ == "__main__":
    unittest.main()

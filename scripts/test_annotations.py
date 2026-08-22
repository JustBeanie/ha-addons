"""Tests for the to-do reconcile pass in annotations.py.

The pass deletes annotations whose to-do item is no longer open, which makes it
the only code in this add-on that removes a note without a person asking. Most
of what is below is therefore about the cases where it must do *nothing* - an
unreadable list, a bare highlight, a note whose push never landed. Those are the
ones that would destroy someone's work, and none of them is visible from the
outside once it has gone wrong.
"""

import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ha_docs"))
SPEC = importlib.util.spec_from_file_location("annotations", ROOT / "ha_docs" / "annotations.py")
ANNO = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(ANNO)

ENTITY = "todo.docs_review"


def open_list(*summaries):
    """A well-formed get_items response carrying these open summaries."""
    return {
        "changed_states": [],
        "service_response": {ENTITY: {"items": [{"summary": s} for s in summaries]}},
    }


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        ANNO.STORE = ANNO.Store(os.path.join(self.tmp.name, "annotations.json"))

        os.environ["TODO_ENTITY"] = ENTITY
        os.environ["SUPERVISOR_TOKEN"] = "test-token"
        self.addCleanup(os.environ.pop, "TODO_ENTITY", None)
        self.addCleanup(os.environ.pop, "SUPERVISOR_TOKEN", None)

        # reconcile() must never tick items off: they are already completed, or
        # already gone. Recording the calls is how that stays true.
        self.completed = []
        real_complete = ANNO.complete_todo
        ANNO.complete_todo = self.completed.append
        self.addCleanup(setattr, ANNO, "complete_todo", real_complete)

        self.real_request = ANNO.todo_request
        self.addCleanup(setattr, ANNO, "todo_request", self.real_request)

    def reply(self, ok, body):
        def stub(service, payload, return_response=False):
            return ok, body

        ANNO.todo_request = stub

    def add(self, anno_id, note, pushed=True):
        record = {
            "id": anno_id,
            "page": "CUSTOM-CODE.html",
            "color": "yellow",
            "note": note,
            "exact": "quoted text",
            "created": 1,
            "updated": 1,
            "todo_pushed": pushed,
        }
        if pushed:
            record["todo_summary"] = note
        ANNO.STORE.save(record)

    def ids(self):
        return sorted(r["id"] for r in ANNO.STORE.all())

    # --- the pass must do nothing -------------------------------------------

    def test_failed_fetch_prunes_nothing(self):
        """An unreachable core API must not read as "nothing is open"."""
        self.add("a", "still open")
        self.add("b", "also open")
        self.reply(False, None)

        self.assertEqual(ANNO.reconcile(), 0)
        self.assertEqual(self.ids(), ["a", "b"])

    def test_unreadable_shape_prunes_nothing(self):
        """A response whose shape changed upstream is unreadable, not empty."""
        for body in (
            {},
            {"service_response": None},
            {"service_response": {}},
            {"service_response": {ENTITY: {}}},
            {"service_response": {ENTITY: {"items": "not a list"}}},
            {"service_response": {"todo.something_else": {"items": []}}},
        ):
            with self.subTest(body=body):
                ANNO.STORE = ANNO.Store(os.path.join(self.tmp.name, "s.json"))
                self.add("a", "a note")
                self.reply(True, body)

                self.assertIsNone(ANNO.open_todo_summaries())
                self.assertEqual(ANNO.reconcile(), 0)
                self.assertEqual(self.ids(), ["a"])

    def test_bare_highlight_is_never_touched(self):
        """A highlight with no note never had an item, so it is not a task."""
        self.add("bare", "", pushed=False)
        self.reply(True, open_list())

        self.assertEqual(ANNO.reconcile(), 0)
        self.assertEqual(self.ids(), ["bare"])

    def test_unpushed_note_is_never_touched(self):
        """A note whose push failed has no item either - an outage must not eat it."""
        self.add("failed", "push never landed", pushed=False)
        self.reply(True, open_list("something else"))

        self.assertEqual(ANNO.reconcile(), 0)
        self.assertEqual(self.ids(), ["failed"])

    def test_open_summary_is_kept(self):
        self.add("a", "still open")
        self.reply(True, open_list("still open"))

        self.assertEqual(ANNO.reconcile(), 0)
        self.assertEqual(self.ids(), ["a"])

    # --- the pass must act ---------------------------------------------------

    def test_missing_summary_is_pruned(self):
        """Ticked off and deleted outright are the same event from out here."""
        self.add("gone", "was ticked off")
        self.add("kept", "still open")
        self.reply(True, open_list("still open"))

        self.assertEqual(ANNO.reconcile(), 1)
        self.assertEqual(self.ids(), ["kept"])

    def test_empty_open_list_does_prune(self):
        """Empty is a real answer; only None means unreadable.

        The mirror of test_failed_fetch_prunes_nothing, and the reason the two
        cannot share a return value.
        """
        self.add("a", "everything is done")
        self.reply(True, open_list())

        self.assertEqual(ANNO.open_todo_summaries(), set())
        self.assertEqual(ANNO.reconcile(), 1)
        self.assertEqual(self.ids(), [])

    def test_reconcile_never_completes_the_item(self):
        self.add("gone", "was ticked off")
        self.reply(True, open_list())

        ANNO.reconcile()
        self.assertEqual(self.completed, [])

    # --- duplicates ----------------------------------------------------------

    def test_duplicate_summaries_are_all_or_nothing(self):
        """Notes with identical text share one item, so they cannot part ways.

        Live example: three notes on the Ember Mug page all read "no remove
        this". Completing one leaves the summary open and keeps all three; the
        pass fails toward keeping a highlight, which is the right direction.
        """
        for anno_id in ("x", "y", "z"):
            self.add(anno_id, "no remove this")

        self.reply(True, open_list("no remove this"))
        self.assertEqual(ANNO.reconcile(), 0)
        self.assertEqual(self.ids(), ["x", "y", "z"])

        self.reply(True, open_list())
        self.assertEqual(ANNO.reconcile(), 3)
        self.assertEqual(self.ids(), [])


class OpenSummariesTests(unittest.TestCase):
    def setUp(self):
        self.real_request = ANNO.todo_request
        self.addCleanup(setattr, ANNO, "todo_request", self.real_request)

    def test_no_entity_configured_is_unreadable(self):
        """No list means no answer, not an empty one."""
        os.environ.pop("TODO_ENTITY", None)
        self.assertIsNone(ANNO.open_todo_summaries())

    def test_status_is_requested_explicitly(self):
        """Omitting status returns completed items too, and nothing ever prunes.

        This is not hypothetical: 1.11.0 shipped relying on the service schema's
        `needs_action` default. Home Assistant applies field defaults when it
        renders the UI form, not when a service is called over the API, so every
        summary matched, every pass cleared nothing, and - because a pass that
        finds nothing logged nothing - it looked exactly like the worker was
        never running.
        """
        os.environ["TODO_ENTITY"] = ENTITY
        self.addCleanup(os.environ.pop, "TODO_ENTITY", None)

        seen = {}

        def capture(service, payload, return_response=False):
            seen["service"] = service
            seen["payload"] = payload
            seen["return_response"] = return_response
            return True, open_list("one")

        ANNO.todo_request = capture
        ANNO.open_todo_summaries()

        self.assertEqual(seen["service"], "get_items")
        self.assertEqual(seen["payload"].get("status"), ["needs_action"])
        self.assertTrue(seen["return_response"])

    def test_summaries_are_extracted(self):
        os.environ["TODO_ENTITY"] = ENTITY
        self.addCleanup(os.environ.pop, "TODO_ENTITY", None)
        ANNO.todo_request = lambda *a, **k: (True, open_list("one", "two"))

        self.assertEqual(ANNO.open_todo_summaries(), {"one", "two"})

    def test_malformed_items_are_skipped_not_fatal(self):
        os.environ["TODO_ENTITY"] = ENTITY
        self.addCleanup(os.environ.pop, "TODO_ENTITY", None)
        body = {
            "service_response": {
                ENTITY: {"items": [{"summary": "good"}, {"no_summary": 1}, "junk", None]}
            }
        }
        ANNO.todo_request = lambda *a, **k: (True, body)

        self.assertEqual(ANNO.open_todo_summaries(), {"good"})


if __name__ == "__main__":
    unittest.main()

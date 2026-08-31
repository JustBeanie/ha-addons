import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import annotations


class AnnotationTests(unittest.TestCase):
    def test_clean_validates_ids_and_excludes_boolean_hints(self):
        with self.assertRaises(ValueError):
            annotations.clean({"id": "bad\n", "page": "README.md"})
        with self.assertRaises(ValueError):
            annotations.clean({"id": "ok", "page": ""})

        record = annotations.clean({
            "id": "ok_1",
            "page": "README.md",
            "hint": True,
            "note": "  first\n second  ",
        })
        self.assertNotIn("hint", record)
        self.assertEqual(annotations.todo_summary(record), "first second")

    def test_store_round_trip_preserves_todo_receipt_on_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = annotations.Store(str(Path(directory) / "annotations.json"))
            first = annotations.clean({
                "id": "note_1",
                "page": "README.md",
                "exact": "quoted text",
                "note": "first note",
            })
            saved = store.save(first)
            original_created = saved["created"]
            store.mark_pushed("note_1")

            edited = annotations.clean({
                "id": "note_1",
                "page": "changed.md",
                "note": "edited note",
            })
            store.save(edited)
            stored = store.all()[0]

            self.assertEqual(stored["created"], original_created)
            self.assertTrue(stored["todo_pushed"])
            self.assertEqual(stored["todo_summary"], "first note")
            self.assertEqual(stored["exact"], "quoted text")

    def test_malformed_root_is_quarantined_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.json"
            path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

            store = annotations.Store(str(path))

            self.assertEqual(store.all(), [])
            self.assertFalse(path.exists())
            self.assertTrue(path.with_name("annotations.json.corrupt").exists())

    def test_http_api_handles_annotation_and_sync_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            original_store = annotations.STORE
            original_sync_path = annotations.SYNC_REQUEST_PATH
            annotations.STORE = annotations.Store(str(Path(directory) / "store.json"))
            annotations.SYNC_REQUEST_PATH = str(Path(directory) / "sync")
            server = annotations.ThreadingHTTPServer(
                ("127.0.0.1", 0), annotations.Handler
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"

            try:
                with urlopen(f"{base}/anno/health") as response:
                    self.assertEqual(json.load(response)["ok"], True)

                payload = json.dumps({"id": "http_1", "page": "README.md"}).encode()
                with urlopen(Request(
                    f"{base}/anno/save",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )) as response:
                    self.assertTrue(json.load(response)["ok"])

                bad_sync = Request(
                    f"{base}/anno/sync",
                    data=b"{}",
                    method="POST",
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(bad_sync)
                self.assertEqual(raised.exception.code, 400)

                with urlopen(Request(
                    f"{base}/anno/sync",
                    headers={"Content-Length": "0"},
                    method="POST",
                )) as response:
                    self.assertTrue(json.load(response)["ok"])
                self.assertTrue(Path(annotations.SYNC_REQUEST_PATH).exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                annotations.STORE = original_store
                annotations.SYNC_REQUEST_PATH = original_sync_path


if __name__ == "__main__":
    unittest.main()

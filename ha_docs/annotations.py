#!/usr/bin/env python3
"""
Annotation store for the HA Docs add-on.

The site nginx serves is static and rebuilt from scratch on every commit, so
highlights and notes cannot live in it. They live here instead: one JSON file
in /data, which survives add-on upgrades and reboots the same way the cloned
repo and the build stamp do.

Server-side rather than in localStorage because the docs are read from two
places - a desktop browser and the HA companion app - and a highlight made in
one is only useful if it shows up in the other.

Reachability, and why there is no auth: this binds 127.0.0.1 only. The single
route in is nginx, and the single route into nginx is HA ingress, which is
already authenticated. Adding a second token here would guard a door that is
inside the locked room.

The docs repository is never touched. DOCS.md promises the add-on only ever
pulls, and that stays true.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

STORE_PATH = "/data/annotations.json"
BIND = ("127.0.0.1", 8100)

# Request bodies are one annotation. Anything near this is a bug or an abuse.
MAX_BODY = 64 * 1024

# Client-generated ids. Validated rather than trusted because the id ends up in
# a dict key and in an HTML attribute.
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COLOR_RE = re.compile(r"^[a-z]{1,16}$")

# Field caps. `exact` is generous because a highlight can legitimately be a
# whole paragraph; the context strings only need to disambiguate.
CAPS = {
    "page": 512,
    "exact": 2000,
    "prefix": 200,
    "suffix": 200,
    "note": 2000,
}

# HA's to-do summary field is a single line; anything longer is unreadable in
# the UI and some backends reject it outright.
TODO_SUMMARY_MAX = 240


def log(level, message):
    sys.stderr.write("[annotations] {}: {}\n".format(level, message))
    sys.stderr.flush()


class Store:
    """The whole dataset in memory, flushed to one JSON file on every change.

    This process is the only writer, so the in-memory copy is authoritative and
    reads never touch the disk. The data is a few kilobytes; anything more
    structured than a dict would be scaffolding for a problem this does not
    have.
    """

    def __init__(self, path):
        self._path = path
        self._lock = threading.Lock()
        self._records = self._read()

    def _read(self):
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as err:
            # Keep serving rather than crashing the add-on over a corrupt file,
            # but move it aside so the next write does not overwrite evidence.
            log("error", "cannot read {} ({}) - starting empty".format(self._path, err))
            try:
                os.replace(self._path, self._path + ".corrupt")
            except OSError:
                pass
            return {}

        records = data.get("annotations")
        if not isinstance(records, dict):
            return {}
        return records

    def _flush_locked(self):
        """Write via a temp file so a power cut cannot leave a truncated store."""
        payload = {"version": 1, "annotations": self._records}
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except OSError as err:
            log("error", "cannot write {}: {}".format(self._path, err))

    def all(self):
        with self._lock:
            return sorted(self._records.values(), key=lambda r: r.get("created", 0))

    def save(self, record):
        with self._lock:
            previous = self._records.get(record["id"])
            if previous:
                # An edit keeps the anchor and the push state it already had -
                # the client only ever sends note and colour changes after the
                # first save, and re-pushing an edited note would duplicate the
                # to-do item.
                record["created"] = previous.get("created", record["created"])
                record["todo_pushed"] = previous.get("todo_pushed", False)
                for field in ("exact", "prefix", "suffix", "hint"):
                    if field not in record and field in previous:
                        record[field] = previous[field]
            self._records[record["id"]] = record
            self._flush_locked()
            return dict(record)

    def delete(self, anno_id):
        with self._lock:
            existed = self._records.pop(anno_id, None) is not None
            if existed:
                self._flush_locked()
            return existed

    def mark_pushed(self, anno_id):
        with self._lock:
            record = self._records.get(anno_id)
            if not record or record.get("todo_pushed"):
                return
            record["todo_pushed"] = True
            self._flush_locked()


def clean(payload):
    """Reduce an incoming body to a record, or raise ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("body must be an object")

    anno_id = payload.get("id")
    if not isinstance(anno_id, str) or not ID_RE.match(anno_id):
        raise ValueError("bad id")

    page = payload.get("page")
    if not isinstance(page, str) or not page:
        raise ValueError("bad page")

    record = {
        "id": anno_id,
        "page": page[: CAPS["page"]],
        "color": "yellow",
        "note": "",
        "created": int(time.time()),
        "updated": int(time.time()),
        "todo_pushed": False,
    }

    color = payload.get("color")
    if isinstance(color, str) and COLOR_RE.match(color):
        record["color"] = color

    for field in ("exact", "prefix", "suffix", "note"):
        value = payload.get(field)
        if isinstance(value, str):
            record[field] = value[: CAPS[field]]

    hint = payload.get("hint")
    if isinstance(hint, int) and not isinstance(hint, bool) and hint >= 0:
        record["hint"] = hint

    title = payload.get("title")
    if isinstance(title, str):
        record["title"] = title[:200]

    return record


def push_todo(record):
    """Add one item to the configured to-do list.

    One way, once, and only for annotations that carry a note - a bare
    highlight is a reading aid, not a task. Editing the note later does not
    update the item and deleting the annotation does not remove it: todo's
    add_item returns no uid, so there is nothing to address afterwards. That
    is documented in DOCS.md rather than worked around.
    """
    entity = os.environ.get("TODO_ENTITY", "").strip()
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not entity:
        return
    if not token:
        log("warning", "todo_entity is set but SUPERVISOR_TOKEN is missing")
        return

    where = record.get("title") or record.get("page", "")
    summary = " ".join(record.get("note", "").split())[:TODO_SUMMARY_MAX]
    if not summary:
        return

    body = json.dumps(
        {
            "entity_id": entity,
            "item": summary,
            "description": "{}\n\n> {}".format(where, record.get("exact", "")),
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "http://supervisor/core/api/services/todo/add_item",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status < 300:
                return True
            log("warning", "todo add_item returned {}".format(response.status))
    except (urllib.error.URLError, OSError) as err:
        log("warning", "todo add_item failed: {}".format(err))
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "ha_docs_annotations"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # BaseHTTPRequestHandler logs every request to stderr, which would put a
    # line in the add-on log for each page view.
    def log_message(self, fmt, *args):
        pass

    def _reply(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("bad Content-Length")
        if length <= 0 or length > MAX_BODY:
            raise ValueError("bad body size")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")

        # One route, deliberately: the client fetches the whole store on load
        # rather than just this page's, because the review drawer needs the
        # rest anyway and the payload is kilobytes over loopback.
        if route == "/anno/all":
            self._reply(200, {"ok": True, "annotations": STORE.all()})
        elif route == "/anno/health":
            self._reply(200, {"ok": True, "todo": bool(os.environ.get("TODO_ENTITY"))})
        else:
            self._reply(404, {"ok": False, "error": "no such route"})

    def do_POST(self):
        route = urlparse(self.path).path.rstrip("/")

        try:
            payload = self._body()
        except (ValueError, UnicodeDecodeError) as err:
            self._reply(400, {"ok": False, "error": str(err)})
            return

        if route == "/anno/save":
            try:
                record = clean(payload)
            except ValueError as err:
                self._reply(400, {"ok": False, "error": str(err)})
                return
            saved = STORE.save(record)
            # Off the request path on purpose: a slow or unreachable core API
            # must not make saving a highlight feel broken.
            if saved.get("note") and not saved.get("todo_pushed"):
                threading.Thread(
                    target=_push_and_mark, args=(saved,), daemon=True
                ).start()
            self._reply(200, {"ok": True, "annotation": saved})

        elif route == "/anno/delete":
            anno_id = payload.get("id")
            if not isinstance(anno_id, str) or not ID_RE.match(anno_id):
                self._reply(400, {"ok": False, "error": "bad id"})
                return
            self._reply(200, {"ok": True, "deleted": STORE.delete(anno_id)})

        else:
            self._reply(404, {"ok": False, "error": "no such route"})


def _push_and_mark(record):
    if push_todo(record):
        STORE.mark_pushed(record["id"])


STORE = Store(STORE_PATH)


def main():
    server = ThreadingHTTPServer(BIND, Handler)
    server.daemon_threads = True

    entity = os.environ.get("TODO_ENTITY", "").strip()
    destination = "to-do list " + entity if entity else "no to-do list configured"
    log(
        "info",
        "serving {} annotations on {}:{} ({})".format(
            len(STORE.all()), BIND[0], BIND[1], destination
        ),
    )

    server.serve_forever()


if __name__ == "__main__":
    main()

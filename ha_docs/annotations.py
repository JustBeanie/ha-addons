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

import datetime as dt
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

import scan_status

STORE_PATH = "/data/annotations.json"
BIND = ("127.0.0.1", 8100)

# The Sync button in the site header writes SYNC_REQUEST; run.sh's refresh worker
# polls for it between sleeps and pulls straight away rather than waiting out the
# rest of poll_interval. A file, because the worker is a bash loop in another
# process and /data is the one channel both sides already share.
SYNC_REQUEST_PATH = "/data/.sync-now"

# Written by run.sh: BUILD_STAMP_PATH after a successful build, REFRESH_MARKER
# after every completed pass whether or not anything changed. The browser needs
# both - the first to know a new site exists, the second to know the worker has
# finished looking, so "nothing changed" can be reported immediately instead of
# waiting out a timeout.
BUILD_STAMP_PATH = "/data/.last_build"
REFRESH_MARKER_PATH = "/data/.last_refresh"

# How often reconcile_worker stats the refresh marker. This is NOT the reconcile
# cadence - the core API is only called when the marker changes, which run.sh
# does once per completed refresh pass. Keep it small: it is a stat of one tiny
# file, and it decides how quickly the site's Sync button clears a done note.
MARKER_POLL_SECONDS = 5

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


def read_marker(path):
    """Contents of one of run.sh's small state files, or "" if it is not there."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def log(level, message):
    timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    sys.stderr.write("{} [{}] [annotations] {}\n".format(timestamp, level.upper(), message))
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
                if "todo_summary" in previous:
                    record["todo_summary"] = previous["todo_summary"]
                for field in ("exact", "prefix", "suffix", "hint"):
                    if field not in record and field in previous:
                        record[field] = previous[field]
            self._records[record["id"]] = record
            self._flush_locked()
            return dict(record)

    def delete(self, anno_id):
        """Remove one annotation and hand it back, or None if it was not there.

        Returns the record rather than a bool because the caller has to know
        whether it ever reached the to-do list, and this is the last moment it
        can be asked.
        """
        with self._lock:
            record = self._records.pop(anno_id, None)
            if record is not None:
                self._flush_locked()
            return record

    def mark_pushed(self, anno_id):
        with self._lock:
            record = self._records.get(anno_id)
            if not record or record.get("todo_pushed"):
                return
            record["todo_pushed"] = True
            # The exact string the item was created with. Editing the note later
            # changes the record but not the item, so completing it means keeping
            # the handle rather than recomputing it from a note that has moved on.
            record["todo_summary"] = todo_summary(record)
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


def todo_summary(record):
    """The single line a note becomes on the to-do list.

    One definition, because an item is created by this string and later found
    again by it. If the two ever drifted apart, completing an item would
    silently miss.
    """
    return " ".join(record.get("note", "").split())[:TODO_SUMMARY_MAX]


def todo_request(service, payload, return_response=False):
    """Call one todo service on the core API. Returns (ok, parsed body or None).

    Split out from call_todo because one caller - the reconcile pass - needs the
    body and the rest only need to know it landed. `ok` is about the request,
    not the contents: a service that legitimately returns nothing still gives
    (True, None).
    """
    entity = os.environ.get("TODO_ENTITY", "").strip()
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not entity:
        return False, None
    if not token:
        log("warning", "todo_entity is set but SUPERVISOR_TOKEN is missing")
        return False, None

    body = dict(payload)
    body["entity_id"] = entity

    # Services that return data only do so when asked. Without this the call
    # succeeds and hands back an empty body, which would read as "nothing is
    # open" - the exact misreading reconcile() must never make.
    url = "http://supervisor/core/api/services/todo/" + service
    if return_response:
        url += "?return_response"

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                log("warning", "todo {} returned {}".format(service, response.status))
                return False, None
            if not return_response:
                return True, None
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as err:
        log("warning", "todo {} failed: {}".format(service, err))
        return False, None

    try:
        return True, json.loads(raw)
    except (ValueError, UnicodeDecodeError) as err:
        log("warning", "todo {} returned unreadable JSON: {}".format(service, err))
        return False, None


def call_todo(service, payload):
    """Call one todo service on the core API. True if it landed.

    Both callers run on a daemon thread off the request path, so an unreachable
    or slow core API can only ever cost a log line - never a saved highlight or
    a deleted one.
    """
    ok, _ = todo_request(service, payload)
    return ok


def push_todo(record):
    """Add one item to the configured to-do list.

    Once, and only for annotations that carry a note - a bare highlight is a
    reading aid, not a task. Editing the note afterwards still does not update
    the item; there is no uid to address it by, and rewriting an item someone
    may already have started on would be worse than leaving it.
    """
    summary = todo_summary(record)
    if not summary:
        return False

    where = record.get("title") or record.get("page", "")
    return call_todo(
        "add_item",
        {
            "item": summary,
            "description": "{}\n\n> {}".format(where, record.get("exact", "")),
        },
    )


def complete_todo(record):
    """Tick off the item a note created, when its annotation is deleted.

    update_item resolves `item` by uid or by summary, so the string sent at push
    time is handle enough and no get_items round trip is needed. It comes off
    the record (mark_pushed stored it) rather than off the current note, which
    may have been edited since.

    Only called for records that pushed - todo_pushed is the receipt. An item
    that is already gone comes back 400 and is logged: deleting a note must
    never fail over what the to-do list thinks.
    """
    summary = record.get("todo_summary") or todo_summary(record)
    if not summary:
        return False

    return call_todo("update_item", {"item": summary, "status": "completed"})


def open_todo_summaries():
    """Summaries of every still-open item on the list, or None if unreadable.

    `get_items` defaults to needs_action, so one call answers both halves of the
    question this exists for: an item that pushed and is no longer in here has
    been ticked off *or* deleted, and from out here those are the same event.

    **None and an empty set are not the same thing and must never be conflated.**
    Empty means the list has nothing open; None means the list could not be read.
    reconcile() prunes on the first and does nothing on the second, and that
    distinction is the only thing standing between an unreachable core API and
    every note-bearing highlight in the store being deleted at once.
    """
    entity = os.environ.get("TODO_ENTITY", "").strip()
    if not entity:
        return None

    ok, body = todo_request("get_items", {}, return_response=True)
    if not ok or not isinstance(body, dict):
        return None

    # {"changed_states": [...], "service_response": {"<entity>": {"items": [...]}}}
    # Checked a layer at a time rather than assumed: a shape change upstream has
    # to surface as "cannot read", never as "nothing is open".
    response = body.get("service_response")
    if not isinstance(response, dict):
        log("warning", "todo get_items returned no service_response")
        return None

    listing = response.get(entity)
    if not isinstance(listing, dict):
        log("warning", "todo get_items returned nothing for {}".format(entity))
        return None

    items = listing.get("items")
    if not isinstance(items, list):
        log("warning", "todo get_items returned no items for {}".format(entity))
        return None

    return {
        item["summary"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("summary"), str)
    }


def reconcile():
    """Delete annotations whose to-do item is no longer open. Count removed.

    The inverse of push_todo, and the half that was missing until 1.11.0: a note
    creates an item, and the item going away now takes the highlight with it.

    complete_todo is deliberately NOT called for anything removed here. Store's
    delete hands the record back so the caller can decide, and this is the one
    caller that must decline - the item is already completed, or already gone.
    """
    summaries = open_todo_summaries()
    if summaries is None:
        return 0

    removed = 0
    for record in STORE.all():
        # A bare highlight is a reading aid, not a task: it never had an item,
        # so there is nothing here to reason about. The same guard covers a note
        # whose push failed, which would otherwise be destroyed over an outage
        # that happened while it was being written.
        if not record.get("todo_pushed"):
            continue
        if record.get("todo_summary") in summaries:
            continue
        if STORE.delete(record["id"]) is not None:
            removed += 1

    if removed:
        log("info", "cleared {} highlight(s) whose to-do item is done".format(removed))
    return removed


def reconcile_worker():
    """Reconcile once per completed refresh pass, forever.

    run.sh bumps REFRESH_MARKER_PATH after every pass - poll or sync-request
    alike - so watching that file inherits poll_interval without a second timer
    to keep in step with it, and makes the site's Sync button a manual "clear
    now", which is the answer to a fifteen-minute default feeling slow.

    Watching a file rather than exposing a route also keeps every mutation of
    the store inside the process holding its lock. The sleep below is only how
    often the marker is stat'd; the core API is called when it *changes*.
    """
    seen = read_marker(REFRESH_MARKER_PATH)
    while True:
        time.sleep(MARKER_POLL_SECONDS)
        current = read_marker(REFRESH_MARKER_PATH)
        if current == seen:
            continue
        seen = current
        try:
            reconcile()
        except Exception as err:  # noqa: BLE001
            # Broad on purpose. This thread is the only thing clearing done
            # highlights; letting one bad pass kill it would fail silently and
            # look exactly like the feature never having worked.
            log("warning", "reconcile pass failed: {}".format(err))


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
            self._reply(200, {
                "ok": True,
                "todo": bool(os.environ.get("TODO_ENTITY")),
                "build": read_marker(BUILD_STAMP_PATH),
                "refreshed": read_marker(REFRESH_MARKER_PATH),
            })
        elif route == "/anno/scan":
            # Deliberately not folded into /anno/health: the Supervisor watchdog
            # probes that on a timer, and it must stay a trivial liveness answer
            # rather than growing a directory walk.
            self._reply(200, scan_status.read_status(
                enabled=os.environ.get("REPORT_DOC_LINK_REPAIRS") == "true",
                watcher=os.environ.get("WATCH_ENTITY_UPDATES") == "true",
            ))
        else:
            self._reply(404, {"ok": False, "error": "no such route"})

    def _request_sync(self):
        """Ask the refresh worker to pull now.

        Nothing is validated because nothing is accepted: the request is the
        whole message, and the file it writes is read by one bash loop that
        deletes it again. The reply carries the current state so the caller has
        something to compare against while it waits.
        """
        try:
            with open(SYNC_REQUEST_PATH, "w", encoding="utf-8") as handle:
                handle.write(str(int(time.time())))
        except OSError as err:
            log("error", "cannot request a sync: {}".format(err))
            self._reply(500, {"ok": False, "error": "cannot request a sync"})
            return
        self._reply(200, {
            "ok": True,
            "build": read_marker(BUILD_STAMP_PATH),
            "refreshed": read_marker(REFRESH_MARKER_PATH),
        })

    def do_POST(self):
        route = urlparse(self.path).path.rstrip("/")

        # Answered before the body is read: a sync request carries no payload,
        # and _body() rejects an empty one.
        if route == "/anno/sync":
            self._request_sync()
            return

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
            removed = STORE.delete(anno_id)
            # Same reasoning as the push above: the annotation is already gone
            # from the store, and whether the to-do list agrees is not something
            # the browser should be made to wait on.
            if removed and removed.get("todo_pushed"):
                threading.Thread(
                    target=complete_todo, args=(removed,), daemon=True
                ).start()
            self._reply(200, {"ok": True, "deleted": removed is not None})

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

    # Only worth running when there is a list to reconcile against. Without an
    # entity open_todo_summaries() returns None every pass anyway, so this would
    # be a thread waking up forever to decide it has nothing to do.
    if entity:
        threading.Thread(target=reconcile_worker, daemon=True).start()

    server.serve_forever()


if __name__ == "__main__":
    main()

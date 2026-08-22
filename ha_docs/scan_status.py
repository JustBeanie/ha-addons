"""On-disk status for the HA Docs checkers, and the merged view the site reads.

Two checkers report through here: the documentation-source anchor check
(``check_source``) and the HA Docs-link Repair scan (``check_ha``). Both are
short-lived subprocesses, and several Repair scans can be in flight at once -
one full scan plus however many targeted ones ``entity_watch.py`` has queued -
so there is no long-lived process to hold this state. They write small JSON
files into /data instead, the same channel run.sh's ``.last_build`` and
``.last_refresh`` markers already use, and annotations.py serves the merged
result at ``/anno/scan``.

One writer per file, which is what makes this safe without any locking:

    source.json           check_source; refresh_worker is a single serial loop
    full.json             the full --ha scan, one at a time from refresh()
    entity/<slug>.json    one targeted scan, in its own subprocess

Writing is opt-in on ``HA_DOCS_SCAN_STATUS_DIR``. Unset means every writer here
is a no-op, so running ``check_anchors.py --source`` on a developer machine
cannot scatter status files across it - there is deliberately no default path.

Nothing in this module may raise. A checker's exit code is a statement about
documentation links, and it must not start depending on whether a status file
could be written.
"""

import json
import logging
import os
import pathlib
import re
import time


LOGGER = logging.getLogger("ha_docs.scan_status")

VERSION = 1

# Same rule as check_anchors.repair_issue_id, so a status filename is derived
# the same way a Repair issue id is and stays filesystem-safe.
SLUG_RE = re.compile(r"[^a-z0-9_]+")

# A broken-anchor list is for reading, not for archiving; the log has them all.
MAX_SOURCE_EXAMPLES = 50

# How many recent targeted checks the panel shows.
MAX_RECENT = 10

# Progress writes are throttled to this, so a fast scan cannot turn into one
# small write per completed entity.
UPDATE_THROTTLE = 1.0

# Added to 3x the scan's own heartbeat interval before a running record is
# called stalled. The scan bumps its heartbeat every time it reports waiting on
# the HA config API, so a genuinely slow scan stays "running"; only a process
# that has actually gone away goes quiet for longer than this.
STALE_GRACE = 60


def status_dir():
    """Where status is written, or None when status reporting is switched off."""
    value = os.environ.get("HA_DOCS_SCAN_STATUS_DIR", "").strip()
    return pathlib.Path(value) if value else None


def entity_slug(entity_id):
    return SLUG_RE.sub("_", entity_id.casefold())


def _write(path, payload):
    """Replace one status file atomically. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as err:
        LOGGER.debug("cannot write %s: %s", path, err)


def _read(path):
    """One status file as a dict, or None if it is absent or unreadable."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------
# The documentation-source anchor check
# ---------------------------------------------------------------------------


def write_source(checked, broken, examples):
    root = status_dir()
    if root is None:
        return
    examples = list(examples)
    _write(root / "source.json", {
        "version": VERSION,
        "checked": checked,
        "broken": broken,
        "examples": examples[:MAX_SOURCE_EXAMPLES],
        "truncated": len(examples) > MAX_SOURCE_EXAMPLES,
        "finished": time.time(),
    })


# ---------------------------------------------------------------------------
# The full Docs-link Repair scan
#
# Module state, because a full scan is one process from begin to finish and the
# alternative is threading the record through check_ha by hand.
# ---------------------------------------------------------------------------

_full = None
_flushed_at = 0.0


def begin_full(total, heartbeat_interval):
    global _full, _flushed_at
    root = status_dir()
    if root is None:
        return
    previous = _read(root / "full.json") or {}
    _full = {
        "version": VERSION,
        "state": "running",
        "started": time.time(),
        "heartbeat_interval": heartbeat_interval,
        "total": total,
        "completed": 0,
        "current": None,
        # Carried forward so the panel keeps showing the last known repairs
        # while a new scan runs, rather than blanking the list for the minutes
        # it takes. `issues_at` says how old that list is, and doubles as the
        # cutoff read_status uses when applying targeted verdicts on top.
        "issues": previous.get("issues", []),
        "issues_at": previous.get("issues_at", 0),
    }
    _flushed_at = 0.0
    _flush(force=True)


def update_full(**fields):
    if _full is None:
        return
    _full.update(fields)
    _flush()


def finish_full(state, issues, **counts):
    global _full
    if _full is None:
        return
    _full.update(counts)
    _full["state"] = state
    _full["finished"] = time.time()
    _full["current"] = None
    _full["issues"] = list(issues)
    _full["issues_at"] = _full["finished"]
    _flush(force=True)
    _prune_entities()
    _full = None


def _flush(force=False):
    global _flushed_at
    root = status_dir()
    if root is None or _full is None:
        return
    now = time.monotonic()
    if not force and now - _flushed_at < UPDATE_THROTTLE:
        return
    _flushed_at = now
    _full["heartbeat"] = time.time()
    _write(root / "full.json", _full)


def _prune_entities():
    """Drop the per-entity files a completed full scan has just superseded.

    A targeted scan writing one back mid-sweep is harmless: it either survives,
    and is newer than the full record so read_status applies it on top, or it is
    removed and that entity is re-derived the next time it changes.
    """
    root = status_dir()
    if root is None:
        return
    try:
        for path in (root / "entity").glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass
    except OSError as err:
        LOGGER.debug("cannot prune entity status: %s", err)


# ---------------------------------------------------------------------------
# Targeted single-entity checks
# ---------------------------------------------------------------------------


def write_entity(entity_id, verdict, reason=None, rule=None, config_id=None):
    """Record one targeted verdict.

    Called for a healthy link too, which the audit file deliberately never
    records. Without the `valid` case a repaired entity would keep its row in
    the panel until the next full scan.
    """
    root = status_dir()
    if root is None:
        return
    _write(root / "entity" / (entity_slug(entity_id) + ".json"), {
        "version": VERSION,
        "entity_id": entity_id,
        "verdict": verdict,
        "reason": reason,
        "rule": rule,
        "config_id": config_id,
        "finished": time.time(),
    })


# ---------------------------------------------------------------------------
# The merged view
# ---------------------------------------------------------------------------


def _read_entities(root):
    try:
        paths = sorted((root / "entity").glob("*.json"))
    except OSError:
        return []
    records = []
    for path in paths:
        record = _read(path)
        if record and record.get("entity_id"):
            records.append(record)
    return records


def _stalled(record):
    interval = record.get("heartbeat_interval") or 10
    try:
        limit = 3 * float(interval) + STALE_GRACE
    except (TypeError, ValueError):
        limit = 3 * 10 + STALE_GRACE
    return time.time() - (record.get("heartbeat") or 0) > limit


def _merge(full, entities):
    record = dict(full) if full else {"state": "unknown"}
    issues = {}
    for issue in record.pop("issues", None) or []:
        if isinstance(issue, dict) and issue.get("entity_id"):
            issues[issue["entity_id"]] = dict(issue)

    boundary = record.get("issues_at") or 0
    for entity in entities:
        if (entity.get("finished") or 0) <= boundary:
            continue
        entity_id = entity["entity_id"]
        verdict = entity.get("verdict")
        if verdict == "repair-raised":
            issues[entity_id] = {
                "entity_id": entity_id,
                "reason": entity.get("reason"),
                "rule": entity.get("rule"),
                "config_id": entity.get("config_id"),
            }
        elif verdict in ("valid", "skipped"):
            issues.pop(entity_id, None)
        # A "failed" verdict leaves whatever was known in place. The check could
        # not reach a conclusion, which is not evidence the entity is now fine.

    if record.get("state") == "running" and _stalled(record):
        record["state"] = "stalled"
    record["issues"] = sorted(issues.values(), key=lambda issue: issue["entity_id"])
    return record


def read_status(enabled=True, watcher=True):
    """Everything /anno/scan reports, merged from the files above."""
    payload = {
        "version": VERSION,
        "enabled": bool(enabled),
        "watcher": bool(watcher),
        "source": None,
        "repairs": {"state": "unknown", "issues": []},
        "recent": [],
    }
    root = status_dir()
    if root is None:
        return payload

    entities = _read_entities(root)
    payload["source"] = _read(root / "source.json")
    payload["repairs"] = _merge(_read(root / "full.json"), entities)
    payload["recent"] = sorted(
        entities, key=lambda record: record.get("finished") or 0, reverse=True
    )[:MAX_RECENT]
    return payload

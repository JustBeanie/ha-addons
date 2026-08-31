"""Targeted, report-only Docs-link checks for changed HA scripts/automations.

The initial and docs-source scans remain reconciliation passes.  This watcher
keeps normal operation cheap: Home Assistant state-change events are debounced
into one batch and invoke the canonical checker for just those entities.

One batch rather than one task per entity because the events do not only arrive
one at a time.  Saving an automation produces a pair, but a Home Assistant
restart adds every automation and script back at once -- around two hundred of
them here -- and a subprocess each would be a thundering herd doing the work of
one scan.  Batched, that burst settles into a single targeted check, which is
the reconciliation pass an HA restart deserves anyway and which nothing else
runs unless the docs happen to change.
"""

import asyncio
import datetime as dt
import logging
import os
import signal
import sys


LOGGER = logging.getLogger("ha_docs.entity_watch")
TRACE = 5
logging.addLevelName(TRACE, "TRACE")
RUNTIME_ATTRIBUTES = {
    "current", "last_action", "last_action_time", "last_reported", "last_triggered",
}


class LocalIsoFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802 - logging API name
        return dt.datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds")


def configure_logging(level: str) -> None:
    value = {"trace": TRACE, "debug": logging.DEBUG, "info": logging.INFO,
             "warning": logging.WARNING, "error": logging.ERROR}[level]
    handler = logging.StreamHandler()
    handler.setFormatter(LocalIsoFormatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(value)
    LOGGER.propagate = False


def is_runtime_state_change(event_data: dict) -> bool:
    """Return whether an entity event is only normal execution activity.

    Scripts change from off to on to off when executed.  Their ``current`` and
    ``last_triggered`` attributes also change as a normal side effect.  Those
    are not configuration edits, so a Docs-link validation would be noisy and
    pointless.  Ignore the same operational state flips for automations.

    Saving an automation or a script is the one case that must get through, and
    it does not arrive looking like an edit.  Home Assistant removes the single
    entity whose configuration changed and adds it back, which reaches this
    subscription as a ``new_state: null`` event followed by an ``old_state:
    null`` one.  A description lives in the configuration and never in the
    attributes, so a half-present event is the only evidence of an edit there
    is -- and reading one as a state flip, which is what comparing ``None``
    against ``"on"`` amounts to, discards every edit and every deletion.
    """
    entity_id = event_data.get("entity_id", "")
    if not entity_id:
        # Malformed rather than operational.  Keep it visible.
        return False
    old_state = event_data.get("old_state")
    new_state = event_data.get("new_state")
    if old_state is None or new_state is None:
        # The entity was added or removed: a configuration event either way.
        return False
    if old_state.get("state") != new_state.get("state"):
        return True
    old_attributes = {
        key: value for key, value in old_state.get("attributes", {}).items()
        if key not in RUNTIME_ATTRIBUTES
    }
    new_attributes = {
        key: value for key, value in new_state.get("attributes", {}).items()
        if key not in RUNTIME_ATTRIBUTES
    }
    # A same-state event with only last-run metadata is another ordinary
    # execution update.
    return old_attributes == new_attributes


class EntityWatcher:
    def __init__(self):
        self.token = os.environ["SUPERVISOR_TOKEN"]
        self.websocket_url = os.getenv("HA_DOCS_WS_URL", "ws://supervisor/core/websocket")
        self.repo = os.environ["HA_DOCS_REPO_DIR"]
        self.github_base = os.environ["HA_DOCS_GITHUB_BASE"]
        self.audit_file = os.environ["HA_DOC_LINK_AUDIT"]
        self.ready_file = os.getenv("HA_DOCS_READY_FILE", "/data/.doc-link-checker-ready")
        self.log_level = os.getenv("HA_DOCS_LOG_LEVEL", "info")
        self.debounce_seconds = int(os.getenv("HA_DOCS_ENTITY_DEBOUNCE", "3"))
        self.concurrency = os.getenv("HA_DOCS_SCAN_CONCURRENCY", "4")
        self.progress_interval = os.getenv("HA_DOCS_PROGRESS_INTERVAL", "25")
        self.heartbeat_interval = os.getenv("HA_DOCS_HEARTBEAT_INTERVAL", "10")
        self.pending: set[str] = set()
        self.debounce: asyncio.Task | None = None
        self.running: set[asyncio.Task] = set()
        self.stop = asyncio.Event()

    def described(self, entity_ids: list[str]) -> str:
        """How a batch is named in the log: the entity, or how many there are."""
        return entity_ids[0] if len(entity_ids) == 1 else f"{len(entity_ids)} changed entities"

    async def run_check(self, entity_ids: list[str]) -> None:
        described = self.described(entity_ids)
        try:
            LOGGER.info("[ha] Entity update detected; checking only entity=%s", described)
            selection = []
            for entity_id in entity_ids:
                selection += ["--entity-id", entity_id]
            process = await asyncio.create_subprocess_exec(
                sys.executable, "/opt/ha_docs/check_anchors.py", "--ha", "--report",
                *selection,
                "--log-level", self.log_level,
                "--scan-concurrency", self.concurrency,
                "--progress-interval", self.progress_interval,
                "--heartbeat-interval", self.heartbeat_interval,
                "--github-base", self.github_base,
                "--audit-file", self.audit_file,
                self.repo,
            )
            result = await process.wait()
            if result:
                LOGGER.error("[ha] Targeted Docs-link check failed: entity=%s exit_code=%d", described, result)
            else:
                LOGGER.info("[ha] Targeted Docs-link check complete: entity=%s", described)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # Keep event monitoring alive after one failure.
            LOGGER.error("[ha] Targeted Docs-link check error: entity=%s error=%s", described, exc)

    async def collect(self) -> None:
        """Wait out the debounce, then check everything that arrived during it.

        Restarted by every new event, so a burst is checked once it stops rather
        than once per entity.  The initial documentation sync is waited out first
        and not on the far side of the debounce: a check before it means nothing,
        and events arriving meanwhile should join this batch rather than each
        start one that then queues behind the same wait.
        """
        while not os.path.exists(self.ready_file) and not self.stop.is_set():
            LOGGER.debug(
                "[ha] Targeted Docs-link check waiting for initial source sync: pending=%d",
                len(self.pending),
            )
            await asyncio.sleep(1)
        if self.stop.is_set():
            return
        await asyncio.sleep(self.debounce_seconds)
        entity_ids = sorted(self.pending)
        self.pending.clear()
        self.debounce = None
        if not entity_ids:
            return
        task = asyncio.create_task(self.run_check(entity_ids))
        self.running.add(task)
        task.add_done_callback(self.running.discard)

    def queue_check(self, entity_id: str) -> None:
        self.pending.add(entity_id)
        if self.debounce and not self.debounce.done():
            self.debounce.cancel()
            LOGGER.debug("[ha] Entity update coalesced: entity=%s pending=%d", entity_id, len(self.pending))
        else:
            LOGGER.debug("[ha] Entity update queued: entity=%s", entity_id)
        self.debounce = asyncio.create_task(self.collect())

    async def watch_once(self) -> None:
        # Imported here rather than at module scope so that the pure event
        # predicate above can be unit tested without the package installed.
        import websockets

        async with websockets.connect(self.websocket_url, ping_interval=20, ping_timeout=20) as socket:
            greeting = await socket.recv()
            LOGGER.log(TRACE, "[ha] Entity-update websocket greeting received: bytes=%d", len(greeting))
            await socket.send('{"type":"auth","access_token":"' + self.token + '"}')
            auth = await socket.recv()
            if '"auth_ok"' not in auth:
                raise RuntimeError("Home Assistant websocket authentication failed")
            await socket.send('{"id":1,"type":"subscribe_events","event_type":"state_changed"}')
            subscribed = await socket.recv()
            if '"success":true' not in subscribed.replace(" ", ""):
                raise RuntimeError("Home Assistant websocket event subscription failed")
            LOGGER.info("[ha] Entity-update watcher connected: event=state_changed debounce=%ss", self.debounce_seconds)
            while not self.stop.is_set():
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                # Avoid retaining or logging descriptions/state data.  The
                # inexpensive substring guards most unrelated event traffic.
                if '"entity_id":"automation.' not in message and '"entity_id":"script.' not in message:
                    continue
                import json
                event = json.loads(message)
                data = event.get("event", {}).get("data", {})
                entity_id = data.get("entity_id", "")
                if entity_id.startswith(("automation.", "script.")):
                    if is_runtime_state_change(data):
                        LOGGER.debug("[ha] Entity runtime activity ignored: entity=%s", entity_id)
                        continue
                    self.queue_check(entity_id)

    async def run(self) -> None:
        while not self.stop.is_set():
            try:
                await self.watch_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("[ha] Entity-update watcher disconnected: error=%s retry_seconds=5", exc)
                await asyncio.sleep(5)

    async def close(self) -> None:
        self.stop.set()
        tasks = [task for task in (self.debounce, *self.running) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def main() -> int:
    configure_logging(os.getenv("HA_DOCS_LOG_LEVEL", "info"))
    watcher = EntityWatcher()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, watcher.stop.set)
    try:
        await watcher.run()
    finally:
        await watcher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

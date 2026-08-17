"""Targeted, report-only Docs-link checks for changed HA scripts/automations.

The initial and docs-source scans remain reconciliation passes.  This watcher
keeps normal operation cheap: Home Assistant state-change events are debounced
per entity and invoke the canonical checker for that one entity only.
"""

import asyncio
import datetime as dt
import logging
import os
import signal
import sys

import websockets


LOGGER = logging.getLogger("ha_docs.entity_watch")
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


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
        self.pending: dict[str, asyncio.Task] = {}
        self.stop = asyncio.Event()

    async def run_check(self, entity_id: str) -> None:
        try:
            while not os.path.exists(self.ready_file) and not self.stop.is_set():
                LOGGER.debug("[ha] Targeted Docs-link check waiting for initial source sync: entity=%s", entity_id)
                await asyncio.sleep(1)
            if self.stop.is_set():
                return
            await asyncio.sleep(self.debounce_seconds)
            LOGGER.info("[ha] Entity update detected; checking only entity=%s", entity_id)
            process = await asyncio.create_subprocess_exec(
                sys.executable, "/opt/ha_docs/check_anchors.py", "--ha", "--report",
                "--entity-id", entity_id,
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
                LOGGER.error("[ha] Targeted Docs-link check failed: entity=%s exit_code=%d", entity_id, result)
            else:
                LOGGER.info("[ha] Targeted Docs-link check complete: entity=%s", entity_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # Keep event monitoring alive after one failure.
            LOGGER.error("[ha] Targeted Docs-link check error: entity=%s error=%s", entity_id, exc)
        finally:
            self.pending.pop(entity_id, None)

    def queue_check(self, entity_id: str) -> None:
        current = self.pending.get(entity_id)
        if current and not current.done():
            current.cancel()
            LOGGER.debug("[ha] Entity update coalesced: entity=%s", entity_id)
        else:
            LOGGER.debug("[ha] Entity update queued: entity=%s", entity_id)
        self.pending[entity_id] = asyncio.create_task(self.run_check(entity_id))

    async def watch_once(self) -> None:
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
        for task in self.pending.values():
            task.cancel()
        if self.pending:
            await asyncio.gather(*self.pending.values(), return_exceptions=True)


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

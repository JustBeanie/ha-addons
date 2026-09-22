"""Batching, the checkout lock and shutdown in EntityWatcher (Plan 021 P4).

The watcher used to start a new checker subprocess whenever a debounce expired,
whether or not the previous one had finished, and cancelling it on shutdown
left the child running. These tests pin the replacement: one batch at a time,
nothing lost that arrives mid-check, a hard cap on how long a stream of events
can postpone a check, and a shutdown that takes the child down with it.
"""

import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

import entity_watch


def make_watcher(tmp, **overrides):
    ready = os.path.join(tmp, "ready")
    open(ready, "w").close()
    env = {
        "SUPERVISOR_TOKEN": "test",
        "HA_DOCS_REPO_DIR": tmp,
        "HA_DOCS_GITHUB_BASE": "https://github.com/example/docs/blob/main/",
        "HA_DOC_LINK_AUDIT": os.path.join(tmp, "audit.jsonl"),
        "HA_DOCS_READY_FILE": ready,
        "HA_DOCS_CHECKOUT_LOCK": overrides.pop("lock", ""),
    }
    with mock.patch.dict(os.environ, env):
        watcher = entity_watch.EntityWatcher()
    watcher.debounce_seconds = overrides.pop("debounce", 0.05)
    for name, value in overrides.items():
        setattr(watcher, name, value)
    return watcher


class Recorder:
    """Stands in for run_check: records each batch and how long it ran."""

    def __init__(self, duration):
        self.duration = duration
        self.batches = []
        self.running = 0
        self.max_running = 0

    async def __call__(self, entity_ids):
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        self.batches.append((time.monotonic(), list(entity_ids)))
        try:
            await asyncio.sleep(self.duration)
        finally:
            self.running -= 1


class BatchingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()

    async def settle(self, watcher, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            idle = watcher.debounce is None and watcher.active is None and not watcher.pending
            if idle:
                return
            await asyncio.sleep(0.02)
        self.fail("watcher did not settle")

    async def test_a_burst_becomes_one_batch(self):
        watcher = make_watcher(self.tmp)
        recorder = Recorder(0.01)
        watcher.run_check = recorder
        for entity_id in ("automation.a", "automation.b", "script.c"):
            watcher.queue_check(entity_id)
        await self.settle(watcher)
        self.assertEqual([["automation.a", "automation.b", "script.c"]],
                         [batch for _, batch in recorder.batches])

    async def test_batches_never_overlap_and_mid_check_arrivals_are_kept(self):
        watcher = make_watcher(self.tmp)
        recorder = Recorder(0.3)
        watcher.run_check = recorder
        watcher.queue_check("automation.first")
        await asyncio.sleep(0.15)  # debounce done, first batch running
        self.assertIsNotNone(watcher.active)
        watcher.queue_check("automation.second")
        watcher.queue_check("automation.third")
        await self.settle(watcher)

        self.assertEqual(1, recorder.max_running)
        self.assertEqual(
            [["automation.first"], ["automation.second", "automation.third"]],
            [batch for _, batch in recorder.batches],
        )

    async def test_a_steady_stream_cannot_postpone_the_check_past_the_cap(self):
        watcher = make_watcher(self.tmp, debounce=0.2, max_collect_seconds=0.4)
        recorder = Recorder(0.01)
        watcher.run_check = recorder
        started = time.monotonic()
        # An event every 0.1 s for 1.2 s: the 0.2 s debounce alone would
        # never expire until the stream stopped.
        for i in range(12):
            watcher.queue_check(f"automation.e{i}")
            await asyncio.sleep(0.1)
        await self.settle(watcher)

        self.assertTrue(recorder.batches)
        first_at = recorder.batches[0][0] - started
        self.assertLess(first_at, 0.7, "first batch waited for the stream to end")
        seen = sorted(e for _, batch in recorder.batches for e in batch)
        self.assertEqual(sorted(f"automation.e{i}" for i in range(12)), seen)

    async def test_waiting_for_the_initial_sync_does_not_count_against_the_cap(self):
        watcher = make_watcher(self.tmp, debounce=0.2, max_collect_seconds=0.3)
        os.remove(watcher.ready_file)
        recorder = Recorder(0.01)
        watcher.run_check = recorder
        watcher.queue_check("automation.a")
        await asyncio.sleep(1.2)
        self.assertEqual([], recorder.batches)
        open(watcher.ready_file, "w").close()
        ready_at = time.monotonic()
        await self.settle(watcher)
        # The window opens once the sync is done, so the debounce still applies.
        self.assertGreaterEqual(recorder.batches[0][0] - ready_at, 0.15)

    async def test_close_terminates_the_running_checker(self):
        watcher = make_watcher(self.tmp)
        watcher.command = lambda ids: [sys.executable, "-c", "import time; time.sleep(60)"]
        spawned = []
        real_exec = asyncio.create_subprocess_exec

        async def spy(*args, **kwargs):
            process = await real_exec(*args, **kwargs)
            spawned.append(process)
            return process

        with mock.patch.object(entity_watch.asyncio, "create_subprocess_exec", spy):
            watcher.queue_check("automation.a")
            deadline = time.monotonic() + 5
            while not spawned and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            self.assertTrue(spawned, "checker never started")
            began = time.monotonic()
            await watcher.close()

        self.assertIsNotNone(spawned[0].returncode, "checker outlived the watcher")
        self.assertLess(time.monotonic() - began, entity_watch.CHILD_TERMINATE_SECONDS + 1)


@unittest.skipIf(entity_watch.fcntl is None, "flock is POSIX-only")
class CheckoutLockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lock = os.path.join(self.tmp, ".checkout.lock")

    def hold(self):
        """Take the lock the way run.sh's flock does, from another descriptor."""
        fd = os.open(self.lock, os.O_RDWR | os.O_CREAT, 0o644)
        entity_watch.fcntl.flock(fd, entity_watch.fcntl.LOCK_EX)
        return fd

    async def test_a_check_waits_for_the_refresh_worker(self):
        watcher = make_watcher(self.tmp, lock=self.lock)
        watcher.command = lambda ids: [sys.executable, "-c", "pass"]
        fd = self.hold()
        task = asyncio.create_task(watcher.run_check(["automation.a"]))
        await asyncio.sleep(0.8)
        self.assertFalse(task.done(), "check ran while the checkout was locked")
        os.close(fd)
        await asyncio.wait_for(task, 5)

    async def test_close_is_prompt_while_the_lock_is_held_elsewhere(self):
        watcher = make_watcher(self.tmp, lock=self.lock)
        watcher.command = lambda ids: [sys.executable, "-c", "pass"]
        fd = self.hold()
        try:
            watcher.queue_check("automation.a")
            await asyncio.sleep(0.4)
            self.assertIsNotNone(watcher.active)
            began = time.monotonic()
            await asyncio.wait_for(watcher.close(), 3)
            self.assertLess(time.monotonic() - began, 2)
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main()

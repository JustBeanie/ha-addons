"""Read Home Assistant's Repairs issue registry over the websocket API.

The core REST API this add-on otherwise uses has no repairs endpoint, and a
scan cannot substitute for one: it enumerates the entities that exist and
decides what *should* be raised, so an issue whose entity has been deleted is
invisible to it forever.  Nothing else ever revisits that issue.  One websocket
round trip per poll is what closes the gap.

``websockets`` is imported inside the coroutine rather than at module scope, the
same arrangement ``entity_watch.py`` uses, so that ``check_anchors.py`` still
imports on a workstation that has never installed it.

Nothing here raises.  An unreadable registry means one sweep is skipped, which
is a cleanup postponed rather than a check that failed, so callers are handed
``None`` -- distinct from an empty set, which means the registry was read and
holds nothing of ours.
"""

import asyncio
import json
import logging


LOGGER = logging.getLogger("ha_docs.repairs_registry")

# Spook files an issue created through ``repairs.create`` under its own domain
# with a ``user_`` prefix, and takes the bare id back in ``repairs.remove``.
# Strip it on the way in so an id read out of the registry is the same string
# that was put in, and can be handed straight back to the remove action.
USER_PREFIX = "user_"

# The registry is small and the connection is local; a poll must not be able to
# sit on a half-open socket for the length of its own interval.
TIMEOUT = 30


def link_issue_ids(payload, prefix):
    """Bare ids of the open issues under ``prefix``, from a list_issues result."""
    if not isinstance(payload, dict):
        return set()
    result = payload.get("result")
    if not isinstance(result, dict):
        return set()
    issues = result.get("issues", [])
    found = set()
    for issue in issues if isinstance(issues, list) else []:
        if not isinstance(issue, dict):
            continue
        issue_id = issue.get("issue_id") or ""
        if not isinstance(issue_id, str):
            continue
        if issue_id.startswith(USER_PREFIX):
            issue_id = issue_id[len(USER_PREFIX):]
        if issue_id.startswith(prefix):
            found.add(issue_id)
    return found


async def _list_issues(ws_url, token):
    import websockets

    async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as socket:
        await socket.recv()
        await socket.send(json.dumps({"type": "auth", "access_token": token}))
        auth = await socket.recv()
        if '"auth_ok"' not in auth:
            raise RuntimeError("Home Assistant websocket authentication failed")
        await socket.send(json.dumps({"id": 1, "type": "repairs/list_issues"}))
        while True:
            message = json.loads(await socket.recv())
            # Events for another subscription cannot arrive on a socket that has
            # made no subscription, but the id check costs nothing and keeps this
            # correct if one is ever added above.
            if message.get("id") != 1 or message.get("type") != "result":
                continue
            if not message.get("success"):
                raise RuntimeError(f"repairs/list_issues failed: {message.get('error')}")
            return message


def open_link_issue_ids(ws_url, token, prefix, timeout=TIMEOUT):
    """Open issue ids under ``prefix``, or None when the registry cannot be read."""
    try:
        payload = asyncio.run(asyncio.wait_for(_list_issues(ws_url, token), timeout))
    # Broad on purpose: this is a best-effort cleanup, and every failure here --
    # an import error, a refused connection, a protocol change in the command --
    # has the same correct answer, which is to leave the issues alone and say so.
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("[ha] Repairs registry unreadable, orphan sweep skipped: error=%s", exc)
        return None
    return link_issue_ids(payload, prefix)

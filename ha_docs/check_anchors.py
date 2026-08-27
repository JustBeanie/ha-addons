"""Verify documentation anchors, including Home Assistant descriptions.

Two modes, run in sequence:

  --source  compare link targets against slugs computed from the markdown
            headings themselves. Tests the slugifier against ground truth:
            the anchors in these docs were copied from GitHub's own output,
            so agreement means the slugifier matches GitHub.

  --site    compare link targets against the id="" attributes MkDocs actually
            emitted into the built HTML. Tests the whole pipeline.

Usage:
    python check_anchors.py --source <repo_dir>
    python check_anchors.py --site <repo_dir> <site_dir>
    python check_anchors.py --ha --repair --github-base <blob-url> <repo_dir>

The ``--ha`` mode uses Home Assistant's authenticated core configuration API,
never the ``.storage`` files.  It deliberately repairs only three
deterministic cases: a legacy marker, a unique Entity Index destination, or a
unique heading matching an otherwise broken anchor.  Anything else remains a
visible failure.
"""

import argparse
import copy
import datetime as dt
import hashlib
import json
import logging
import os
import pathlib
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import urllib.error
import urllib.parse
import urllib.request

import ghslug
import scan_status


TRACE = 5
logging.addLevelName(TRACE, "TRACE")
LOGGER = logging.getLogger("ha_docs.check_anchors")


class LocalIsoFormatter(logging.Formatter):
    """Render every scanner message with the HA host's local ISO timestamp."""

    def formatTime(self, record, datefmt=None):  # noqa: N802 - logging API name
        return dt.datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds")


def configure_logging(level: str = "info", stream=None) -> None:
    """Configure a compact, token-safe CLI logger for every scanner mode."""
    value = {"trace": TRACE, "debug": logging.DEBUG, "info": logging.INFO,
             "warning": logging.WARNING, "error": logging.ERROR}.get(level.casefold())
    if value is None:
        raise ValueError(f"unsupported log level: {level}")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(LocalIsoFormatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(value)
    LOGGER.propagate = False


configure_logging()

# [text](target)  -- target may be "file.md#anchor", "#anchor", "file.md"
LINK_RE = re.compile(r"\[(?:[^\]\\]|\\.)*\]\(([^)\s]+)\)")
# ATX headings, ignoring those inside fenced code blocks (stripped separately).
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
ID_RE = re.compile(r'\bid="([^"]+)"')
# Inline markdown that python-markdown's toc strips before slugifying.
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
INLINE_EMPH_RE = re.compile(r"\*\*([^*]*)\*\*|\*([^*]*)\*|__([^_]*)__")
INLINE_LINK_RE = re.compile(r"\[((?:[^\]\\]|\\.)*)\]\([^)]*\)")
DOCS_RE = re.compile(r"(?m)(?P<marker>📖 Docs:|Docs:)\s*(?P<url>https://[^\s)]+)")
INDEX_ROW_RE = re.compile(
    r"^\|\s*`(?P<entity>(?:automation|script)\.[^`]+)`.*?\]\((?P<target>docs/[^)#]+\.md#[^)]+)\)",
    re.MULTILINE,
)

# One issue for one condition -- "the site is frozen" -- rather than one per
# link, because the reader can only act on all of them at once anyway.
SOURCE_REPAIR_ISSUE_ID = "ha_docs_source_anchors"
# The check runs on every poll, so the push has to be edge-triggered or it is
# ~96 identical notifications a day.  A marker file rather than in-memory state
# because each run is a short-lived subprocess.  Overridable so that a run
# outside the add-on cannot touch /data.
SOURCE_ALERT_MARKER = pathlib.Path(os.getenv("HA_DOCS_SOURCE_ALERT_MARKER", "/data/.source_alerted"))


def heading_text(raw: str) -> str:
    """Reduce a raw heading to the plain text the toc extension slugifies."""
    text = INLINE_LINK_RE.sub(r"\1", raw)
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = INLINE_EMPH_RE.sub(lambda m: next(g for g in m.groups() if g is not None), text)
    return text.strip()


def strip_fences(text: str) -> str:
    return FENCE_RE.sub("", text)


def md_files(repo: pathlib.Path):
    return sorted(p for p in repo.rglob("*.md") if ".git" not in p.parts)


def collect_headings(repo: pathlib.Path) -> dict[pathlib.Path, set[str]]:
    """file -> set of slugs its headings generate."""
    out = {}
    for path in md_files(repo):
        body = strip_fences(path.read_text(encoding="utf-8"))
        slugs, seen = set(), {}
        for _, raw in HEADING_RE.findall(body):
            base = ghslug.slugify(heading_text(raw))
            # GitHub disambiguates repeats with -1, -2, ...
            count = seen.get(base, 0)
            seen[base] = count + 1
            slugs.add(base if count == 0 else f"{base}-{count}")
        out[path.relative_to(repo)] = slugs
    return out


def collect_links(repo: pathlib.Path):
    """Yield (source_file, target_file_or_None, anchor, raw_target)."""
    for path in md_files(repo):
        body = strip_fences(path.read_text(encoding="utf-8"))
        for target in LINK_RE.findall(body):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if "#" not in target:
                continue
            file_part, _, anchor = target.partition("#")
            if not anchor:
                continue
            if file_part:
                resolved = (path.parent / file_part).resolve()
                try:
                    rel = resolved.relative_to(repo.resolve())
                except ValueError:
                    continue
            else:
                rel = path.relative_to(repo)
            yield path.relative_to(repo), rel, anchor, target


def source_repair_description(broken: list[dict[str, str]]) -> str:
    """Human-facing remediation text for the gated-rebuild Repairs issue."""
    lines = [
        "The docs site is **frozen**. Its source anchor check failed, so the add-on is",
        "still serving the last commit that passed, and will keep doing so until these",
        "links are fixed:",
        "",
    ]
    lines += [f"- `{item['source']}` -> `{item['target']}` ({item['problem']})" for item in broken]
    lines += [
        "",
        "Fix the link -- or add the heading it expects -- in the docs repository and",
        "push. The next poll rebuilds the site and clears this issue by itself.",
    ]
    return "\n".join(lines)


def announce_source_result(api, notify_service: str | None, bad: int, broken: list[dict[str, str]]) -> None:
    """Report a gated rebuild through Repairs, and push once on the way in.

    Best-effort throughout, and deliberately returns nothing: the caller's exit
    code is what gates the rebuild, so a Repairs or notify outage must never be
    able to publish unvalidated docs -- nor to hold back a clean one.
    """
    try:
        if bad:
            api.call_service("repairs", "create", {
                "issue_id": SOURCE_REPAIR_ISSUE_ID,
                "title": f"HA Docs site is frozen: {bad} broken anchor(s)",
                "description": source_repair_description(broken),
                "severity": "warning",
                "persistent": True,
            })
            LOGGER.warning("[source] Repair raised: broken=%d location=Settings > System > Repairs", bad)
        else:
            try:
                api.call_service("repairs", "remove", {"issue_id": SOURCE_REPAIR_ISSUE_ID})
            except (RuntimeError, OSError):
                # No pre-existing issue is the normal case; same best-effort
                # rule as the per-entity removals in check_ha.
                pass
    # OSError as well as RuntimeError: CoreApiError only covers an HTTP status.
    # A refused connection surfaces as urllib.error.URLError, and letting that
    # escape would make an HA blip look like a failed check and freeze the site.
    except (RuntimeError, OSError) as exc:
        LOGGER.error("[source] Repair report failed: error=%s", exc)

    try:
        if not bad:
            SOURCE_ALERT_MARKER.unlink(missing_ok=True)
        elif notify_service and not SOURCE_ALERT_MARKER.exists():
            domain, _, service = notify_service.partition(".")
            if not service:
                domain, service = "notify", notify_service
            api.call_service(domain, service, {
                "title": "Docs site frozen",
                "message": (f"{bad} broken anchor(s) failed the check. HA Docs is still serving "
                            "the previous commit. See Settings > System > Repairs."),
            })
            # Stamped only once the push actually landed, so a wrong service
            # name retries next poll instead of swallowing the one alert.
            SOURCE_ALERT_MARKER.parent.mkdir(parents=True, exist_ok=True)
            SOURCE_ALERT_MARKER.touch()
            LOGGER.warning("[source] Failure notification sent: service=%s", notify_service)
    except (RuntimeError, OSError) as exc:
        LOGGER.error("[source] Failure notification failed: error=%s", exc)


def check_source(repo: pathlib.Path, api=None, notify_service: str | None = None) -> int:
    headings = collect_headings(repo)
    total = bad = 0
    # Collected as well as logged, because a non-zero result here stops the
    # rebuild - so the site keeps serving the previous commit, and the reader
    # needs to see why from the site rather than from the add-on log.
    broken: list[dict[str, str]] = []
    for src, target_file, anchor, raw in collect_links(repo):
        total += 1
        slugs = headings.get(target_file)
        if slugs is None:
            LOGGER.warning("[source] missing file: %s -> %s", src, raw)
            bad += 1
            broken.append({"source": src.as_posix(), "target": raw, "problem": "missing file"})
        elif anchor not in slugs:
            LOGGER.warning("[source] broken anchor: %s -> %s", src, raw)
            bad += 1
            broken.append({"source": src.as_posix(), "target": raw, "problem": "broken anchor"})
    LOGGER.info("[source] anchor check complete: checked=%d broken=%d", total, bad)
    scan_status.write_source(total, bad, broken)
    # No api means no reporting surface -- a --source run on a workstation stays
    # silent, the same way an unset HA_DOCS_SCAN_STATUS_DIR makes the status
    # writers no-ops.
    if api is not None:
        announce_source_result(api, notify_service, bad, broken)
    return bad


def check_site(repo: pathlib.Path, site: pathlib.Path) -> int:
    ids = {}
    for html in site.rglob("*.html"):
        ids[html.relative_to(site)] = set(ID_RE.findall(html.read_text(encoding="utf-8")))
    total = bad = 0
    for src, target_file, anchor, raw in collect_links(repo):
        total += 1
        html_name = target_file.with_suffix(".html")
        # MkDocs renders README.md as index.html
        if html_name.name == "README.html":
            html_name = html_name.with_name("index.html")
        page_ids = ids.get(html_name)
        if page_ids is None:
            LOGGER.warning("[site] missing page: %s -> %s (expected %s)", src, raw, html_name)
            bad += 1
        elif anchor not in page_ids:
            LOGGER.warning("[site] broken anchor: %s -> %s", src, raw)
            bad += 1
    LOGGER.info("[site] anchor check complete: checked=%d broken=%d", total, bad)
    return bad


def config_hash(config: dict) -> str:
    """Stable local version used to detect a concurrent UI edit."""
    return hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def canonicalize(value: str) -> str:
    """Compare human wording independent of punctuation and separators."""
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def headings_with_text(repo: pathlib.Path) -> dict[pathlib.Path, list[tuple[str, str]]]:
    """file -> (GitHub slug, plain heading text), retaining duplicate text."""
    out = {}
    for path in md_files(repo):
        body = strip_fences(path.read_text(encoding="utf-8"))
        values, seen = [], {}
        for _, raw in HEADING_RE.findall(body):
            text = heading_text(raw)
            base = ghslug.slugify(text)
            count = seen.get(base, 0)
            seen[base] = count + 1
            values.append((base if count == 0 else f"{base}-{count}", text))
        out[path.relative_to(repo)] = values
    return out


def entity_index_targets(repo: pathlib.Path) -> dict[str, list[str]]:
    """Read only explicit entity-to-anchor rows from ENTITY-INDEX.md."""
    index = repo / "ENTITY-INDEX.md"
    if not index.exists():
        return {}
    targets: dict[str, list[str]] = {}
    for match in INDEX_ROW_RE.finditer(index.read_text(encoding="utf-8")):
        targets.setdefault(match.group("entity"), []).append(match.group("target"))
    return targets


def url_target(url: str, github_base: str) -> tuple[pathlib.Path, str] | None:
    """Turn one repository URL into a repo-relative file and fragment."""
    prefix = github_base.rstrip("/") + "/"
    if not url.startswith(prefix):
        return None
    relative = urllib.parse.unquote(url[len(prefix) :])
    file_part, sep, anchor = relative.partition("#")
    if not sep or not file_part or not anchor:
        return None
    return pathlib.Path(file_part), anchor


def valid_doc_url(url: str, repo: pathlib.Path, github_base: str, headings: dict) -> bool:
    target = url_target(url, github_base)
    return bool(target and target[0] in headings and target[1] in headings[target[0]])


def unique_heading_repair(url: str, repo: pathlib.Path, github_base: str, detailed_headings: dict) -> str | None:
    """Return a repaired URL only when one heading has matching wording."""
    target = url_target(url, github_base)
    if not target or target[0] not in detailed_headings:
        return None
    wanted = canonicalize(target[1])
    matches = [slug for slug, text in detailed_headings[target[0]] if canonicalize(text) == wanted]
    if len(matches) != 1:
        return None
    return f"{github_base.rstrip('/')}/{target[0].as_posix()}#{matches[0]}"


class CoreApiError(RuntimeError):
    """An HA Core API failure with its HTTP status retained for callers."""

    def __init__(self, method: str, path: str, status: int, detail: str):
        self.method = method
        self.path = path
        self.status = status
        self.detail = detail
        super().__init__(f"HA {method} {path}: {status} {detail}")


class CoreApi:
    """Minimal, injectable client for the authenticated HA core API."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.config_identifiers: dict[str, str] = {}

    def request(self, method: str, path: str, body=None):
        LOGGER.log(TRACE, "[ha] API request: method=%s path=%s", method, path)
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}", data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                LOGGER.log(TRACE, "[ha] API response: method=%s path=%s status=%s", method, path, response.status)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CoreApiError(method, path, exc.code, detail) from exc

    def remember_config_identifier(self, state: dict) -> str | None:
        """Record the API config key for one live automation or script state."""
        entity_id = state.get("entity_id", "")
        if not entity_id.startswith(("automation.", "script.")):
            return None
        if entity_id.startswith("automation."):
            # Automation editor URLs use the immutable config ``id`` rather
            # than the registry object_id. Scripts use their storage key.
            config_id = state.get("attributes", {}).get("id")
            if not config_id:
                raise RuntimeError(f"automation {entity_id} has no configuration id")
            self.config_identifiers[entity_id] = str(config_id)
        else:
            self.config_identifiers[entity_id] = entity_id.split(".", 1)[1]
        return entity_id

    def entity_ids(self) -> list[str]:
        states = self.request("GET", "states")
        entity_ids = []
        for state in states:
            entity_id = self.remember_config_identifier(state)
            if entity_id:
                entity_ids.append(entity_id)
        return sorted(entity_ids)

    def prepare_entity(self, entity_id: str) -> bool:
        """Load one entity's state so a targeted check has its config key."""
        state = self.request("GET", f"states/{entity_id}")
        return self.remember_config_identifier(state) == entity_id

    def get_config(self, entity_id: str) -> dict:
        domain, object_id = entity_id.split(".", 1)
        config_id = self.config_identifiers.get(entity_id, object_id)
        payload = self.request("GET", f"config/{domain}/config/{config_id}")
        # The endpoint may return either config directly or its normal envelope.
        return payload.get("config", payload)

    def set_config(self, entity_id: str, config: dict) -> None:
        domain, object_id = entity_id.split(".", 1)
        config_id = self.config_identifiers.get(entity_id, object_id)
        self.request("POST", f"config/{domain}/config/{config_id}", config)

    def call_service(self, domain: str, service: str, data: dict) -> None:
        self.request("POST", f"services/{domain}/{service}", data)


def audit(path: pathlib.Path, **record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record["timestamp"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def reconcile_description(entity_id: str, config: dict, repo: pathlib.Path, github_base: str,
                          headings: dict, detailed_headings: dict, index: dict) -> tuple[str, str | None, str | None]:
    """Return (outcome, replacement_description, repair_rule)."""
    description = config.get("description", "")
    links = list(DOCS_RE.finditer(description))
    if len(links) != 1:
        return f"expected exactly one Docs link, found {len(links)}", None, None
    link = links[0]
    url = link.group("url")
    if valid_doc_url(url, repo, github_base, headings):
        if link.group("marker") == "Docs:":
            return "repair", description[: link.start("marker")] + "📖 Docs:" + description[link.end("marker"):], "legacy-marker"
        return "valid", None, None

    targets = index.get(entity_id, [])
    if len(targets) == 1:
        canonical = f"{github_base.rstrip('/')}/{targets[0]}"
        if valid_doc_url(canonical, repo, github_base, headings):
            return "repair", description[: link.start("url")] + canonical + description[link.end("url"):], "entity-index"
    heading_url = unique_heading_repair(url, repo, github_base, detailed_headings)
    if heading_url:
        return "repair", description[: link.start("url")] + heading_url + description[link.end("url"):], "unique-heading"
    return "broken or ambiguous Docs target", None, None


def repair_issue_id(entity_id: str) -> str:
    return "ha_docs_link_" + re.sub(r"[^a-z0-9_]+", "_", entity_id.casefold())


def repair_instruction(entity_id: str, config: dict, outcome: str, replacement: str | None, rule: str | None) -> str:
    """Human-facing, report-only remediation text for a Spook Repairs issue."""
    link = DOCS_RE.search(config.get("description", ""))
    found = f"`{link.group('marker')} {link.group('url')}`" if link else "no recognizable Docs link"
    if rule == "legacy-marker":
        action = "Replace `Docs:` with `📖 Docs:`; leave the URL and every other field unchanged."
    elif rule in {"entity-index", "unique-heading"} and replacement:
        proposed = DOCS_RE.search(replacement).group("url")
        action = f"Replace the current Docs URL with `{proposed}`; leave every other field unchanged."
    else:
        action = "Manually add exactly one valid `📖 Docs:` URL that points to the documented entity section."
    return (
        f"Entity: `{entity_id}`\n\n"
        f"Detected Docs link: {found}\n\n"
        f"Problem: {outcome}.\n\n"
        f"What to fix: {action}\n\n"
        "Open this automation or script in Home Assistant and edit only its description. "
        "HA Docs only reported this Repair; it did not modify the entity."
    )


def check_ha(repo: pathlib.Path, api: CoreApi, github_base: str, report: bool, audit_file: pathlib.Path,
             concurrency: int = 4, progress_interval: int = 25, heartbeat_interval: int = 10,
             selected_entity_ids: list[str] | None = None) -> int:
    """Report invalid HA Docs links without changing Home Assistant config."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if progress_interval < 1:
        raise ValueError("progress_interval must be at least 1")
    if heartbeat_interval < 1:
        raise ValueError("heartbeat_interval must be at least 1")
    headings = collect_headings(repo)
    detailed_headings = headings_with_text(repo)
    index = entity_index_targets(repo)
    failures = raised = healthy = removal_attempts = skipped_missing_config = 0
    # Only a full scan reports a whole-instance picture worth recording as one;
    # a targeted check records its single verdict instead. `scan_state` starts
    # pessimistic so that an exception on the way out is reported as a failure
    # rather than as a scan that quietly succeeded.
    full_scan = selected_entity_ids is None
    issues: list[dict[str, str | None]] = []
    scan_state = "failed"
    if selected_entity_ids is None:
        entity_ids = api.entity_ids()
        scan_kind = "full"
    else:
        entity_ids = sorted(set(selected_entity_ids))
        scan_kind = "targeted"
        # CoreApi needs one state read to obtain an automation's immutable
        # config id.  Test doubles and callers that already know the id need
        # not implement this optional convenience method.
        prepare = getattr(api, "prepare_entity", None)
        if prepare is not None:
            live_ids = []
            for entity_id in entity_ids:
                try:
                    if prepare(entity_id):
                        live_ids.append(entity_id)
                    else:
                        LOGGER.info("[ha] Docs-link targeted check skipped: entity=%s reason=not-automation-or-script", entity_id)
                except CoreApiError as exc:
                    if exc.status == 404:
                        LOGGER.info("[ha] Docs-link targeted check skipped: entity=%s reason=entity-missing", entity_id)
                        audit(audit_file, entity_id=entity_id, outcome="skipped-missing-entity")
                        continue
                    raise
            entity_ids = live_ids
    LOGGER.info(
        "[ha] Docs-link Repair scan started: kind=%s entities=%d report_only=%s concurrency=%d progress_every=%d heartbeat_every=%ds",
        scan_kind, len(entity_ids), report, concurrency, progress_interval, heartbeat_interval,
    )
    if full_scan:
        scan_status.begin_full(len(entity_ids), heartbeat_interval)

    try:
        def read_config(entity_id: str):
            try:
                return entity_id, api.get_config(entity_id), None
            except RuntimeError as exc:
                return entity_id, None, exc

        # Reads are bounded and parallel; Repair actions remain ordered and serial
        # below so repeated scans update a given Spook issue deterministically.
        results = {}
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="ha-docs") as executor:
            futures = {executor.submit(read_config, entity_id): entity_id for entity_id in entity_ids}
            pending = set(futures)
            completed = 0
            LOGGER.info("[ha] Docs-link scan dispatched: queued=%d active_workers=%d", len(futures), concurrency)
            while pending:
                done, pending = wait(pending, timeout=heartbeat_interval, return_when=FIRST_COMPLETED)
                if not done:
                    active = sum(future.running() for future in pending)
                    LOGGER.info(
                        "[ha] Docs-link scan waiting for HA config API: completed=%d total=%d active=%d queued=%d",
                        completed, len(entity_ids), active, len(pending) - active,
                    )
                    # Also bumps the status heartbeat.  A scan legitimately
                    # waiting on a slow config API must not read as stalled.
                    scan_status.update_full(completed=completed)
                    continue
                for future in done:
                    entity_id, config, read_error = future.result()
                    results[entity_id] = config, read_error
                    completed += 1
                    if completed == 1 or completed % progress_interval == 0 or completed == len(entity_ids):
                        LOGGER.info("[ha] Docs-link scan progress: completed=%d total=%d current=%s", completed, len(entity_ids), entity_id)
                    scan_status.update_full(completed=completed, current=entity_id)

        for entity_id in entity_ids:
            config, read_error = results[entity_id]
            if read_error is not None:
                if isinstance(read_error, CoreApiError) and read_error.status == 404:
                    # A registry state can outlive its storage configuration after
                    # an upgrade or manual deletion.  It is neither a bad Docs
                    # link nor a failed scan; clean any old HA Docs issue and let
                    # Home Assistant own the stale-record cleanup.
                    skipped_missing_config += 1
                    LOGGER.info("[ha] Docs-link config skipped: entity=%s reason=configuration-missing", entity_id)
                    audit(audit_file, entity_id=entity_id, outcome="skipped-missing-config")
                    if report:
                        try:
                            api.call_service("repairs", "remove", {"issue_id": repair_issue_id(entity_id)})
                            removal_attempts += 1
                        except RuntimeError:
                            pass
                    if not full_scan:
                        scan_status.write_entity(entity_id, "skipped", reason="configuration missing")
                    continue
                LOGGER.warning("[ha] Docs-link config read failed: entity=%s error=%s", entity_id, read_error)
                audit(audit_file, entity_id=entity_id, outcome="failed", reason=f"configuration read failed: {read_error}")
                failures += 1
                if not full_scan:
                    scan_status.write_entity(entity_id, "failed", reason="configuration read failed")
                continue
            outcome, replacement, rule = reconcile_description(
                entity_id, config, repo, github_base, headings, detailed_headings, index
            )
            if outcome == "valid":
                healthy += 1
                LOGGER.debug("[ha] Docs link valid: entity=%s", entity_id)
                if report:
                    try:
                        api.call_service("repairs", "remove", {"issue_id": repair_issue_id(entity_id)})
                        removal_attempts += 1
                        LOGGER.debug("[ha] Repair removal requested: entity=%s", entity_id)
                    except RuntimeError:
                        # No pre-existing issue is normal; the remove action is
                        # deliberately best-effort and must not mark a valid link bad.
                        pass
                if not full_scan:
                    # Recorded even though the audit file deliberately never
                    # records a healthy verdict: this is what clears a repaired
                    # entity from the site panel before the next full scan.
                    scan_status.write_entity(entity_id, "valid")
                continue
            try:
                api.call_service("repairs", "create", {
                    "issue_id": repair_issue_id(entity_id),
                    "title": f"HA Docs link needs repair: {entity_id}",
                    "description": repair_instruction(entity_id, config, outcome, replacement, rule),
                    "severity": "warning",
                    "persistent": True,
                })
            except RuntimeError as exc:
                LOGGER.error("[ha] Repair report failed: entity=%s error=%s", entity_id, exc)
                audit(audit_file, entity_id=entity_id, outcome="failed", reason=f"could not raise repair: {exc}")
                failures += 1
                if not full_scan:
                    scan_status.write_entity(entity_id, "failed", reason="could not raise repair")
                continue
            raised += 1
            # config_id is what the site panel needs to deep-link into the
            # automation or script editor.  getattr because a test double is
            # not obliged to carry CoreApi's identifier cache.
            config_id = getattr(api, "config_identifiers", {}).get(entity_id)
            if full_scan:
                issues.append({
                    "entity_id": entity_id, "reason": outcome,
                    "rule": rule, "config_id": config_id,
                })
            else:
                scan_status.write_entity(
                    entity_id, "repair-raised", reason=outcome, rule=rule, config_id=config_id
                )
            audit(audit_file, entity_id=entity_id, outcome="repair-raised", reason=outcome, repair_rule=rule)
            LOGGER.warning("[ha] Repair raised: entity=%s rule=%s location=Settings > System > Repairs", entity_id, rule or "manual-review")
        LOGGER.info(
            "[ha] Docs-link Repair scan complete: healthy=%d repairs_raised=%d repair_removals_requested=%d skipped_missing_config=%d failures=%d",
            healthy, raised, removal_attempts, skipped_missing_config, failures,
        )
        scan_state = "complete" if not failures else "failed"
        return failures
    finally:
        # In a finally so that an exception on the way out still lands a
        # terminal record.  Without it the status file would sit on "running"
        # until the reader aged its heartbeat out, reporting a scan that is no
        # longer happening.
        if full_scan:
            scan_status.finish_full(
                scan_state, issues,
                healthy=healthy, raised=raised, removals=removal_attempts,
                skipped=skipped_missing_config, failures=failures,
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="store_true")
    ap.add_argument("--site", action="store_true")
    ap.add_argument("--ha", action="store_true", help="validate automation/script Docs links through the HA API")
    ap.add_argument("--report", action="store_true", help="raise Spook Repairs issues; never modify descriptions")
    ap.add_argument("--log-level", default=os.getenv("HA_DOCS_LOG_LEVEL", "info"),
                    choices=("trace", "debug", "info", "warning", "error"))
    ap.add_argument("--scan-concurrency", type=int, default=int(os.getenv("HA_DOCS_SCAN_CONCURRENCY", "4")))
    ap.add_argument("--progress-interval", type=int, default=int(os.getenv("HA_DOCS_PROGRESS_INTERVAL", "25")))
    ap.add_argument("--heartbeat-interval", type=int, default=int(os.getenv("HA_DOCS_HEARTBEAT_INTERVAL", "10")))
    ap.add_argument("--entity-id", action="append", dest="entity_ids", metavar="ENTITY_ID",
                    help="check only this automation or script; repeatable")
    ap.add_argument("--github-base", help="repository blob URL prefix, e.g. https://github.com/o/r/blob/main")
    ap.add_argument("--notify-service", default=os.getenv("HA_DOCS_NOTIFY_SERVICE"),
                    help="notify service alerted when a failed source check freezes the site, "
                         "e.g. notify.mobile_app_phone; unset raises the Repair only")
    ap.add_argument("--ha-api", default=os.getenv("HA_API_URL", "http://supervisor/core/api"))
    ap.add_argument("--audit-file", type=pathlib.Path, default=pathlib.Path(os.getenv("HA_DOC_LINK_AUDIT", "/data/doc-link-repairs.jsonl")))
    ap.add_argument("repo", type=pathlib.Path)
    ap.add_argument("site_dir", type=pathlib.Path, nargs="?")
    args = ap.parse_args()
    configure_logging(args.log_level)

    if args.site:
        if args.site_dir is None:
            ap.error("--site requires site_dir")
        return check_site(args.repo, args.site_dir)
    if args.ha:
        if not args.github_base:
            ap.error("--ha requires --github-base")
        token = os.getenv("SUPERVISOR_TOKEN")
        if not token:
            ap.error("--ha requires SUPERVISOR_TOKEN")
        return check_ha(args.repo, CoreApi(args.ha_api, token), args.github_base, args.report, args.audit_file,
                        args.scan_concurrency, args.progress_interval, args.heartbeat_interval, args.entity_ids)
    api = None
    if args.report:
        token = os.getenv("SUPERVISOR_TOKEN")
        if token:
            api = CoreApi(args.ha_api, token)
        else:
            LOGGER.warning("[source] --report ignored: SUPERVISOR_TOKEN is not set")
    return check_source(args.repo, api, args.notify_service)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)

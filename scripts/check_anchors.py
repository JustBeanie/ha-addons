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
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import ghslug

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


def check_source(repo: pathlib.Path) -> int:
    headings = collect_headings(repo)
    total = bad = 0
    for src, target_file, anchor, raw in collect_links(repo):
        total += 1
        slugs = headings.get(target_file)
        if slugs is None:
            print(f"MISSING FILE  {src} -> {raw}")
            bad += 1
        elif anchor not in slugs:
            print(f"BROKEN ANCHOR {src} -> {raw}")
            bad += 1
    print(f"\n[source] {total} anchor links checked, {bad} broken")
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
            print(f"MISSING PAGE  {src} -> {raw}  (expected {html_name})")
            bad += 1
        elif anchor not in page_ids:
            print(f"BROKEN ANCHOR {src} -> {raw}")
            bad += 1
    print(f"\n[site] {total} anchor links checked, {bad} broken")
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


class CoreApi:
    """Minimal, injectable client for the authenticated HA core API."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.config_identifiers: dict[str, str] = {}

    def request(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}", data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HA {method} {path}: {exc.code} {detail}") from exc

    def entity_ids(self) -> list[str]:
        states = self.request("GET", "states")
        entity_ids = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(("automation.", "script.")):
                continue
            if entity_id.startswith("automation."):
                config_id = state.get("attributes", {}).get("id")
                if not config_id:
                    raise RuntimeError(f"automation {entity_id} has no configuration id")
                self.config_identifiers[entity_id] = str(config_id)
            else:
                self.config_identifiers[entity_id] = entity_id.split(".", 1)[1]
            entity_ids.append(entity_id)
        return sorted(entity_ids)

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


def check_ha(repo: pathlib.Path, api: CoreApi, github_base: str, repair: bool, audit_file: pathlib.Path) -> int:
    headings = collect_headings(repo)
    detailed_headings = headings_with_text(repo)
    index = entity_index_targets(repo)
    bad = repaired = 0
    for entity_id in api.entity_ids():
        config = api.get_config(entity_id)
        before_hash = config_hash(config)
        outcome, replacement, rule = reconcile_description(
            entity_id, config, repo, github_base, headings, detailed_headings, index
        )
        if outcome == "valid":
            continue
        if outcome != "repair" or not repair:
            print(f"HA DOC LINK {entity_id}: {outcome}")
            audit(audit_file, entity_id=entity_id, outcome="failed", reason=outcome)
            bad += 1
            continue
        latest = api.get_config(entity_id)
        if config_hash(latest) != before_hash:
            print(f"HA DOC LINK {entity_id}: configuration changed concurrently")
            audit(audit_file, entity_id=entity_id, outcome="conflict", reason="config hash changed")
            bad += 1
            continue
        updated = copy.deepcopy(latest)
        old_url = DOCS_RE.search(updated.get("description", "")).group("url")
        updated["description"] = replacement
        # Defensive invariant: the write payload differs only in description.
        compare_before, compare_after = copy.deepcopy(latest), copy.deepcopy(updated)
        compare_before.pop("description", None)
        compare_after.pop("description", None)
        if compare_before != compare_after:
            raise AssertionError("repair attempted to modify non-description fields")
        api.set_config(entity_id, updated)
        after = api.get_config(entity_id)
        post, _, _ = reconcile_description(entity_id, after, repo, github_base, headings, detailed_headings, index)
        if post != "valid" or any(after.get(k) != latest.get(k) for k in set(after) | set(latest) if k != "description"):
            print(f"HA DOC LINK {entity_id}: post-write validation failed")
            audit(audit_file, entity_id=entity_id, old_url=old_url, new_url=DOCS_RE.search(after.get("description", "")).group("url") if DOCS_RE.search(after.get("description", "")) else None, repair_rule=rule, outcome="failed", reason="post-write validation")
            bad += 1
            continue
        repaired += 1
        audit(audit_file, entity_id=entity_id, old_url=old_url, new_url=DOCS_RE.search(after["description"]).group("url"), repair_rule=rule, outcome="repaired")
        print(f"HA DOC LINK {entity_id}: repaired ({rule})")
    print(f"\n[ha] documentation links checked; {repaired} repaired, {bad} unresolved")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="store_true")
    ap.add_argument("--site", action="store_true")
    ap.add_argument("--ha", action="store_true", help="validate automation/script Docs links through the HA API")
    ap.add_argument("--repair", action="store_true", help="apply only unambiguous HA Docs-link repairs")
    ap.add_argument("--github-base", help="repository blob URL prefix, e.g. https://github.com/o/r/blob/main")
    ap.add_argument("--ha-api", default=os.getenv("HA_API_URL", "http://supervisor/core/api"))
    ap.add_argument("--audit-file", type=pathlib.Path, default=pathlib.Path(os.getenv("HA_DOC_LINK_AUDIT", "/data/doc-link-repairs.jsonl")))
    ap.add_argument("repo", type=pathlib.Path)
    ap.add_argument("site_dir", type=pathlib.Path, nargs="?")
    args = ap.parse_args()

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
        return check_ha(args.repo, CoreApi(args.ha_api, token), args.github_base, args.repair, args.audit_file)
    return check_source(args.repo)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)

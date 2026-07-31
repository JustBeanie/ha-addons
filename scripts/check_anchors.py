"""Verify that every intra-repo heading anchor in the docs still resolves.

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
"""

import argparse
import pathlib
import re
import sys

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="store_true")
    ap.add_argument("--site", action="store_true")
    ap.add_argument("repo", type=pathlib.Path)
    ap.add_argument("site_dir", type=pathlib.Path, nargs="?")
    args = ap.parse_args()

    if args.site:
        if args.site_dir is None:
            ap.error("--site requires site_dir")
        return check_site(args.repo, args.site_dir)
    return check_source(args.repo)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)

# HA Docs

Clones a git repository of Markdown, builds it into a static
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/) site, and serves
it in the Home Assistant sidebar over ingress. It re-checks the repo on an
interval and rebuilds only when the commit changes.

Git stays the source of truth. The add-on never writes to the repository — it
only ever pulls.

## Configuration

| Option | Default | Meaning |
|---|---|---|
| `repository` | *(placeholder)* | Repo to publish. Set this first. |
| `branch` | `main` | Branch to follow. |
| `poll_interval` | `900` | Seconds between checks. 60–86400. |
| `site_name` | `Docs` | Title in the header and browser tab. |
| `git_token` | *(unset)* | Personal access token. Only needed for a private repo; never written to the log. |

### Private repositories

Create a [fine-grained personal access token](https://github.com/settings/tokens?type=beta)
scoped to **only** the docs repository, with **Repository permissions → Contents:
Read-only**. Paste it into `git_token`. Nothing else is needed — the add-on only
ever reads.

The token is used to build the clone URL and is never logged, but note it is
stored in the add-on options like any other add-on secret.

## How it renders your Markdown

The source repo needs **no** `mkdocs.yml`, `_sidebar.md`, front matter, or any
other scaffolding. All site configuration lives inside this add-on, so the repo
stays exactly as GitHub renders it.

- Navigation is generated from the file tree; `README.md` becomes the index.
- Relative `.md` links are rewritten automatically.
- Full-text search is built in.

### GitHub-identical heading anchors

This is the part that matters if your docs cross-link to headings.

GitHub's slugger strips punctuation and emoji but **does not collapse** the gaps
that leaves, so `## ⚠️ Nightlight script ID desync` becomes
`#-nightlight-script-id-desync` (leading dash) and
`### Dusk and away rules — per window` becomes `#dusk-and-away-rules--per-window`
(double dash).

Every common slugifier — MkDocs' default, `pymdownx.slugs`, docsify, Gollum —
collapses those runs, which silently breaks every such link. `ghslug.py`
reimplements GitHub's algorithm so the anchors keep working.

`scripts/check_anchors.py` in this repo verifies it. Run it against a clone
before trusting a large docs set:

```
python scripts/check_anchors.py --source /path/to/docs-repo
```

## Forcing an immediate sync

Restarting the add-on triggers a pull and rebuild straight away:

```yaml
action: hassio.addon_restart
data:
  addon: 3b317604_ha_docs
```

The slug depends on where you installed it from — `local_ha_docs` for a local
copy in `/addons`, or `<repo-id>_ha_docs` when installed from an add-on
repository. The Supervisor shows it in the add-on page URL.

## Notes

- The site is fully self-contained; no CDN or web-font requests leave the box.
- A failed `git fetch` or `mkdocs build` leaves the previously built site in
  place rather than blanking it. Check the add-on log.

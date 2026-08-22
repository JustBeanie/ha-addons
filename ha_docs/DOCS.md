# HA Docs

Clones a git repository of Markdown, builds it into a static
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/) site, and serves
it in the Home Assistant sidebar over ingress. It re-checks the repo on an
interval and rebuilds when the commit changes — or when the add-on itself is
upgraded, since a new version can change how the same Markdown renders.

Git stays the source of truth. The add-on never writes to the repository — it
only ever pulls.

## Configuration

| Option | Default | Meaning |
|---|---|---|
| `repository` | *(placeholder)* | Repo to publish. Set this first. |
| `branch` | `main` | Branch to follow. |
| `git_username` | `x-access-token` | Non-secret HTTPS username used with `git_token`. The default is correct for GitHub. |
| `poll_interval` | `900` | Seconds between checks. 60–86400. |
| `site_name` | `Docs` | Title in the header and browser tab. |
| `git_token` | *(unset)* | Personal access token. Only needed for a private repo. It is never placed in a repository URL, process argument, Git configuration, or log. Add-on configuration containing it is still sensitive. |
| `todo_entity` | *(unset)* | To-do list that notes are mirrored onto, e.g. `todo.docs_review`. Leave empty to keep notes inside the docs site. |

### Private repositories

Create a [fine-grained personal access token](https://github.com/settings/tokens?type=beta)
scoped to **only** the docs repository, with **Repository permissions → Contents:
Read-only**. Paste it into `git_token`. Nothing else is needed — the add-on only
ever reads.

HA Docs gives Git the token through a short-lived, permission-restricted
credential file in `/run`. The file is removed immediately after each fetch.
The token is never embedded in a URL or stored in the repository cache, and the
fetch and build processes do not inherit the Supervisor API token.

The default `git_username` is correct for GitHub. If another HTTPS Git provider
requires the account name alongside a token, set that non-secret name here.

The token is still stored in Supervisor options. Home Assistant intentionally
allows authorized manager/admin callers to retrieve full add-on options,
including password and API-key fields. Masking the field in the configuration UI
does not remove it from those API responses. See the
[Supervisor API documentation](https://developers.home-assistant.io/docs/api/supervisor/endpoints/#addons).

Treat all add-on configuration and status output as sensitive: never paste it
into a chat, issue, or other public report. If such output is exposed, revoke and
rotate the token immediately.

**After upgrading from any release before 1.4.0, rotate the repository token.**
Older releases embedded it in Git's remote URL, so it may remain in an old Home
Assistant backup or storage snapshot even though 1.4.0 removes the live legacy
checkout during migration. Treat pre-1.4.0 backups as sensitive.

If you inspect Home Assistant through HA-MCP, enable its **Redact secrets**
feature (`redact_secrets: true`) and restart HA-MCP before requesting detailed
add-on status. A password option that is set should then appear as
`<redacted: set>`. Redaction protects HA-MCP responses; it does not make the
underlying Supervisor option inaccessible to legitimately privileged callers.

## How it renders your Markdown

The source repo needs **no** `mkdocs.yml`, `_sidebar.md`, front matter, or any
other scaffolding. All site configuration lives inside this add-on, so the repo
stays exactly as GitHub renders it.

- Navigation is generated from the file tree; `README.md` becomes the index.
- Relative `.md` links are rewritten automatically.
- Full-text search is built in.
- ` ```mermaid ` fenced blocks render as diagrams, the same as on GitHub.

### Safe Markdown policy

The repository is treated as untrusted input. HA Docs accepts Markdown, raster
images, PDF, and plain-text files. It rejects symlinks, submodules, special
files, HTML pages, JavaScript, CSS, SVG, XML, WebAssembly, dot-directories, and
files that exceed the build limits: 10,000 files, 100 MiB total source data,
10 MiB per passive asset, 2 MiB per Markdown file, 20 path components, 128
bytes per component, and 512 bytes per path.

Rendered Markdown is sanitized before it is inserted into the trusted Material
theme. Ordinary headings, links, tables, code highlighting, admonitions,
details, raster images, and `<br>` elements are retained. Raw scripts, event
handlers, forms, frames, embedded objects, SVG, arbitrary styles, and unsafe URL
schemes are removed. A repository that needs custom HTML, JavaScript, CSS, or SVG
is intentionally outside this add-on's security model.

Builds are staged and validated before they replace the current site. A bad Git
tree, rejected file, sanitizer failure, or MkDocs failure leaves the previously
built safe site online.

### Diagrams stay offline

Material's built-in Mermaid support fetches the runtime from a CDN on every
page load. This add-on vendors it into the image instead, and emits a different
CSS class (`diagram`, not `mermaid`) so Material's version never activates.
Nothing leaves the box.

Because `mkdocs build` cannot validate diagram syntax, a block that fails to
parse is rendered as a visible error with its source, rather than as an empty
gap.

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

## Highlights and notes

Select any text on a page to get a small toolbar: pick a colour to highlight it,
or **Note** to highlight it and write something. Click an existing highlight to
edit the note, change the colour, or delete it. The bookmark button in the header
opens a review drawer listing everything you have flagged across every doc, with
a link to each passage.

Each entry in the drawer has a delete button, which works whichever doc the
annotation belongs to. It takes two taps — the first arms it, the second deletes —
because there is no undo.

Annotations are stored by the add-on in `/data/annotations/store.json`, not in the
browser. That means the same set appears in the companion app and in a desktop
browser, and survives an add-on upgrade, a reboot, or a cleared cache. It also
means they are included in a Home Assistant backup.

The docs repository is still never written to. Your notes are *about* the docs;
they are not part of them.

### Mirroring notes to a to-do list

Set `todo_entity` to a to-do list — a [Local To-do](https://www.home-assistant.io/integrations/local_todo/)
list called *Docs Review* works well — and every note is added to it as an item:
the note is the summary, the page and the quoted text are the description.

An item is pushed once, when the note is first written, and deleting the note
completes it. Editing a note afterwards does **not** update its item: it may be
one you have already started acting on, and quietly rewriting it would be worse
than leaving it as written.

You can still tick items off in Home Assistant as you deal with them — that has
no effect on the highlight, which stays in the docs until you delete it.

If the list is unreachable the note is still saved. The to-do operation remains
in a durable retry queue and uses an annotation-specific marker to reconcile an
ambiguous add before retrying. Home Assistant's add-item action has no native
idempotency key, so the marker sharply reduces duplicates but cannot guarantee
exactly-once behavior for every third-party to-do provider. The annotation API
reports work as pending or failed if it cannot complete after bounded retries.

### When a doc changes underneath a highlight

Annotations are anchored to the quoted text plus about forty characters either
side, with whitespace normalised. Rewrapping a paragraph, reindenting it, or
editing a nearby sentence therefore leaves the highlight where it was.

When the quoted text is gone altogether, the annotation is **not** reattached to
whatever looks closest. It is listed in the review drawer as orphaned, with the
text you originally highlighted, and is not drawn on the page. A highlight
silently sitting on the wrong sentence would be worse than one that admits it
lost its place.

Once an orphan has told you what you needed to know, delete it from the drawer.
That is the only place it can be reached, since there is no highlight on any page
to click.

Text inside Mermaid diagrams cannot be annotated: that subtree is replaced with
a fresh SVG on every render and on every palette toggle, so no anchor in it
would survive.

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
- The site and annotation API accept traffic only through Home Assistant
  Supervisor ingress. The health endpoint is reserved for the Supervisor
  watchdog.
- HA Docs limits source-tree size, annotation count and size, request size,
  concurrency, and request rates so one document or client cannot consume the
  add-on indefinitely.
- Annotation storage is capped at 2,000 records, 250 records per page, 8 KiB
  per record, and 4 MiB total. Requests are capped at 64 KiB. New or growing
  notes are rejected at capacity, while deletes and non-growing corrections
  remain available.

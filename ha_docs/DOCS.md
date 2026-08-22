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
| `poll_interval` | `900` | Seconds between checks. 60–86400. |
| `site_name` | `Docs` | Title in the header and browser tab. |
| `git_token` | *(unset)* | Personal access token. Only needed for a private repo. HA Docs never writes it to its log, but add-on configuration and status output containing it is sensitive. |
| `todo_entity` | *(unset)* | To-do list that notes are mirrored onto, e.g. `todo.docs_review`. Leave empty to keep notes inside the docs site. |
| `report_doc_link_repairs` | `true` | Raise a Home Assistant Repairs issue for each invalid automation/script Docs link. Requires Spook. Never changes entity descriptions. |
| `repair_scan_on_start` | `true` | Start the report-only Docs-link Repair scan in the background when HA Docs starts. |
| `repair_scan_concurrency` | `4` | Concurrent configuration reads during the scan. Range: 1–8; Repair actions remain serial. |
| `repair_progress_interval` | `25` | Entities between visible scan-progress log records. Range: 1–100. |
| `repair_scan_heartbeat_interval` | `10` | Seconds between visible “waiting for HA config API” records when reads stall. Range: 1–300. |
| `watch_entity_updates` | `true` | Watch automation/script entity changes and run a report-only check for only that entity. Requires Spook and `report_doc_link_repairs`. |
| `entity_update_debounce` | `3` | Seconds to coalesce successive changes for the same entity before its targeted check. Range: 1–30. |
| `log_level` | `info` | Applies to all HA Docs components: `trace`, `debug`, `info`, `warning`, or `error`. |

### Documentation-link repair reporting (Spook required)

Install [Spook](https://spook.boo/) before enabling `report_doc_link_repairs`. HA Docs uses
Spook's `repairs.create` and `repairs.remove` actions to raise or clear persistent issues in the
Home Assistant Repairs dashboard. It only reports the entity, failure, and suggested repair rule;
it never changes an automation or script description. Each issue includes the link it found and the
exact marker or URL change to make when the target is unambiguous.

HA Docs starts ingress before it fetches or scans, so the previously built site remains usable while a refresh is in progress. A first-ever start serves a small “initial sync” page until its first successful build.

Every HA Docs log line includes a local ISO-8601 timestamp and a level. At `info`, the scanner reports dispatch, timed waiting heartbeats, periodic progress, Repairs raised, and its healthy/raised/removal-requested/failure summary. A valid link always invokes Spook's `repairs.remove`, which clears its previously raised Repair; the summary counts removal requests because Spook deliberately treats an already-absent issue as a successful no-op. `debug` adds per-entity decisions; `trace` adds token-safe API request metadata. No level logs Supervisor tokens or full entity descriptions.

After its initial reconciliation, HA Docs also subscribes to non-runtime Home Assistant automation and script entity changes. Script execution state flips and last-run metadata are ignored. It debounces genuine update bursts, then runs the same report-only checker for the one changed entity—never a new full scan. The log records `Entity update detected; checking only entity=...`, followed by that entity's targeted result. A full reconciliation runs only at add-on start or when the documentation source changes, because a documentation change can affect more than one entity.

### Repeatable live Repair test fixture

`script.ha_docs_repair_test` is a disabled, no-op script reserved for validating this report-only integration. Give it a valid `📖 Docs:` link to verify that a prior Repair clears; temporarily use a `Docs:` marker, a nonexistent Markdown path, or a nonexistent anchor to verify that Spook raises a clear, actionable Repair. Restore its canonical link afterwards. HA Docs never changes the fixture description.

### Private repositories

Create a [fine-grained personal access token](https://github.com/settings/tokens?type=beta)
scoped to **only** the docs repository, with **Repository permissions → Contents:
Read-only**. Paste it into `git_token`. Nothing else is needed — the add-on only
ever reads.

HA Docs uses the token to build the clone URL in memory. It logs only **Using
authenticated access**, and never the token or the authenticated clone URL.

The token is still stored in Supervisor options, and Home Assistant deliberately
lets authorized manager/admin callers read full add-on options back — including
password fields. Masking the field in the configuration UI does not remove it
from those API responses. See the
[Supervisor API documentation](https://developers.home-assistant.io/docs/api/supervisor/endpoints/#addons).

So treat add-on configuration and status output as sensitive: do not paste it
into a chat, an issue, or a bug report. If it is exposed, revoke and rotate the
token immediately.

If you inspect Home Assistant through HA-MCP, enable its **Redact secrets**
option (`redact_secrets: true`) and restart HA-MCP before asking for detailed
add-on status; a password option that is set then reads as `<redacted: set>`.
That protects HA-MCP responses only — it does not make the underlying Supervisor
option inaccessible to legitimately privileged callers.

## How it renders your Markdown

The source repo needs **no** `mkdocs.yml`, `_sidebar.md`, front matter, or any
other scaffolding. All site configuration lives inside this add-on, so the repo
stays exactly as GitHub renders it.

- Navigation is generated from the file tree; `README.md` becomes the index.
- Relative `.md` links are rewritten automatically.
- Full-text search is built in, and understands entity IDs (see below).
- ` ```mermaid ` fenced blocks render as diagrams, the same as on GitHub.
- Previous/next links sit at the foot of every page.
- Each page links back to GitHub to edit or view its source, when the docs repo
  is on GitHub.
- The footer shows the commit the site was built from.
- Anything under a `retired/` folder stays built, linkable and searchable, but
  is kept out of the sidebar so it does not read as current.

### Searching for entity IDs

Most search setups treat `sensor.nw_sun_penetration` as one indivisible word, so
searching for `penetration` finds nothing at all — which is close to useless for
a docs set that is largely made of entity IDs. This add-on splits on dots and
underscores as well as whitespace, so any part of an ID finds the whole thing.
Version numbers and decimals like `1.5` are left alone.

### Editing a page from the page

With a GitHub `repository` configured, every page carries an edit and a view
action in its top-right corner, pointing at that document in the repo on the
configured branch. The links are built from `repository`, never from the
tokenised clone URL, so a configured `git_token` cannot appear in a page.

Material normally fetches star and fork counts from `api.github.com` on every
page load once a repository is configured. That request is suppressed — the
element it attaches to is overridden away — so the site stays as self-contained
as it was before.

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

Annotations are stored by the add-on in `/data/annotations.json`, not in the
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

If the list is unreachable the note is still saved — the failure is logged and
nothing is lost.

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

## Checker status in the site header

HA Docs runs two link checkers, and both used to report only into the add-on
log — the one place you are not looking while reading the docs. The **link**
button in the site header now shows what they are doing, and opens a panel with
the detail. It is strictly read-only: it starts nothing and changes nothing in
Home Assistant.

The button changes to match whatever most needs acting on, in this order:

| Indicator | Meaning |
| --- | --- |
| Red, with a count | The documentation source has broken anchors. **The site is not being rebuilt** — you are reading the last good commit. |
| Dimmed | `report_doc_link_repairs` is off, so the Repair checker results below are stale by definition. |
| Amber, with a count | That many automations or scripts have an open Docs-link Repair. |
| Spinning | A Docs-link Repair scan is running; the panel shows how far along. |
| Red, no count | The last scan stopped before it finished, or finished with failures. Check the add-on log. |
| Plain | Everything resolves and no Repairs are open. |

The panel has a section per checker:

- **Documentation source** — how many links were checked and when. When any are
  broken it lists them, because this is the failure that otherwise looks like
  nothing happening at all: the anchor check gates the rebuild, so a broken link
  leaves the site serving the previous commit indefinitely.
- **Docs-link repairs** — whether a scan is idle, running, or was interrupted;
  the last scan's healthy/raised/skipped/failed counts; and a row per open
  Repair. Each row links straight to that automation or script in the editor,
  and there is a link to Settings → System → Repairs. The last targeted
  entity check is shown too, which is the quickest confirmation that editing a
  description had the effect you expected.

On a narrow screen the header has no room for a third button, so the same panel
appears at the top of the highlights drawer instead, and the status dot moves
onto the highlights button.

The panel polls while it is open or while a scan is running, and slowly
otherwise. It stops entirely when the page is not visible, so leaving the docs
open in the companion app costs nothing.

Status lives in `/data/scan/`, alongside the annotation store. Like everything
else the add-on keeps, it is derived state — deleting it costs nothing more than
the next scan.

## Forcing an immediate sync

Use the **Sync** button in the site header. It asks the add-on to pull straight
away rather than waiting out the rest of `poll_interval`, then watches for the
outcome: if a new site was built the page reloads itself, and if the repository
had nothing new it says so. This is the normal way to read something you have
just pushed.

Restarting the add-on also triggers a pull and rebuild, and is still the right
tool if the add-on itself looks wedged:

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
- The Supervisor watchdog probes `/anno/health`, so a failure means nginx or the
  annotation store has actually stopped answering — not merely that the
  container exited.
- The first-ever start serves a placeholder that refreshes itself until the
  first build lands.

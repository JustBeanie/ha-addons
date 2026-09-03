# Changelog

## 1.15.2 - 2026-09-02

- Added independent **Hide navigation** and **Hide contents** controls to the
  desktop site header. Each sidebar can now be collapsed to give the document
  more room, and the selected state is remembered in that browser. Material's
  existing mobile navigation drawers are unchanged.

## 1.15.1 - 2026-08-31

- Fixed private GitHub repository sync by sending the configured PAT as the
  Basic-auth password expected by Git-over-HTTPS. The credential remains
  process-scoped and is never written to the repository remote URL.

## 1.15.0 - 2026-08-30

The app now has a maintained quality gate and safer runtime defaults.

- Added Python regression tests for anchor validation, annotation persistence,
  event filtering, scan-status merging, and Repairs cleanup.
- Added pull-request, push, scheduled, and architecture build CI with the Home
  Assistant app linter, Hadolint, ShellCheck, and a Python 3.12/3.13 test matrix.
- Moved pinned MkDocs dependencies into `requirements.txt`, enabled Dependabot,
  and refreshed the Home Assistant base image to 3.24-2026.08.0.
- Kept git tokens out of persistent remote URLs, hardened path/API error
  handling, quarantined malformed annotation stores, and added basic browser
  security headers.
- Made the app explicitly stable, admin-only, AppArmor-enabled, and cold-backup
  safe.
- Incorporated the upstream watcher correction: a saved automation or script is
  observed through its `off` → `unavailable` → `off` reload round trip, while
  execution state changes remain ignored.
- Updated the manifest for current Home Assistant app lint rules and moved the
  health probe to the Docker-native `HEALTHCHECK` directive.

## 1.14.0 - 2026-08-30

A Repairs issue now follows the entity that owns it.

- **An edited automation is checked again.** The targeted watcher had not run a
  single check since it shipped, and the log said so plainly once anyone looked:
  twelve full scans across one evening and no targeted ones at all. Saving an
  automation makes Home Assistant remove that one entity and add it back, so
  both halves arrive as a state-change event with one side missing — and
  comparing the surviving state against nothing read as an ordinary off/on flip,
  which is exactly the script-execution case the filter exists to discard. A
  description lives in the configuration and never in the entity attributes, so
  that half-present event is the only evidence of an edit there is. An entity
  being added or removed is now treated as what it is: a configuration event.
- **A deleted automation takes its issue with it.** Two paths had to change,
  because a deletion is invisible to a scan by construction: a scan enumerates
  the entities that exist, and this one no longer does. A targeted check that
  finds the entity missing now withdraws its Repair — the configuration-missing
  branch beside it already did — and clears its row from the site panel too.
- **Every poll sweeps the Repairs registry.** The targeted check only covers a
  deletion the add-on was running for. The sweep is the backstop: it reads the
  open issues over the websocket API, since the core REST API this add-on
  otherwise uses has no repairs endpoint, and withdraws every `ha_docs_link_*`
  issue with no entity behind it. It runs first in the refresh pass, ahead of
  the repository fetch and outside the source check that freezes the site, on
  the grounds that stale Repairs about Home Assistant should not wait on a
  broken anchor in the docs. A registry it cannot read is one cleanup postponed
  for a poll, never a failed check, and the one issue belonging to no entity
  — *HA Docs site is frozen* — is outside the swept prefix by construction.
- **A burst of events is one check, not one each.** Honouring additions means
  hearing a Home Assistant restart, which puts every automation and script back
  at once — about two hundred here, and a subprocess each would be a thundering
  herd doing the work of one scan. Events are now debounced into a batch and
  passed to a single targeted check, which the checker already accepted: it has
  taken a repeatable `--entity-id` since the watcher shipped. A restart
  therefore reconciles the whole instance once, which nothing else does unless
  the documentation happens to change.
- **The event filter is tested rather than grepped.** Its only test asserted
  that three words appeared somewhere in the file, all of which did, throughout.
  It is now exercised as a function, including both halves of a reload, and the
  websockets import moved inside the connect call so the predicate can be tested
  without the package.

## 1.13.0 - 2026-08-28

Table columns sort when you click their header.

- **Any table with five or more rows sorts now.** Click a header to sort by it,
  again to reverse, a third time to put it back in the order it was written in
  — which these tables genuinely have, being ordered by hand. Below five rows
  nothing is added: the table is already visible at a glance, and that threshold
  is the difference between the affordance appearing on about two hundred
  tables and on all four hundred and eighty-six.
- **Column types are read from the cells, not from the Markdown.** Sorting a
  column as numbers rather than as text is a decision the usual libraries take
  from a `data-sort-method` attribute on each header — which would mean writing
  site scaffolding into the docs repo, the one thing this add-on exists to
  avoid. Sniffing the column instead keeps the source rendering identically on
  GitHub. Thousands separators and trailing units are understood, so `87,493`
  no longer sorts below `9,102`; ISO dates need nothing, already sorting
  correctly as text.
- **Nothing new is downloaded.** Material's documented integration pulls a
  library from a CDN and wants a further file per data type, one of them a date
  parser whose only possible effect here would be to misread dates that are
  already correct. The sort is written into the add-on instead: no CDN, no new
  pin, no change to the Dockerfile.
- **Existing highlights are unaffected by sorting** — they live inside the row
  and travel with it. The one case that is not exact is a highlight *created*
  while a table is sorted; see DOCS.md. No stored annotation can be rewritten
  or orphaned by any of this.

## 1.12.0 - 2026-08-27

A failed source anchor check now says so, instead of only stopping.

- **A frozen site raises a Repairs issue.** The source anchor check gates the
  rebuild, so one broken link leaves the site serving an older commit for as
  long as it takes someone to notice. Until now the only evidence was a line in
  this add-on's log and a badge in the header of the very site that had stopped
  updating — which is precisely the wrong place for it. It is reported outward
  now: one issue, *HA Docs site is frozen*, listing every broken link, removed
  automatically by the next check that passes.
- **New `notify_service` option** sends a push on the same condition. It fires
  on the transition into failure rather than on every poll — the check runs
  every `poll_interval`, so the level-triggered version would be about a hundred
  identical notifications a day and would be muted within a week. It re-arms
  after a check passes. Unset means the Repairs issue is still raised.
- **Reporting can never change what gets published.** Both paths are
  best-effort and swallow connection errors as well as HTTP ones: an
  unreachable Home Assistant must not be able to publish unvalidated docs, nor
  to hold back a good build. The rebuild still turns purely on the link count.
- `--source` accepts `--report` and `--notify-service` to match. Without a
  `SUPERVISOR_TOKEN` both are ignored with a warning, so running the checker by
  hand on a workstation — or in CI — behaves exactly as it did before.

## 1.11.1 - 2026-08-22

Fixes the reconcile pass shipped in 1.11.0, which never cleared anything.

- **`get_items` now asks for open items explicitly.** 1.11.0 relied on the
  service schema's `needs_action` default. Home Assistant applies field defaults
  when it renders the UI form, not when a service is called over the API, so the
  call came back with completed items included too. Every stored summary matched
  something still on the list, so every pass cleared nothing.
- **Every pass now logs what it saw**, not only the passes that remove
  something. That is what made the above so hard to see: a pass finding nothing
  to do was indistinguishable in the log from a worker that had never started,
  and both look like the feature simply not working. The worker also announces
  itself at startup.

## 1.11.0 - 2026-08-22

Working through the to-do list now cleans up the docs behind you.

- **Ticking an item off clears its highlight.** Until now the mirroring ran one
  way only: writing a note created an item, deleting the note completed it, and
  completing the item did nothing at all. That was deliberate, and it was wrong
  — clearing nine notes off a list left nine highlights sitting on a page that
  had already been dealt with, with no way to shift them but deleting each by
  hand. An item that is no longer open, whether ticked off or deleted outright,
  now takes its annotation with it.
- **The Sync button reconciles as well as pulls.** The pass runs once per
  completed refresh, so it inherits `poll_interval` instead of adding a second
  timer to keep in step with it — and because Sync forces a refresh, it doubles
  as "clear now" for anyone who does not want to wait out fifteen minutes.
- **A list that cannot be read prunes nothing.** "Could not read the list" and
  "the list has nothing open" are answered separately and never collapsed into
  one value. Conflating them would let a brief outage delete every note-bearing
  highlight in the store at once, which is the one way this feature could
  destroy work rather than tidy it.
- Bare highlights are untouched, as are notes whose push never landed. Neither
  has an item behind it, so neither is a task the list can have finished.
- Two behaviours that read as bugs and are not, both now documented: renaming an
  item in Home Assistant clears its highlight, because items are matched by the
  summary they were created with; and notes with identical text share one item,
  so they clear together or not at all.

## 1.10.0 - 2026-08-22

The link checkers stop reporting only into the log.

- **Both checkers now have a live indicator in the site header**, with a panel
  showing what they are doing. Until now the documentation-source anchor check
  and the Docs-link Repair scan reported only into the add-on log, an
  append-only audit file, and the Repairs dashboard — none of which you are
  looking at while reading the docs.
- **A broken source anchor is finally visible where it matters.** That check
  gates the rebuild, so a broken link leaves the site serving the previous
  commit for as long as it takes someone to open the log and notice. The panel
  now says so in as many words, and lists the offending links.
- The Repair section reports scan state and live progress, the last scan's
  healthy/raised/skipped/failed counts, and a row per open Repair linking
  straight into that automation or script's editor. The last targeted entity
  check is shown as well, so editing a description gives immediate feedback.
- A repaired entity now leaves the list without waiting for the next full scan.
  The audit file deliberately never records a healthy verdict, so the targeted
  checker records one separately — that is what lets a row disappear.
- An interrupted scan reports as interrupted rather than as one that is still
  running. The reader ages out a status record whose scan has stopped bumping
  its heartbeat, which covers a crash, a shutdown mid-scan, and a container
  restart alike.
- On a narrow screen the panel moves into the highlights drawer rather than
  adding a third header button, which does not fit beside the hamburger, title
  and search.
- New `UPSTREAM.md` records where MkDocs 2.0 leaves this add-on, why the pinned
  build is not affected, and why Zensical is not yet an exit. Documentation
  only; no behaviour change.
- Status is written to `/data/scan/` only when the add-on asks for it, so
  running `check_anchors.py` by hand on a workstation still writes nothing.

## 1.9.0 - 2026-08-20

An icon, and the reading side of the site catching up with the backend.

- **The add-on finally has an icon.** It had none at all, so it showed as a
  blank tile in the add-on store and on its own page. `panel_icon` only ever
  covered the sidebar entry. Both `icon.png` and `logo.png` are generated by
  `scripts/gen_icon.py`, which takes no dependencies, so the mark can be
  regenerated rather than being an opaque binary.
- **Search understands entity IDs.** The default separator treats
  `sensor.nw_sun_penetration` as a single token, so searching for `penetration`
  returned nothing. Dots and underscores now split, while `1.5` and `v2.0.0`
  stay intact.
- **A Sync button in the header** pulls the docs repo immediately instead of
  waiting out `poll_interval`. It watches for the result and reloads the page
  when a new site has been built, says so when there was nothing new, and no
  longer requires restarting the add-on to see a doc you just pushed.
- **Every page links back to GitHub** to edit or view its source. Material would
  normally fetch star and fork counts from `api.github.com` once `repo_url` is
  set; the element that triggers that is overridden away, so the promise that
  nothing leaves the box still holds.
- **The footer says which commit the site was built from**, which is the
  quickest way to tell a stale site from a current one.
- Previous/next links at the foot of each page, section index pages, and
  scroll-tracked anchors.
- Retired documents leave the sidebar but stay built, linkable and searchable.
- The app healthcheck now has an application-level probe (`/anno/health`)
  rather than only noticing if the container itself stops.
- The first-run "sync in progress" page refreshes itself instead of stranding
  the reader on a dead page.
- Code fences can opt into line numbers with linkable anchors per line.
- Documents that Supervisor returns `git_token` in full to authorized admin
  callers, so add-on configuration and status output should be treated as
  sensitive and the token rotated if it is ever exposed. Carried over from the
  1.3.1 draft, which was never merged.

## 1.8.2 - 2026-08-16

Targeted, report-only Docs-link validation with quieter runtime behavior.

- HA Docs now validates one affected automation or script after a non-runtime
  entity update, rather than repeating a whole-instance scan for that change.
  Full reconciliation remains at add-on start and after a documentation-source
  change.
- Script execution activity (`off`/`on` transitions and last-run metadata) is
  ignored, so running an automation or script does not trigger a Docs-link
  check.
- A stale registry entity whose configuration endpoint returns 404 is recorded
  as `skipped-missing-config`, any prior HA Docs Repair is cleared, and the
  refresh worker continues instead of reporting a failed scan.
- Added `watch_entity_updates` and `entity_update_debounce` options, both
  enabled by default, plus targeted-check lifecycle logs.

## 1.8.1 - 2026-08-16

- Script execution activity is ignored by the Docs-link watcher, so running an
  automation or script no longer triggers a check.

## 1.8.0 - 2026-08-16

- Targeted Docs-link checks: after a non-runtime entity update, only the
  affected automation or script is validated rather than the whole instance.
- Added `watch_entity_updates` and `entity_update_debounce`.

## 1.7.1 - 2026-08-16

- Stalled scans are reported promptly instead of going quiet, via the new
  `repair_scan_heartbeat_interval` option.

## 1.7.0 - 2026-08-16

- Scan visibility: added `repair_scan_on_start`, `repair_scan_concurrency` and
  `repair_progress_interval`, so the reconciliation can be backgrounded, bounded
  and watched.

## 1.6.2 - 2026-08-16

- Added the `log_level` option, applying to every HA Docs component including
  the Python link scanner.

## 1.6.1 - 2026-08-16

- Clearer, more actionable repair instructions on each raised issue.

## 1.6.0 - 2026-08-16

- Docs-link handling became **report-only**: issues are raised through Spook's
  Repairs and entity descriptions are never rewritten.
- The `repair_doc_links` option from 1.5.0 is replaced by
  `report_doc_link_repairs`. Anything that set the old name needs updating.

## 1.5.3 - 2026-08-16

- Link reconciliation continues after an HA config API failure rather than
  abandoning the run.

## 1.5.2 - 2026-08-16

- Automation configuration identifiers are resolved correctly, so entities are
  no longer missed during a scan.

## 1.5.1 - 2026-08-16

- Build fix for 1.5.0.

## 1.5.0 - 2026-08-16

- First version of the HA documentation-link reconciler, behind a new
  `repair_doc_links` option.

There was no 1.4.x.

## 1.3.0 - 2026-08-07

Clearing notes, which 1.2.0 could only do one highlight at a time.

- Every entry in the review drawer now has a delete button. This is the only way
  to clear an **orphaned** annotation — it is not drawn on the page, so there was
  no highlight to click — and it saves navigating to another doc to remove
  something you can already see listed.
- Deleting takes two taps: the first arms the button, the second removes the
  annotation. There is no undo, and the drawer is scrolled with a thumb.
- Deleting a note now also completes its item on the `todo_entity` list. In 1.2.0
  the item was left behind, so the list only ever grew. Editing a note still does
  not update its item.

## 1.2.0 - 2026-08-06

Highlights and notes, for marking things while reading and coming back to them.

- Select any text to highlight it in one of four colours, and optionally attach
  a note.
- Annotations are stored by the add-on in `/data`, not in the browser, so the
  same set appears in the companion app and on the desktop and survives an
  add-on upgrade or a cleared cache. The docs repository is still never written
  to.
- A button in the header opens a review drawer listing everything flagged,
  across every doc, with a link to each passage.
- New `todo_entity` option: when set, every note is also added once to that
  to-do list, so flagged items show up in the Home Assistant UI.
- Annotations are anchored by quoted text and surrounding context, so editing a
  doc and rewrapping its paragraphs does not move them. When the quoted text is
  gone entirely, the annotation is reported as orphaned in the drawer rather
  than reattached to whatever is nearest.

## 1.1.1 - 2026-08-02

Fixes an upgrade that appears to do nothing.

- The built site is now cached against the commit **and** the builder that
  produced it. Keying on the commit alone meant that upgrading the add-on left
  the previously built site in place — `/data` survives an image rebuild — so a
  new `mkdocs.yml` was not used until the docs repo happened to get a commit.
  That is why 1.1.0 shipped Mermaid support that did not appear.
- The first run after this upgrade always rebuilds.

## 1.1.0 - 2026-08-02

- Renders ` ```mermaid ` fenced blocks as diagrams.
- The Mermaid runtime is vendored into the image at build time, so no request
  leaves the box at page load. Material's own diagram support fetches it from a
  CDN, so it is deliberately bypassed rather than configured.
- Diagrams follow the light/dark palette toggle, and a diagram that fails to
  parse says so on the page instead of rendering as an empty block.
- Wide diagrams render at full size and scroll inside their own block, rather
  than shrinking to fit the narrow ingress sidebar.

## 1.0.0 - 2026-07-31

Initial release.

- Clones a configurable git repo/branch and rebuilds when the commit SHA changes.
- MkDocs Material with search, dark mode, and auto-generated navigation.
- GitHub-identical heading slugs via `ghslug.py`, so existing anchor links keep
  resolving.
- Served over ingress; no ports exposed, no external font or CDN requests.
- A failed fetch or build keeps the previously built site online.

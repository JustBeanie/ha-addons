# Changelog

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

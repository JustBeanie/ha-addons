# Changelog

## 1.4.0 - 2026-08-11

Security hardening for repositories, rendered content, ingress, and notes.

- Replaces the working clone with a validated HTTPS-only bare fetch and a
  symlink-safe extractor. Symlinks, submodules, special files, traversal paths,
  active static assets, and oversized trees are rejected before MkDocs runs.
- Keeps private-repository tokens out of URLs, arguments, logs, Git metadata,
  and build environments by using a short-lived restricted credential helper.
- Sanitizes rendered Markdown, locks down Mermaid, and adds a restrictive
  per-page Content Security Policy plus browser security headers.
- Restricts the service to Supervisor ingress and adds a watchdog health route,
  request/body limits, timeouts, rate limits, and bounded backend workers.
- Makes annotation writes atomic and durable, enforces storage quotas and path
  validation, and replaces per-request to-do threads with a durable bounded
  retry queue.
- Separates fetch, build, annotation, and web-server privileges. Only the
  annotation service receives the Home Assistant API token.
- Migrates the annotation store and removes legacy clones, generated sites, and
  build stamps. Repository tokens used by older releases must be rotated because
  old backups or snapshots may retain the credential-bearing Git metadata.

## 1.3.1 - 2026-08-07

Security documentation correction for private-repository credentials.

- Clarifies that HA Docs never logs `git_token` or the authenticated clone URL;
  its log only reports that authenticated access is in use.
- Warns that Supervisor stores the token in add-on options and can return it to
  authorized manager/admin clients, so configuration and status output must not
  be pasted into chats or issues.
- Documents least-privilege token scope, immediate rotation after exposure, and
  HA-MCP's `redact_secrets` protection for status responses.

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

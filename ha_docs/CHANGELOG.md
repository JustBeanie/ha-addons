# Changelog

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

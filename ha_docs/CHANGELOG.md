# Changelog

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

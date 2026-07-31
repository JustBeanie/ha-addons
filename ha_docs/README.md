# HA Docs

Serves a git repository of Markdown as a searchable MkDocs Material site in the
Home Assistant sidebar, behind normal HA authentication.

Point it at a repo, and it pulls on an interval and rebuilds when the commit
changes. The repo needs no `mkdocs.yml` or other site scaffolding — all
configuration lives in the add-on, so the source stays exactly as GitHub
renders it, including GitHub-identical heading anchors.

See [DOCS.md](DOCS.md) for configuration.

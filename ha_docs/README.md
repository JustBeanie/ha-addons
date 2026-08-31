# HA Docs

Serves a git repository of Markdown as a searchable MkDocs Material site in the
Home Assistant sidebar, behind normal HA authentication.

Point it at a repo, and it pulls on an interval and rebuilds when the commit
changes. The repo needs no `mkdocs.yml` or other site scaffolding — all
configuration lives in the add-on, so the source stays exactly as GitHub
renders it, including GitHub-identical heading anchors.

See [DOCS.md](DOCS.md) for configuration.

## Development

The repository's HA Docs workflow runs the same checks used for changes:

```sh
python -m compileall -q ha_docs
cd ha_docs
python -m unittest discover -s tests -v
```

The workflow also validates the app manifest, Dockerfile, shell script, and
both supported container architectures. A clean build runs weekly so pinned
Home Assistant base images and Python dependencies do not silently rot.

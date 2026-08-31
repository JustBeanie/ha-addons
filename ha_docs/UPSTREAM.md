# HA Docs — where the upstream stack stands

HA Docs is built on MkDocs and Material for MkDocs. In February 2026 the
Material team [published their position on MkDocs 2.0][post], and every build
since has printed a warning about it into the add-on log. This is the standing
answer to that warning, so it does not have to be re-derived each time someone
reads the log.

**Short version: nothing is wrong, nothing needs doing, and the reasons are
below. Do not "upgrade" this add-on off its pins without reading this first.**

[post]: https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/

## What MkDocs 2.0 changes

From the post above:

- **Plugin support is removed** outright. The stated focus is theming instead.
- **Theming is rewritten.** Navigation reaches themes as pre-rendered HTML
  rather than structured data, which makes patterns like tabs and collapsible
  sections impossible for a theme to implement.
- **Config moves from YAML to TOML**, with no migration path for existing
  projects.
- **Contributions are closed** — the project asks the community not to open
  issues or pull requests.
- **No license is specified**, which is its own problem for anything shipped.

Material will not support MkDocs 2.0. From 9.7.5 it constrains `mkdocs<2`
instead. Their answer is a new generator, [Zensical](https://zensical.org),
presented as a drop-in replacement for MkDocs 1.x.

## Why this add-on is not affected today

The Python toolchain is pinned explicitly.

`requirements.txt` pins MkDocs 1.6.1, Material 9.7.7, and pymdown-extensions
11.0.1. Independently of that, mkdocs-material 9.7.7 declares
`mkdocs<2,>=1.6` in its own metadata, so pip refuses MkDocs 2.0 even if the
explicit pin were dropped.

Dependabot proposes updates to the Python dependencies and GitHub Actions, while
the weekly HA Docs workflow exercises a clean build. A MkDocs 2.0 release still
changes nothing about a pinned 1.6.1 build.

## What this add-on would lose if it ever did move

Nearly every distinguishing feature runs through a surface 2.0 deletes. This is
worth being blunt about, because "it is only a static site generator" badly
understates the coupling:

| Feature | Depends on | Status under 2.0 |
| --- | --- | --- |
| GitHub-identical heading anchors (~85 links) | `slugify: !!python/name:ghslug.slugify` | YAML python-name tag; TOML has no equivalent |
| Offline Mermaid diagrams | `!!python/name:pymdownx.superfences.fence_div_format` | same |
| Entity-ID search | `plugins: search:` with a custom `separator` | plugin system removed |
| No outbound `api.github.com` request | the deliberately empty `overrides/partials/source.html` | theming rewritten |
| Highlights, notes, checker panel | `custom_dir`, `extra_javascript`, `extra_css` | theming rewritten |
| `run.sh` wiring (site name, repo URL, build stamp) | `!ENV` tags | YAML tag; TOML has no equivalent |

The slugifier is the load-bearing one. `ghslug.py` exists because GitHub strips
emoji and punctuation from headings *without collapsing the gaps*, and every
other slugger collapses them — so losing the ability to inject a slugify
function silently breaks about eighty-five anchors at once.

## The risks that are actually real

Ranked by how likely they are to arrive **without anyone choosing them**:

1. **PyPI availability at install time.** There is no `image:` key in
   `config.yaml` — deliberately, so the Supervisor builds this image locally
   on every install. A fresh install on a new box needs mkdocs 1.6.1, mkdocs-material
   9.7.7 and pymdown-extensions 11.0.1 all still served by PyPI. This is the
   one that turns a working add-on into an uninstallable one.
2. **The Alpine base ageing out.** `build.yaml` pins the architecture-specific
   images to Home Assistant's `3.24-2026.08.0` base release. Python and Alpine
   cannot drift under that pin without someone editing the file, but the pin
   still needs to be refreshed as Home Assistant publishes newer base images.
3. **Unpatched upstream fixes.** Lowest of the three. This serves a LAN-only
   box behind authenticated ingress, building Markdown from a repository the
   operator controls. No untrusted input reaches mkdocs.

None of these is the risk the log warning describes. MkDocs 2.0 itself cannot
reach this add-on while the pins hold; what can reach it is the ordinary decay
of a build that has to be reconstructed from PyPI and a base image every time
it is installed.

## Is Zensical an exit?

Not yet. Three questions decide it for this add-on, and only one is a clear yes.

- **Can it take a custom slugify function?** *Probably, unconfirmed.* Zensical
  documents the `toc` extension's `slugify` option and SuperFences custom
  fences with `format` handlers — the two `!!python/name:` uses here. What its
  documentation does not settle is whether it resolves an arbitrary local
  module (`ghslug`, sitting on `PYTHONPATH` at `/opt/ha_docs`) rather than a
  known set, and whether the YAML tag survives or needs a TOML spelling. Only
  a real build answers this.
- **Can it override a theme partial?** *Yes.* Template overrides are supported
  with minor MiniJinja adjustments, and the one override here is an empty file,
  so it ports with no work at all. `extra_javascript` and `extra_css` are
  explicitly compatible.
- **Can it set a search separator?** *No home for it yet.* Plugins are phased:
  a module system is Phase 2, parity with popular plugins is Phase 3. Search is
  built into the theme rather than being a plugin, so the separator may survive
  as a config key, but that is not documented, and the entity-ID search added
  in 1.9.0 depends on it.

Zensical also requires Python ≥3.10, which the current Home Assistant base
satisfies, so the base image is not the obstacle.

## The position

**Pin and stay. Do not chase Zensical yet.** Material 9.7.7 works, the pin is
double, and the one feature Zensical cannot house today is search — which 1.9.0
specifically tuned to make an entity-ID-heavy docs set searchable. The payoff
for moving right now is zero.

Two cheap hardening steps belong with that:

- Keep `build_from` on an explicit Home Assistant base release rather than a
  mutable `latest` tag, so a rebuild is reproducible rather than merely likely.
- Run a from-scratch rebuild weekly. The scheduled HA Docs workflow is the
  canary for both risk 1 and risk 2, and is the only way either of them
  announces itself before an install fails.

Revisit when Zensical reaches its module/plugin phase, or when the Alpine base
forces a move — whichever lands first. If both slugify and search turn out to
be unreachable, the fallback is not another generator: it is rendering with
python-markdown directly, which this add-on is already halfway to, given it
hand-writes its own frontend, vendors Mermaid, and ships its own slugifier.

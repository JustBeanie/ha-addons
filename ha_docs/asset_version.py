"""MkDocs hook: give the add-on's own site assets a content-versioned URL.

Material's assets are already content-hashed in their filenames
(`main.ec1eaa64.min.css`); the add-on's (`assets/annotate.css`, ...) are not,
so nginx could not let a browser cache them for long without risking an old
script running against a new page. 1.17.0 sent `no-cache` on everything
instead, and every page change then revalidated every stylesheet through
ingress before it could paint - a blank frame between pages, most visible on
the dark palette.

This appends `?v=<digest>` to every `assets/...` entry of extra_css and
extra_javascript. The digest covers every file under the overrides assets
directory, the vendored Mermaid runtime included, so a change to any of them
moves every URL. nginx.conf marks `?v=` URLs, and Material's hashed ones,
immutable; pages themselves stay `no-cache`, so a rebuild is still seen at
once. mermaid-init.js carries its own `?v=` over to the runtime it loads.
"""

import hashlib
import logging
import pathlib

LOG = logging.getLogger("mkdocs.hooks.asset_version")


def digest(assets: pathlib.Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in assets.rglob("*") if p.is_file()):
        h.update(path.relative_to(assets).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]


def versioned(path: str, version: str) -> str:
    if not path.startswith("assets/") or "?" in path:
        return path
    return f"{path}?v={version}"


def on_config(config, **kwargs):
    custom_dir = config.theme.custom_dir
    if not custom_dir:
        return config
    assets = pathlib.Path(custom_dir) / "assets"
    if not assets.is_dir():
        return config
    version = digest(assets)
    config.extra_css = [versioned(path, version) for path in config.extra_css]
    scripts = []
    for script in config.extra_javascript:
        # A plain entry stays a str; one written as a mapping (type/defer/
        # async) is an ExtraScriptValue.
        if isinstance(script, str):
            script = versioned(script, version)
        else:
            script.path = versioned(script.path, version)
        scripts.append(script)
    config.extra_javascript = scripts
    LOG.debug("site assets versioned: v=%s", version)
    return config

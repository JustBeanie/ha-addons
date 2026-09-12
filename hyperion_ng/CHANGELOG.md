# Changelog

## 3.0.8

- Use hot backups so Home Assistant backups no longer stop and restart
  Hyperion (and drop LED grabber connections).

## 3.0.7

- Restore host networking so Home Assistant can reach Hyperion's native JSON
  API on port 19444 after the app's web token flow completes.

## 3.0.6

- Fix the token-request approval dialog so Home Assistant's requested token
  displays and approves the actual application ID instead of `undefined`.

## 3.0.5

- Start Hyperion with an explicit `/config` user-data directory so its
  database is written to the persistent app storage across restarts.

## 3.0.4

- Restore the `app_config` storage mapping so Hyperion configuration survives
  app restarts and is included in Home Assistant backups.

## 3.0.3

- Avoid a double slash in Home Assistant ingress URLs so the web UI assets
  load correctly inside the app iframe.

## 3.0.2

- Include Debian's shared MIME database so the Hyperion web UI and JavaScript
  assets have valid content types through Home Assistant ingress.

## 3.0.1

- Use Home Assistant ingress for the app's Open Web UI action instead of
  directing the browser to Hyperion's direct host port. This avoids
  Hyperion's non-local-network protection page when opened from Home
  Assistant.

## 3.0.0

- Publish a multi-architecture image so Home Assistant downloads the image
  instead of compiling it locally during installation.
- Keep ingress HTTP request bodies compatible with Hyperion's native parser;
  WebSocket ingress remains supported without streamed request bodies.
- Keep the existing Hyperion configuration under `/root/.hyperion`.
- Replace host networking with explicit service ports and mark the release as
  a breaking update so custom protocol/discovery ports can be reviewed.

## 2.2.8

- Restore the existing `addon_config` mapping so the app reuses the prior
  Hyperion database and configuration.
- Make the official Hyperion web client use ingress-relative API, content, and
  WebSocket URLs when served through Home Assistant.

## 2.2.7

- Install the complete set of Debian Bookworm runtime providers required by
  Hyperion's bundled Qt and Python extension libraries.
- Add an architecture-matched CI startup smoke test so a build must launch
  Hyperion and serve its HTTP UI.

## 2.2.6

- Install the explicit `libglib2.0-0` runtime dependency required by
  Hyperion's bundled Qt libraries.

## 2.2.5

- Install the explicit `libfontconfig1` runtime dependency required by
  `hyperiond`.

## 2.2.4

- Install the explicit `libexpat1` runtime dependency required by `hyperiond`.

## 2.2.3

- Correct the SHA-256 checksums for the official Debian packages.
- Use the Supervisor-native base image declaration instead of deprecated
  `build.yaml` build parameters.
- Use the current list-only `devices` manifest format.
- Remove the redundant `webui` field because ingress is enabled.

## 2.2.2

- Build and own the app image from the Home Assistant Debian base instead of
  inheriting `sirfragalot/hyperion.ng`.
- Upgrade the packaged Hyperion runtime from 2.2.0 to the official 2.2.1
  release, with architecture-specific SHA-256 verification.
- Align the manifest with current Home Assistant app lint rules and supported
  Home Assistant architectures.

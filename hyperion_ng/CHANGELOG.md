# Changelog

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

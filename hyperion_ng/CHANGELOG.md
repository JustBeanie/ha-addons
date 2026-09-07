# Changelog

## 2.2.2

- Build and own the app image from the Home Assistant Debian base instead of
  inheriting `sirfragalot/hyperion.ng`.
- Upgrade the packaged Hyperion runtime from 2.2.0 to the official 2.2.1
  release, with architecture-specific SHA-256 verification.
- Align the manifest with current Home Assistant app lint rules and supported
  Home Assistant architectures.

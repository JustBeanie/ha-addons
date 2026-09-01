# Changelog

## 2.0.1

- Install a prebuilt image instead of building on the Home Assistant host. The
  application source, tests, and container build now live in
  [JustBeanie/bacnet-mqtt-gateway](https://github.com/JustBeanie/bacnet-mqtt-gateway),
  which publishes `ghcr.io/justbeanie/bacnet-mqtt-gateway-{arch}` per release
  tag; this repository keeps the app manifest, options schema, translations,
  AppArmor profile, and documentation.
- No functional change to the gateway itself.

## 2.0.0

- Add native Home Assistant OS/Supervisor app packaging for `amd64` and
  `aarch64`.
- Add administrator-only Home Assistant ingress on port `18082`.
- Add Supervisor MQTT service discovery and external MQTT/TLS configuration.
- Add writable `app_config` storage and persistent app data using the current
  Supervisor 2026.07 naming.
- Add protected operation with a custom AppArmor profile and no privileged
  capabilities.
- Rebase the application source on maintained upstream commit
  `6e4aed4cd326e6feb938e316a37109f6e108b34e` while preserving the requested
  JustBeanie fork's authenticated MQTT and shutdown behavior.
- Upgrade the runtime to current Node.js-compatible dependencies, regenerate a
  deterministic lockfile, and clear the production and development dependency
  audit.
- Publish retained Home Assistant MQTT Discovery configuration, unique
  per-device entities, availability, BACnet units, and QoS 1 state.
- Make the operations console ingress-prefix-aware, remove CDN dependencies,
  trust the authenticated Home Assistant ingress identity, and restrict the
  listener to the Supervisor ingress proxy.
- Add in-console selection and persistence of BACnet objects for polling.
- Add SIGTERM/SIGINT cleanup for HTTP, MQTT, BACnet schedules, and SQLite.
- Prevent overlapping polls for the same device, await initial configuration
  loading, bound discovery reads, and fall back when devices reject BACnet
  unit-property reads.
- Coalesce offline MQTT publications with a bounded queue, expire stale Home
  Assistant entities, correct BACnet entity type mapping, and throttle broker
  outage retries and logs.
- Add Home Assistant app linting, Node 22/24 tests, and `amd64`/`aarch64`
  container builds in CI.
- Move local builds to the explicit multi-platform Home Assistant base image
  `ghcr.io/home-assistant/base:3.22`; no legacy `build.yaml` is used.

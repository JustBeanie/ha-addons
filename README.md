<div align="center">

# Beanie's Home Assistant Apps

**Self-hosted apps (add-ons) for Home Assistant OS and Supervised installs.**

[![Add this repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJustBeanie%2Fha-addons)

[![Commit activity](https://img.shields.io/github/commit-activity/m/JustBeanie/ha-addons?label=activity)](https://github.com/JustBeanie/ha-addons/commits/main/)
[![Open issues](https://img.shields.io/github/issues/JustBeanie/ha-addons)](https://github.com/JustBeanie/ha-addons/issues)
![Architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-success)

</div>

## Apps at a glance

| App | What it does | Version | Build |
|---|---|---|---|
| [**BACnet MQTT Gateway**](#bacnet-mqtt-gateway) | Bring BACnet/IP building-automation devices into Home Assistant over MQTT | [![version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Fbacnet_mqtt_gateway%2Fconfig.yaml&query=%24.version&label=)](bacnet_mqtt_gateway/CHANGELOG.md) | [![CI](https://github.com/JustBeanie/ha-addons/actions/workflows/bacnet-mqtt-gateway.yml/badge.svg)](https://github.com/JustBeanie/ha-addons/actions/workflows/bacnet-mqtt-gateway.yml) |
| [**HA Docs**](#ha-docs) | Turn a Git repo of Markdown into a searchable docs site in the sidebar | [![version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Fha_docs%2Fconfig.yaml&query=%24.version&label=)](ha_docs/CHANGELOG.md) | [![CI](https://github.com/JustBeanie/ha-addons/actions/workflows/ha-docs.yml/badge.svg)](https://github.com/JustBeanie/ha-addons/actions/workflows/ha-docs.yml) |
| [**Hyperion.NG**](#hyperionng) | Ambient (bias) lighting server with its web UI in the sidebar | [![version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Fhyperion_ng%2Fconfig.yaml&query=%24.version&label=)](hyperion_ng/CHANGELOG.md) | [![CI](https://github.com/JustBeanie/ha-addons/actions/workflows/hyperion-ng.yml/badge.svg)](https://github.com/JustBeanie/ha-addons/actions/workflows/hyperion-ng.yml) |
| [**ToneWatch**](#tonewatch) 🧪 | Detect two-tone radio pages, record them, and notify over MQTT | [![version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Ftonewatch%2Fconfig.yaml&query=%24.version&label=)](tonewatch/CHANGELOG.md) | [![CI](https://github.com/JustBeanie/ha-addons/actions/workflows/tonewatch.yml/badge.svg)](https://github.com/JustBeanie/ha-addons/actions/workflows/tonewatch.yml) |

🧪 = experimental. Every app ships a prebuilt, signed image for **amd64** and **aarch64** (e.g. Raspberry Pi 4/5), so nothing is compiled on your Home Assistant host. Versions above are read live from each app's `config.yaml`.

## Install

1. Click **Add this repository to my Home Assistant** above.
   <details><summary>Or add it by hand</summary>

   Go to **Settings → Apps → App store**, open the **⋮** menu → **Repositories**, and paste:

   ```text
   https://github.com/JustBeanie/ha-addons
   ```

   </details>
2. Refresh the store (⋮ → **Check for updates**) if the apps don't show up straight away.
3. Open the app you want, click **Install**, then read its **Documentation** tab before starting it.

> Requires Home Assistant OS or a Supervised install. Container and Core installs can't run apps.

---

## BACnet MQTT Gateway

Discover and poll BACnet/IP devices, publish their data to MQTT with Home Assistant discovery, and manage devices from an admin-only web console in the sidebar.

- BACnet/IP network and object discovery, with configurable polling
- Entities appear automatically through MQTT Discovery
- Controlled BACnet property writes
- Uses Home Assistant's own MQTT broker automatically, or any external broker (TLS supported)

**Good to know:** needs host networking for BACnet broadcasts. Source code lives in [JustBeanie/bacnet-mqtt-gateway](https://github.com/JustBeanie/bacnet-mqtt-gateway).

[Documentation](bacnet_mqtt_gateway/DOCS.md) · [Changelog](bacnet_mqtt_gateway/CHANGELOG.md)

## HA Docs

Point it at a Git repository of Markdown files and get a searchable [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) site in the Home Assistant sidebar, behind normal Home Assistant login.

- Pulls on an interval and rebuilds only when the repo changes
- No `mkdocs.yml` needed — your repo stays exactly as GitHub renders it, heading links included
- Can flag automations and scripts whose documentation links are broken
- Works with private repos via a read-only token

[Documentation](ha_docs/DOCS.md) · [Changelog](ha_docs/CHANGELOG.md)

## Hyperion.NG

Runs the official [Hyperion.NG](https://github.com/hyperion-project/hyperion.ng) release for TV and monitor ambient lighting, with its web UI in the sidebar.

- Configuration is stored in the app and included in Home Assistant backups
- Native Hyperion ports (JSON, Proto, FlatBuffers) stay available to other clients
- Serial, SPI, and video-capture device access

[Documentation](hyperion_ng/DOCS.md) · [Changelog](hyperion_ng/CHANGELOG.md)

## ToneWatch

Listens to an audio or SDR source for configured two-tone pages, records the call, and sends notifications through MQTT.

- Web interface in the sidebar
- Optional Home Assistant MQTT discovery
- Recordings appear in the Home Assistant **Media** browser
- Safe hot backups (the database is checkpointed first)

> ⚠️ ToneWatch is a **supplemental** notification tool, not a certified primary alerting system. Don't rely on it as your only way to receive pages.

Source code lives in [JustBeanie/tonewatch](https://github.com/JustBeanie/tonewatch).

[Documentation](tonewatch/DOCS.md) · [Changelog](tonewatch/CHANGELOG.md)

---

## Troubleshooting

- **The app isn't in the store** — refresh the store (⋮ → **Check for updates**) and reload the page. **Settings → System → Logs → Supervisor** shows any error loading this repository.
- **Install fails while pulling the image** — make sure the host can reach `ghcr.io`, and that it's an amd64 or aarch64 machine (32-bit ARM isn't supported).
- **Anything else** — open the app's **Log** tab; most problems are explained there.

## Getting help

[Open an issue](https://github.com/JustBeanie/ha-addons/issues/new/choose) and include:

- the app name and version, and your architecture
- the relevant part of the app's **Log** tab
- your app configuration, with **passwords, tokens, and broker credentials removed**

Found a security problem? Please report it privately — see [SECURITY.md](SECURITY.md).

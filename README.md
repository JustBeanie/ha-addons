<div align="center">

# Beanie's Home Assistant Apps

**Self-hosted apps (add-ons) for Home Assistant OS and Supervised installs.**

[![Add this repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJustBeanie%2Fha-addons)

[![Commit activity](https://img.shields.io/github/commit-activity/m/JustBeanie/ha-addons?label=activity)](https://github.com/JustBeanie/ha-addons/commits/main/)
[![Open issues](https://img.shields.io/github/issues/JustBeanie/ha-addons)](https://github.com/JustBeanie/ha-addons/issues)
![Architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-success)
[![License](https://img.shields.io/github/license/JustBeanie/ha-addons)](LICENSE)
[![cortisol: low](.github/low-cortisol.svg)](CONTRIBUTING.md#using-ai-tools)

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

## Available Apps

### [BACnet MQTT Gateway](bacnet_mqtt_gateway/)

![Version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Fbacnet_mqtt_gateway%2Fconfig.yaml&query=%24.version&label=version&color=blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success)

Discover and poll BACnet/IP devices, publish their data to MQTT, and manage devices from a Home Assistant ingress console.

Features:

- BACnet/IP network and object discovery
- Configurable polling with Home Assistant MQTT Discovery
- Controlled BACnet property writes
- Supervisor MQTT credentials or an external broker

[Documentation](bacnet_mqtt_gateway/DOCS.md) · [Changelog](bacnet_mqtt_gateway/CHANGELOG.md)

---

### [HA Docs](ha_docs/)

![Version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Fha_docs%2Fconfig.yaml&query=%24.version&label=version&color=blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success)

Turn a Git repository of Markdown files into a searchable MkDocs site in the Home Assistant sidebar.

Features:

- Pulls documentation from a repository and rebuilds when it changes
- Preserves GitHub-style heading links
- Can report broken documentation links in automations and scripts
- Supports private repositories with a read-only token

[Documentation](ha_docs/DOCS.md) · [Changelog](ha_docs/CHANGELOG.md)

---

### [Hyperion.NG](hyperion_ng/)

![Version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Fhyperion_ng%2Fconfig.yaml&query=%24.version&label=version&color=blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success)

Run Hyperion.NG for ambient lighting, with its web interface available through Home Assistant ingress.

Features:

- Persistent configuration included in Home Assistant backups
- Explicit ports for the web interface and Hyperion protocols
- Serial, SPI, and video-capture device mappings

[Documentation](hyperion_ng/DOCS.md) · [Changelog](hyperion_ng/CHANGELOG.md)

---

### [ToneWatch](tonewatch/)

![Version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FJustBeanie%2Fha-addons%2Fmain%2Ftonewatch%2Fconfig.yaml&query=%24.version&label=version&color=blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success) ![Experimental](https://img.shields.io/badge/stage-experimental-orange)

Detect configured two-tone pages, record audio, and publish supplemental notifications through MQTT.

Features:

- Home Assistant ingress interface and MQTT notifications
- Optional Home Assistant MQTT service integration and discovery
- Recordings available in the Home Assistant media browser
- Hot backups with a database checkpoint

ToneWatch is a supplemental notification tool, not a certified primary alerting system.

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

## License

[Apache License 2.0](LICENSE). Hyperion.NG itself is a separate project under its own [license](https://github.com/hyperion-project/hyperion.ng/blob/master/LICENSE).

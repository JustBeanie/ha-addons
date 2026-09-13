<div align="center">
  
# Beanie’s Home Assistant Apps

**Apps for Home Assistant OS and Supervisor.**

[![GitHub activity](https://img.shields.io/github/commit-activity/m/JustBeanie/ha-addons?label=activity)](https://github.com/JustBeanie/ha-addons/commits/main/)
[![GitHub issues](https://img.shields.io/github/issues/JustBeanie/ha-addons)](https://github.com/JustBeanie/ha-addons/issues)
[![Add Repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJustBeanie%2Fha-addons)
</div>

---

## Available Apps

### [BACnet MQTT Gateway](bacnet_mqtt_gateway/)

![Version 2.0.2](https://img.shields.io/badge/version-2.0.2-blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success)

Discover and poll BACnet/IP devices, publish their data to MQTT, and manage devices from a Home Assistant ingress console.

Features:

- BACnet/IP network and object discovery
- Configurable polling with Home Assistant MQTT Discovery
- Controlled BACnet property writes
- Supervisor MQTT credentials or an external broker

[Documentation](bacnet_mqtt_gateway/DOCS.md) · [Changelog](bacnet_mqtt_gateway/CHANGELOG.md)

---

### [HA Docs](ha_docs/)

![Version 1.16.4](https://img.shields.io/badge/version-1.16.4-blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success)

Turn a Git repository of Markdown files into a searchable MkDocs site in the Home Assistant sidebar.

Features:

- Pulls documentation from a repository and rebuilds when it changes
- Preserves GitHub-style heading links
- Can report broken documentation links in automations and scripts
- Supports private repositories with a read-only token

[Documentation](ha_docs/DOCS.md) · [Changelog](ha_docs/CHANGELOG.md)

---

### [Hyperion.NG](hyperion_ng/)

![Version 3.0.8](https://img.shields.io/badge/version-3.0.8-blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success)

Run Hyperion.NG for ambient lighting, with its web interface available through Home Assistant ingress.

Features:

- Persistent configuration included in Home Assistant backups
- Explicit ports for the web interface and Hyperion protocols
- Serial, SPI, and video-capture device mappings

[Documentation](hyperion_ng/DOCS.md) · [Changelog](hyperion_ng/CHANGELOG.md)

---

### [ToneWatch](tonewatch/)

![Version 0.3.0](https://img.shields.io/badge/version-0.3.0-blue) ![aarch64](https://img.shields.io/badge/aarch64-supported-success) ![amd64](https://img.shields.io/badge/amd64-supported-success) ![Experimental](https://img.shields.io/badge/stage-experimental-orange)

Detect configured two-tone pages, record audio, and publish supplemental notifications through MQTT.

Features:

- Home Assistant ingress interface and MQTT notifications
- Optional Home Assistant MQTT service integration and discovery
- Recordings available in the Home Assistant media browser
- Hot backups with a database checkpoint

ToneWatch is a supplemental notification tool, not a certified primary alerting system.

[Documentation](tonewatch/DOCS.md) · [Changelog](tonewatch/CHANGELOG.md)

---

## Installation

[![Add this repository to Home Assistant](https://img.shields.io/badge/Add%20to-Home%20Assistant-41BDF5?logo=home-assistant&logoColor=white)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJustBeanie%2Fha-addons)

Or add this repository URL from the app store’s **Repositories** menu:

```text
https://github.com/JustBeanie/ha-addons
```

Then install an app from **Settings → Apps → App store**.

---

## Support

- [Report an issue](https://github.com/JustBeanie/ha-addons/issues)
- [Home Assistant app documentation](https://developers.home-assistant.io/docs/apps/)

When reporting an issue, include the app version, architecture, relevant logs, and sanitized configuration. Do not include passwords, tokens, or broker credentials.

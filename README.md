# Beanie's Home Assistant Apps

Home Assistant OS/Supervisor app repository maintained by Beanie.

## Install

In Home Assistant, open **Settings → Apps → App store**, choose **Repositories**
from the menu, and add:

```text
https://github.com/JustBeanie/ha-addons
```

## Apps

- **BACnet MQTT Gateway** — BACnet/IP discovery, polling, property writes,
  Home Assistant MQTT Discovery, and an ingress operations console.
- **HA Docs** — locally hosted Home Assistant documentation.
- **Hyperion NG** — Hyperion ambient-lighting service.

See each app's Documentation tab for configuration and security details.

The repository follows the Home Assistant app repository layout. BACnet MQTT
Gateway is distributed as pre-built architecture-specific images from GHCR; the
manifest repository does not compile application code on a user's
Home Assistant host. For local development, use the Home Assistant app
devcontainer or copy the app folder into `/addons` on a test device as described
in the [local testing guide](https://developers.home-assistant.io/docs/apps/testing).

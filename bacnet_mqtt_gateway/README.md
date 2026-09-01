# BACnet MQTT Gateway

Bridge BACnet/IP building-automation devices into MQTT and Home Assistant from a
native Home Assistant OS app.

The app provides:

- BACnet/IP discovery, polling, property writes, and per-device configuration.
- MQTT telemetry, availability, command handling, and Home Assistant discovery.
- An administrator-only web console through Home Assistant ingress.
- Automatic use of the Supervisor MQTT service or an independently hosted MQTT
  broker, including TLS and client-certificate support.
- Persistent runtime state in the app data volume and device configuration in
  the app-specific configuration directory.

BACnet broadcast traffic requires host networking. The web console itself only
accepts Home Assistant ingress traffic.

## Where the source lives

This folder is the Home Assistant app manifest only — `config.yaml`, the
options schema and its translations, the AppArmor profile, and the
documentation shown in the app's tabs.

The application source, its test suite, and the container build are in
[JustBeanie/bacnet-mqtt-gateway](https://github.com/JustBeanie/bacnet-mqtt-gateway).
Each release tag there publishes
`ghcr.io/justbeanie/bacnet-mqtt-gateway-amd64` and `-aarch64`, and the
`image:` key in `config.yaml` pulls the tag matching its `version:`. Nothing is
built on the Home Assistant host.

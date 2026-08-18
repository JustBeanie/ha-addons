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

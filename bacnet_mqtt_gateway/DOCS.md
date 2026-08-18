# Home Assistant App: BACnet MQTT Gateway

## About

BACnet MQTT Gateway discovers and polls BACnet/IP devices, publishes their state
to MQTT, and accepts controlled BACnet property writes. Its web console is
available from the app page and, when enabled, the Home Assistant sidebar.

The app supports `amd64` and `aarch64` Home Assistant OS systems running
Supervisor 2026.07 or newer. That release introduced the current `app_config`
storage mapping used by this app.

## Installation

1. Add `https://github.com/JustBeanie/ha-addons` to the repositories list in the
   Home Assistant app store.
2. Install **BACnet MQTT Gateway**.
3. Review the configuration. The default `supervisor` MQTT mode expects an MQTT
   service provider such as the Mosquitto broker app.
4. Start the app and inspect its log for configuration or network errors.
5. Select **Open Web UI** to discover and configure BACnet devices.

Configuration changes take effect after an app restart.

In the web console, run **Network Scan**, enter a discovered device ID and IP
address under **Object Scan**, select the objects that should become Home
Assistant entities, choose a polling class, and select **Save Polling
Configuration**. That operation persists the configuration and begins polling
immediately; an app restart is not required.

## MQTT configuration

### Supervisor service (recommended)

Set `mqtt_mode` to `supervisor`. The app requests the Supervisor `mqtt` service
and obtains its host, port, username, password, and TLS setting at startup. These
generated service credentials are not copied into the app options.

If the log reports that no MQTT service is available, install/configure an MQTT
broker app or use external mode.

### External broker

Set `mqtt_mode` to `external` and supply `mqtt_external_host`. The port defaults
to `1883`; username and password are optional. Set `mqtt_tls` to `true` for an
MQTTS connection.

TLS file options are paths relative to this app's configuration directory. Do
not enter `/config` or an absolute host path. For example, with files stored at
`/app_configs/<repository>_bacnet_mqtt_gateway/tls/`, use:

```yaml
mqtt_mode: external
mqtt_external_host: mqtt.example.net
mqtt_external_port: 8883
mqtt_tls: true
mqtt_tls_verify: true
mqtt_tls_ca_file: tls/ca.pem
mqtt_tls_cert_file: tls/client.pem
mqtt_tls_key_file: tls/client-key.pem
```

The certificate and key must be configured together. A CA file can be used by
itself. Disabling `mqtt_tls_verify` permits interception and should only be a
temporary diagnostic measure.

### MQTT options

| Option | Purpose |
| --- | --- |
| `mqtt_gateway_id` | Stable gateway identifier used in MQTT topics and entity IDs. |
| `mqtt_external_username` | Optional external-broker username. |
| `mqtt_external_password` | Optional external-broker password. |
| `mqtt_tls_ca_file` | Optional CA bundle below the app configuration directory. |
| `mqtt_tls_cert_file` | Optional client certificate below the app configuration directory. |
| `mqtt_tls_key_file` | Optional client private key below the app configuration directory. |

## BACnet/IP configuration

The app uses host networking because BACnet discovery relies on UDP broadcast.
The default BACnet port is `47808` (hex `BAC0`). Only one process on the Home
Assistant host can bind the selected interface and UDP port.

| Option | Default | Purpose |
| --- | ---: | --- |
| `bacnet_interface` | `0.0.0.0` | Local IPv4 address on which BACnet listens. Use the Home Assistant host address on the BACnet LAN when selection is ambiguous. |
| `bacnet_broadcast_address` | `255.255.255.255` | Broadcast or directed-broadcast address used for discovery. |
| `bacnet_port` | `47808` | BACnet/IP UDP port. |
| `bacnet_apdu_timeout` | `10000` | APDU timeout in milliseconds. |
| `bacnet_max_segments` | `112` | BACnet maximum-segments setting. |
| `bacnet_max_apdu` | `5` | BACstack maximum-APDU enum value. |

Broadcast discovery normally does not cross routers or VLAN boundaries. On a
segmented network, configure routing/broadcast forwarding appropriate for your
BACnet installation or place Home Assistant on the BACnet network.

## Device configuration and persistent data

`bacnet_config_directory` defaults to `devices`. It is created below the app's
private configuration folder and is mounted inside the container as
`/config/devices`. For a local app installation the corresponding host path is
usually `/app_configs/local_bacnet_mqtt_gateway/devices`; repository installs
use the repository identifier assigned by Supervisor.

The app may read and write this directory. Paths containing `.` or `..` path
components, absolute paths, and TLS-file symlinks that leave `/config` are
rejected at startup.

You can also manage device JSON files directly. Start with
`device.example.json` from the app source and name active files
`device.<device-id>.json`. Prefix a file with `_` to disable loading it. The web
console is recommended because it discovers valid object identifiers and writes
the same format safely.

The runtime database and a generated application secret are stored under the
persistent `/data` volume. Backups use cold mode so the app is stopped while its
SQLite database is copied.

## Polling options

| Option | Default | Purpose |
| --- | ---: | --- |
| `polling_global_concurrency` | `2` | Maximum concurrent device polling jobs. |
| `polling_object_concurrency` | `4` | Maximum concurrent object reads within a job. |
| `polling_scheduler_tick_ms` | `1000` | Scheduler evaluation interval. |
| `polling_default_freshness_ms` | `30000` | Default age after which cached data is stale. |
| `polling_failure_threshold` | `3` | Consecutive failures before opening the device circuit breaker. |
| `polling_base_backoff_ms` | `5000` | Initial retry backoff. |
| `polling_max_backoff_ms` | `120000` | Maximum retry backoff. |

Increase concurrency cautiously on slow MS/TP routers or heavily loaded BACnet
networks.

## Home Assistant MQTT Discovery

After the first successful poll, the gateway publishes retained discovery
records below `homeassistant/` and creates one Home Assistant device per BACnet
device. Entity identifiers include both the BACnet device ID and object ID, so
the same point numbers on different devices do not collide. State, attributes,
availability, unit metadata, and a canonical telemetry record are published at
QoS 1. The gateway also publishes retained `online`/`offline` availability.

Changing `mqtt_gateway_id` creates a new discovery namespace; remove retained
records from the old namespace if you intentionally rename a deployed gateway.

## Ingress and security

The console listens internally on TCP port `18082`, but it rejects application
requests that do not originate from the Home Assistant ingress proxy
(`172.30.32.2`). Health checks from loopback are also accepted. The sidebar panel
is administrator-only and the gateway uses the authenticated ingress user.

Host networking is unavoidable for the required BACnet broadcast behavior. The
app otherwise runs with Supervisor protection enabled, no privileged
capabilities, no Home Assistant or Docker API access, and a custom AppArmor
profile. Keep Home Assistant OS and Supervisor current.

## Troubleshooting

### App exits with no Supervisor MQTT service

Start and configure the Mosquitto broker app, then restart this app. Alternatively
select external MQTT mode and configure the external host.

### BACnet discovery returns no devices

- Confirm `bacnet_interface` belongs to the BACnet-facing network.
- Use the subnet's directed broadcast address if limited broadcast is filtered.
- Allow BACnet UDP traffic through local network firewalls.
- Check that another BACnet process is not already using the configured port.
- Remember that broadcast traffic normally remains inside its IP subnet.

### App will not start because a port is in use

The app needs the selected BACnet UDP port and TCP `18082` on the Home Assistant
host. Stop the conflicting service or, for BACnet, choose a different port that
matches the BACnet network configuration. The ingress HTTP port is fixed in this
release.

### TLS file error

Confirm the path is relative to the app configuration directory and the file is
readable. Client certificates require both the certificate and private-key
options. TLS files are rejected when MQTT TLS is disabled.

### MQTT connects but data is missing

Check the gateway ID, broker ACLs, app logs, and the device polling configuration
in the web console. Set `log_level` to `debug` temporarily for more detail.

## Support

Report issues at <https://github.com/JustBeanie/ha-addons/issues> and include the
app version, architecture, sanitized configuration, and relevant logs. Never
include MQTT passwords or private keys.

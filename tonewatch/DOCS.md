# Home Assistant App: ToneWatch

## About

ToneWatch listens for configured two-tone pages, records the following audio,
and publishes notifications through MQTT. It runs on `amd64` and `aarch64`
Home Assistant systems as an experimental app.

ToneWatch is a supplemental notification tool, not a certified primary alerting
system. Keep a separate, tested primary alerting path for life-safety or
mission-critical notifications.

## Installation and ingress

1. Add `https://github.com/JustBeanie/ha-addons` to the Home Assistant app
   store repositories.
2. Install **ToneWatch**, review its options, and start it.
3. Open the app's **Open Web UI** action or its Home Assistant sidebar panel.

The web UI is served through Home Assistant ingress on port `8099`. Ingress
provides the Home Assistant session to the app. An ingress URL is not suitable
for `public_base_url`, because an external webhook or MQTT consumer cannot use
that Home Assistant session.

## Options

| Option | Values | Purpose |
| --- | --- | --- |
| `log_level` | `debug`, `info`, `warning`, `error` | Sets structured log verbosity. |
| `public_base_url` | optional `http` or `https` URL | Makes recording links absolute for external consumers; the trailing slash is normalized. |
| `mqtt_mode` | `supervisor`, `manual`, `off` | Uses Supervisor MQTT credentials, leaves manual targets unchanged, or disables MQTT publishers at runtime. |
| `ui_password` | optional password | Enables the local UI password in addition to ingress authentication. |

Environment variables take precedence over app options. Set
`public_base_url` to a direct host and port reachable by the notification
consumer, or rely on the authenticated proxy supplied by the future M11
integration.

## MQTT and discovery

With `mqtt_mode: supervisor`, the app requests the MQTT service from Supervisor
at connection time and refreshes credentials after each reconnect. Credentials
are held in memory for the active connection and are not stored in the app
configuration, audit records, logs, API responses, or discovery payloads.

The manifest requests the Supervisor `mqtt:want` service and publishes the
ToneWatch discovery service. With `mqtt_mode: manual`, configure MQTT targets
in ToneWatch. With `mqtt_mode: off`, all MQTT publishers are disabled while
their saved targets remain available for later use.

## Recordings and backups

Recordings are stored under `/media/tonewatch`, which is shown by Home
Assistant under **Media → tonewatch**. When `public_base_url` is set, alert
payloads contain an absolute recording URL. When it is unset, they contain a
relative recording path and mark it as relative.

The app uses a hot backup. Before Supervisor copies the live data, it runs
`tonewatch db checkpoint` to checkpoint the SQLite write-ahead log without
stopping monitoring. Do not change this to a cold backup: a cold backup would
stop a paging monitor during every scheduled backup.

## Audio and SDR devices

The manifest enables Home Assistant audio and USB access. Follow the device
mapping decision in [ADR 0009](https://github.com/JustBeanie/tonewatch/blob/main/docs/decisions/0009-addon-mode.md):
select the exposed ALSA input for a host audio device, and use the mapped USB
device for an RTL-SDR. The image does not claim PulseAudio routing, generate an
ALSA configuration, or provide `libasound2-plugins`; real device capture and
the exact Home Assistant mapping require hardware verification.

## Support

Report issues at <https://github.com/JustBeanie/ha-addons/issues> with the app
version, architecture, sanitized options, and relevant logs. Never include
passwords, Supervisor tokens, or MQTT credentials.

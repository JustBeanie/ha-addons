# ToneWatch

ToneWatch is an experimental Home Assistant app for two-tone page detection,
call recording, MQTT notifications, and Home Assistant discovery.

This directory is the manifest only. It points to the published multi-arch
image `ghcr.io/justbeanie/tonewatch`; the application source and container
build live in [JustBeanie/tonewatch](https://github.com/JustBeanie/tonewatch).

Open the app through Home Assistant ingress. Recordings are mapped to the
Home Assistant media browser under `Media → tonewatch`. See [DOCS.md](DOCS.md)
for options, Supervisor MQTT behavior, hot backups, and audio/SDR device notes.

ToneWatch is a supplemental notification tool, not a certified primary
alerting system.

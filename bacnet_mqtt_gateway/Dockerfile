FROM ghcr.io/home-assistant/base:3.22

ARG BUILD_VERSION=2.0.0
ARG BUILD_ARCH

ENV NODE_ENV=production \
    NODE_CONFIG_DIR=/opt/bacnet-mqtt-gateway/config \
    APP_VERSION=${BUILD_VERSION} \
    SCARF_ANALYTICS=false

WORKDIR /opt/bacnet-mqtt-gateway

COPY package.json package-lock.json ./

RUN apk add --no-cache \
        nodejs \
        npm \
        sqlite-libs \
    && apk add --no-cache --virtual .build-dependencies \
        g++ \
        linux-headers \
        make \
        python3 \
    && npm ci --omit=dev --no-audit --no-fund \
    && node -e "require('sqlite3'); require('bacstack'); require('mqtt'); require('express')" \
    && npm cache clean --force \
    && apk del .build-dependencies

COPY config ./config
COPY scripts ./scripts
COPY src ./src
COPY web ./web
COPY LICENSE openapi.yaml device.example.json ./
COPY run.sh /run.sh

RUN chmod 0755 /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="BACnet MQTT Gateway" \
    org.opencontainers.image.description="BACnet/IP to MQTT gateway for Home Assistant" \
    org.opencontainers.image.source="https://github.com/JustBeanie/ha-addons" \
    org.opencontainers.image.licenses="Apache-2.0" \
    org.opencontainers.image.version="${BUILD_VERSION}"

CMD ["/run.sh"]

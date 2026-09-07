FROM ghcr.io/home-assistant/base-debian:bookworm

ARG BUILD_ARCH
ARG BUILD_VERSION
ARG HYPERION_VERSION=2.2.1

LABEL \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install the official Hyperion release package rather than inheriting a
# third-party image. The checksums make a release update explicit and prevent
# a changed upstream asset from silently entering the app image.
RUN set -euo pipefail; \
    case "${BUILD_ARCH}" in \
        amd64) \
            HYPERION_ARCH="amd64"; \
            HYPERION_SHA256="8e30585049421297455387564f8df2c87603f0f8557bc95abca102be27e872b9"; \
            ;; \
        aarch64) \
            HYPERION_ARCH="arm64"; \
            HYPERION_SHA256="ee5e9eaeeb4a6bc69174b15dcb316de274cc77dab93fc5c370905e04ca2f056b"; \
            ;; \
        *) echo "Unsupported Home Assistant architecture: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl libexpat1 libfontconfig1; \
    package="/tmp/hyperion.deb"; \
    curl -fsSL -o "${package}" \
        "https://github.com/hyperion-project/hyperion.ng/releases/download/${HYPERION_VERSION}/Hyperion-${HYPERION_VERSION}-Linux-${HYPERION_ARCH}.deb"; \
    echo "${HYPERION_SHA256}  ${package}" | sha256sum -c -; \
    apt-get install -y --no-install-recommends "${package}"; \
    rm -f "${package}"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["curl", "-fsS", "http://127.0.0.1:8090/"]

CMD ["hyperiond"]

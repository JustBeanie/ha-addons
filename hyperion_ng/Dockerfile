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
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libbz2-1.0 \
        libcec6 \
        libcrypt1 \
        libdb5.3 \
        libexpat1 \
        libfontconfig1 \
        libglib2.0-0 \
        liblzma5 \
        libncursesw6 \
        libnsl2 \
        libreadline8 \
        libsystemd0 \
        libtinfo6 \
        libtirpc3 \
        libudev1 \
        libuuid1 \
        zlib1g; \
    package="/tmp/hyperion.deb"; \
    curl -fsSL -o "${package}" \
        "https://github.com/hyperion-project/hyperion.ng/releases/download/${HYPERION_VERSION}/Hyperion-${HYPERION_VERSION}-Linux-${HYPERION_ARCH}.deb"; \
    echo "${HYPERION_SHA256}  ${package}" | sha256sum -c -; \
    apt-get install -y --no-install-recommends "${package}"; \
    web_root="$(dirname "$(find / -type f -path '*/webconfig/js/hyperion.js' -print -quit)")"; \
    test -n "${web_root}" -a -f "${web_root}/hyperion.js"; \
    sed -i -z -E \
        -e 's#\$\.get("/cgi/cfg_jsonserver"#\$\.get("./cgi/cfg_jsonserver"#' \
        -e 's#globalThis\.websocket =\s*(document\.location\.protocol == "https:")\s*\?\s*new WebSocket\([^;]+\)\s*:\s*new WebSocket\([^;]+\);#globalThis.websocket = new WebSocket(new URL(".", document.location.href).toString().replace(/^http/, "ws"));#' \
        "${web_root}/hyperion.js"; \
    sed -i \
        -e 's#\.load("/content/#.load("./content/#g' \
        "${web_root}/../js/ui_utils.js"; \
    sed -i \
        -e "s#location.replace('/')#location.replace('./')#" \
        "${web_root}/../js/settings.js"; \
    find "${web_root}/.." -type f -name '*.html' -exec sed -i -E 's#(href|src)="/#\1="./#g' {} +; \
    rm -f "${package}"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["curl", "-fsS", "http://127.0.0.1:8090/"]

CMD ["hyperiond"]

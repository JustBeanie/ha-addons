FROM ghcr.io/hyperion-project/debian:bookworm-qt6 AS hyperion-builder

ARG HYPERION_VERSION=2.2.1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates cmake dpkg-dev git ninja-build \
        pkg-config; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Build from the upstream release tag so the embedded web client can be made
# ingress-aware before Hyperion's Qt resource bundle is compiled.
RUN git clone --depth 1 --branch "${HYPERION_VERSION}" --recursive \
    https://github.com/hyperion-project/hyperion.ng.git

WORKDIR /src/hyperion/build

RUN find /src/hyperion -type f -name hyperion.js -exec sed -i \
        -e 's#\$\.get("/cgi/cfg_jsonserver"#\$\.get("./cgi/cfg_jsonserver"#' {} +; \
    find /src/hyperion -type f -name hyperion.js -exec sed -i -z -E \
        -e 's#globalThis\.websocket =\s*(document\.location\.protocol == "https:")\s*\?\s*new WebSocket\([^;]+\)\s*:\s*new WebSocket\([^;]+\);#globalThis.websocket = new WebSocket(new URL(".", document.location.href).toString().replace(/^http/, "ws"));#' \
        {} +; \
    find /src/hyperion -type f -name ui_utils.js -exec sed -i \
        -e 's#\.load("/content/#.load("./content/#g' \
        {} +; \
    find /src/hyperion -type f -name settings.js -exec sed -i \
        -e "s#location.replace('/')#location.replace('./')#" \
        {} +; \
    find /src/hyperion -type f -path '*/assets/webconfig/*.html' \
        -exec sed -i -E 's#(href|src)="/#\1="./#g' {} +; \
    cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ..; \
    cmake --build . --target package -- -j"$(nproc)"

FROM ghcr.io/home-assistant/base-debian:bookworm

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -euo pipefail; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl libbz2-1.0 libcec6 libcrypt1 libdb5.3 \
        libexpat1 libfontconfig1 libglib2.0-0 liblzma5 libncursesw6 \
        libnsl2 libreadline8 libsystemd0 libtinfo6 libtirpc3 libudev1 \
        libuuid1 zlib1g; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

COPY --from=hyperion-builder /src/hyperion/build/Hyperion-*.deb /tmp/

RUN set -euo pipefail; \
    apt-get update; \
    apt-get install -y --no-install-recommends /tmp/Hyperion-*.deb; \
    rm -f /tmp/Hyperion-*.deb; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["curl", "-fsS", "http://127.0.0.1:8090/"]

CMD ["hyperiond"]

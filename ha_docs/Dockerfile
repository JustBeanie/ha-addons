ARG BUILD_FROM
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION
LABEL \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Direct Python dependencies are pinned in requirements.txt so Dependabot can
# propose updates and CI can build the same direct versions on every
# architecture.
ARG MERMAID_VERSION=11.16.0

COPY requirements.txt /tmp/ha-docs-requirements.txt

RUN apk add --no-cache \
        git \
        nginx \
        python3 \
        py3-pip \
        py3-websockets \
    && apk add --no-cache --virtual .build-deps \
        build-base \
        python3-dev \
        libffi-dev \
    && pip install --no-cache-dir --break-system-packages \
        -r /tmp/ha-docs-requirements.txt \
    && pip check \
    && apk del .build-deps \
    && rm -rf /root/.cache /tmp/ha-docs-requirements.txt

# Mermaid is vendored into the image, not loaded at page load. Material's own
# diagram support pulls the runtime from a CDN, which a LAN-only box cannot
# reach - see overrides/assets/mermaid-init.js for how that path is avoided.
# The UMD build is one self-contained file; the .mjs build lazy-loads chunks
# and would need the whole dist/ tree.
RUN apk add --no-cache --virtual .dl-deps curl \
    && mkdir -p /opt/ha_docs/overrides/assets \
    && curl -fsSL -o /opt/ha_docs/overrides/assets/mermaid.min.js \
        "https://cdn.jsdelivr.net/npm/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js" \
    && apk del .dl-deps

COPY mkdocs.yml ghslug.py annotations.py /opt/ha_docs/
COPY check_anchors.py entity_watch.py repairs_registry.py scan_status.py /opt/ha_docs/
# Merges with the directory the RUN above created - COPY does not clear the
# destination - so the vendored mermaid.min.js survives. Keep this ordering:
# the 3.5 MB download stays in a cached layer when only the overrides change.
COPY overrides/ /opt/ha_docs/overrides/
COPY nginx.conf /etc/nginx/nginx.conf
COPY run.sh /run.sh
RUN nginx -t \
    && chmod a+x /run.sh

# An application-level probe rather than just "is the container still up".
# /anno/health is served by annotations.py and proxied by nginx, so a failure
# means one of the two processes this app depends on has gone.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/anno/health', timeout=3)"]

CMD [ "/run.sh" ]

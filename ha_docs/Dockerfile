ARG BUILD_FROM
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Versions pinned so a rebuild months from now produces the same site.
ARG MKDOCS_VERSION=1.6.1
ARG MATERIAL_VERSION=9.7.7
ARG PYMDOWN_VERSION=11.0.1
ARG MERMAID_VERSION=11.16.0

RUN apk add --no-cache \
        git \
        nginx \
        python3 \
        py3-pip \
    && apk add --no-cache --virtual .build-deps \
        build-base \
        python3-dev \
        libffi-dev \
    && pip install --no-cache-dir --break-system-packages \
        "mkdocs==${MKDOCS_VERSION}" \
        "mkdocs-material==${MATERIAL_VERSION}" \
        "pymdown-extensions==${PYMDOWN_VERSION}" \
    && apk del .build-deps \
    && rm -rf /root/.cache

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
COPY ../scripts/check_anchors.py /opt/ha_docs/check_anchors.py
# Merges with the directory the RUN above created - COPY does not clear the
# destination - so the vendored mermaid.min.js survives. Keep this ordering:
# the 3.5 MB download stays in a cached layer when only the overrides change.
COPY overrides/ /opt/ha_docs/overrides/
COPY nginx.conf /etc/nginx/nginx.conf
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

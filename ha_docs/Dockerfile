ARG BUILD_FROM
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Versions pinned so a rebuild months from now produces the same site.
ARG MKDOCS_VERSION=1.6.1
ARG MATERIAL_VERSION=9.7.7
ARG PYMDOWN_VERSION=11.0.1

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

COPY mkdocs.yml ghslug.py /opt/ha_docs/
COPY nginx.conf /etc/nginx/nginx.conf
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -o nounset -o pipefail

REPO=$(bashio::config 'repository')
BRANCH=$(bashio::config 'branch')
INTERVAL=$(bashio::config 'poll_interval')

export SITE_NAME
SITE_NAME=$(bashio::config 'site_name')
# ghslug.py is imported by mkdocs.yml via !!python/name:
export PYTHONPATH=/opt/ha_docs

readonly CONFIG=/opt/ha_docs/mkdocs.yml
readonly REPO_DIR=/data/repo
readonly SITE_DIR=/data/site
readonly SHA_FILE=/data/.last_sha

# Build the URL git actually uses. Kept in a separate variable that is never
# logged, so a token cannot leak into the add-on log.
AUTH_REPO="${REPO}"
if bashio::config.has_value 'git_token'; then
    AUTH_REPO="${REPO/https:\/\//https://$(bashio::config 'git_token')@}"
    bashio::log.info "Using authenticated access for the docs repository"
fi

sync_repo() {
    if [ -d "${REPO_DIR}/.git" ]; then
        git -C "${REPO_DIR}" remote set-url origin "${AUTH_REPO}"
        git -C "${REPO_DIR}" fetch --depth 1 --quiet origin "${BRANCH}" || return 1
        git -C "${REPO_DIR}" reset --hard --quiet "origin/${BRANCH}" || return 1
    else
        rm -rf "${REPO_DIR}"
        git clone --depth 1 --quiet --branch "${BRANCH}" \
            "${AUTH_REPO}" "${REPO_DIR}" || return 1
    fi
}

build_site() {
    # Build to a scratch directory and swap it in. If mkdocs fails we keep
    # serving the previous site rather than blanking it.
    rm -rf "${SITE_DIR}.new"
    if ! mkdocs build --quiet --config-file "${CONFIG}" \
            --site-dir "${SITE_DIR}.new"; then
        rm -rf "${SITE_DIR}.new"
        return 1
    fi
    rm -rf "${SITE_DIR}.old"
    [ -d "${SITE_DIR}" ] && mv "${SITE_DIR}" "${SITE_DIR}.old"
    mv "${SITE_DIR}.new" "${SITE_DIR}"
    rm -rf "${SITE_DIR}.old"
}

# One pull + conditional rebuild. Returns non-zero only on hard failure.
refresh() {
    if ! sync_repo; then
        bashio::log.warning "git sync failed - keeping the current site"
        return 1
    fi

    local sha previous
    sha=$(git -C "${REPO_DIR}" rev-parse HEAD)
    previous=$(cat "${SHA_FILE}" 2>/dev/null || true)

    if [ "${sha}" = "${previous}" ] && [ -d "${SITE_DIR}" ]; then
        bashio::log.debug "No change (${sha:0:7})"
        return 0
    fi

    bashio::log.info "Building docs at ${sha:0:7}"
    if build_site; then
        echo "${sha}" > "${SHA_FILE}"
        bashio::log.info "Site rebuilt"
    else
        bashio::log.error "mkdocs build failed - keeping the previous site"
        return 1
    fi
}

bashio::log.info "Docs source: ${REPO} (${BRANCH}), polling every ${INTERVAL}s"

refresh || bashio::log.warning "Initial refresh failed"

# nginx needs something to serve even if the very first build failed.
if [ ! -d "${SITE_DIR}" ]; then
    mkdir -p "${SITE_DIR}"
    echo "<h1>HA Docs</h1><p>No site built yet - check the add-on log.</p>" \
        > "${SITE_DIR}/index.html"
fi

bashio::log.info "Starting nginx on port 8099"
nginx &
readonly NGINX_PID=$!

trap 'kill "${NGINX_PID}" 2>/dev/null; exit 0' SIGTERM SIGINT

while true; do
    sleep "${INTERVAL}" &
    wait $!
    refresh || true
done

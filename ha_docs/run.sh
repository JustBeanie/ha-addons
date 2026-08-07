#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -o nounset -o pipefail

REPO=$(bashio::config 'repository')
BRANCH=$(bashio::config 'branch')
INTERVAL=$(bashio::config 'poll_interval')

export SITE_NAME
SITE_NAME=$(bashio::config 'site_name')
# Read by annotations.py. Empty means notes are stored but not mirrored to a
# to-do list; SUPERVISOR_TOKEN is already in the environment via
# homeassistant_api in config.yaml. Guarded with has_value rather than passing
# a default, so an unset option cannot arrive as the string "null".
export TODO_ENTITY=""
if bashio::config.has_value 'todo_entity'; then
    TODO_ENTITY=$(bashio::config 'todo_entity')
fi
# ghslug.py is imported by mkdocs.yml via !!python/name:
export PYTHONPATH=/opt/ha_docs

readonly CONFIG=/opt/ha_docs/mkdocs.yml
readonly REPO_DIR=/data/repo
readonly SITE_DIR=/data/site
readonly STAMP_FILE=/data/.last_build

# The built site is cached against the commit it came from AND the builder that
# produced it. Keying on the commit alone was a bug: /data survives an image
# rebuild, so upgrading the add-on left the previous site in place and the new
# mkdocs.yml was never used until the docs repo happened to get a commit. That
# is how 1.1.0 shipped Mermaid support that did not appear.
#
# BUILDER_ID hashes everything in the image that can change the output -
# mkdocs.yml, ghslug.py, and the theme overrides including the vendored Mermaid
# runtime. Computed once at startup, not per poll, because that tree holds a
# 3.5 MB JS file.
#
# Note the new filename: the old /data/.last_sha is deliberately not read, so
# the first run after this upgrade always rebuilds.
BUILDER_ID=$(find /opt/ha_docs -type f -print0 \
    | xargs -0 md5sum | sort -k 2 | md5sum | cut -d' ' -f1)
readonly BUILDER_ID

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

    local sha stamp previous
    sha=$(git -C "${REPO_DIR}" rev-parse HEAD)
    stamp="${sha} ${BUILDER_ID}"
    previous=$(cat "${STAMP_FILE}" 2>/dev/null || true)

    if [ "${stamp}" = "${previous}" ] && [ -d "${SITE_DIR}" ]; then
        bashio::log.debug "No change (${sha:0:7})"
        return 0
    fi

    bashio::log.info "Building docs at ${sha:0:7} (builder ${BUILDER_ID:0:7})"
    if build_site; then
        echo "${stamp}" > "${STAMP_FILE}"
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

# Highlights and notes live in /data, never in the docs repo - the add-on still
# only ever pulls. Started before nginx so the first page load cannot race it.
bashio::log.info "Starting the annotation store"
python3 /opt/ha_docs/annotations.py &
readonly ANNO_PID=$!

bashio::log.info "Starting nginx on port 8099"
nginx &
readonly NGINX_PID=$!

trap 'kill "${NGINX_PID}" "${ANNO_PID}" 2>/dev/null; exit 0' SIGTERM SIGINT

while true; do
    sleep "${INTERVAL}" &
    wait $!
    refresh || true
done

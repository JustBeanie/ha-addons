#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -o nounset -o pipefail

REPO=$(bashio::config 'repository')
BRANCH=$(bashio::config 'branch')
INTERVAL=$(bashio::config 'poll_interval')
REPORT_DOC_LINK_REPAIRS=$(bashio::config 'report_doc_link_repairs')
REPAIR_SCAN_ON_START=$(bashio::config 'repair_scan_on_start')
REPAIR_SCAN_CONCURRENCY=$(bashio::config 'repair_scan_concurrency')
REPAIR_PROGRESS_INTERVAL=$(bashio::config 'repair_progress_interval')
REPAIR_SCAN_HEARTBEAT_INTERVAL=$(bashio::config 'repair_scan_heartbeat_interval')
LOG_LEVEL=$(bashio::config 'log_level')

case "${LOG_LEVEL}" in
    trace) LOG_THRESHOLD=0 ;;
    debug) LOG_THRESHOLD=1 ;;
    info) LOG_THRESHOLD=2 ;;
    warning) LOG_THRESHOLD=3 ;;
    error) LOG_THRESHOLD=4 ;;
    *) LOG_THRESHOLD=2 ;;
esac

log() {
    local level=$1 weight message
    shift
    case "${level}" in
        TRACE) weight=0 ;;
        DEBUG) weight=1 ;;
        INFO) weight=2 ;;
        WARNING) weight=3 ;;
        ERROR) weight=4 ;;
        *) return 2 ;;
    esac
    if [ "${weight}" -ge "${LOG_THRESHOLD}" ]; then
        message="$*"
        printf '%s [%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "${level}" "${message}" >&2
    fi
}

log_trace() { log TRACE "$@"; }
log_debug() { log DEBUG "$@"; }
log_info() { log INFO "$@"; }
log_warning() { log WARNING "$@"; }
log_error() { log ERROR "$@"; }

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
readonly DOC_LINK_AUDIT=/data/doc-link-repairs.jsonl

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
    log_info "Using authenticated access for the docs repository"
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

reconcile_ha_docs_links() {
    if [ "${REPORT_DOC_LINK_REPAIRS}" != "true" ]; then
        log_info "HA documentation-link Repair reporting is disabled"
        return 0
    fi

    # Only GitHub blob links are accepted in entity descriptions. Keep REPO
    # (rather than AUTH_REPO) here so a configured git token cannot enter a
    # description or an audit record.
    case "${REPO}" in
        https://github.com/*.git)
            local base="${REPO%.git}/blob/${BRANCH}"
            ;;
        https://github.com/*)
            local base="${REPO}/blob/${BRANCH}"
            ;;
        *)
            log_warning "HA Docs-link Repair scan requires a GitHub repository URL"
            return 1
            ;;
    esac

    HA_DOC_LINK_AUDIT="${DOC_LINK_AUDIT}" \
        python3 /opt/ha_docs/check_anchors.py --ha --report \
        --log-level "${LOG_LEVEL}" \
        --scan-concurrency "${REPAIR_SCAN_CONCURRENCY}" \
        --progress-interval "${REPAIR_PROGRESS_INTERVAL}" \
        --heartbeat-interval "${REPAIR_SCAN_HEARTBEAT_INTERVAL}" \
        --github-base "${base}" "${REPO_DIR}"
}

# One pull + conditional rebuild. Returns non-zero only on hard failure.
refresh() {
    local reason=$1 started_at=$SECONDS
    log_info "Refresh worker started: reason=${reason}"
    if ! sync_repo; then
        log_warning "Repository sync failed; continuing to serve the current site"
        return 1
    fi

    # This runs on add-on start and after every successful pull, including an
    # unchanged commit. It validates live descriptions against the freshly
    # pulled source before a static build is published.
    if ! python3 /opt/ha_docs/check_anchors.py --source --log-level "${LOG_LEVEL}" "${REPO_DIR}"; then
        log_error "Source anchor check failed; continuing to serve the current site"
        return 1
    fi

    local sha stamp previous
    sha=$(git -C "${REPO_DIR}" rev-parse HEAD)
    stamp="${sha} ${BUILDER_ID}"
    previous=$(cat "${STAMP_FILE}" 2>/dev/null || true)

    if [ "${stamp}" = "${previous}" ] && [ -d "${SITE_DIR}" ]; then
        log_debug "Docs source unchanged: commit=${sha:0:7}"
    else
        log_info "Building docs: commit=${sha:0:7} builder=${BUILDER_ID:0:7}"
        if build_site; then
            echo "${stamp}" > "${STAMP_FILE}"
            log_info "Docs site published: commit=${sha:0:7}"
        else
            log_error "MkDocs build failed; continuing to serve the previous site"
            return 1
        fi
    fi

    if [ "${reason}" != "startup-skipped" ]; then
        if ! reconcile_ha_docs_links; then
            log_error "HA Docs-link Repair scan completed with failures"
            return 1
        fi
    else
        log_info "HA Docs-link Repair scan skipped by repair_scan_on_start=false"
    fi
    log_info "Refresh worker completed: reason=${reason} elapsed_seconds=$((SECONDS - started_at))"
}

# nginx needs something to serve even if the very first build failed.
if [ ! -d "${SITE_DIR}" ]; then
    mkdir -p "${SITE_DIR}"
    echo "<h1>HA Docs</h1><p>Initial documentation sync is in progress. Check the app log for status.</p>" \
        > "${SITE_DIR}/index.html"
fi

# Highlights and notes live in /data, never in the docs repo - the add-on still
# only ever pulls. Start all ingress services before network and API work.
log_info "HA Docs starting: source=${REPO} branch=${BRANCH} poll_interval=${INTERVAL}s"
log_info "Starting annotation store"
python3 /opt/ha_docs/annotations.py &
readonly ANNO_PID=$!

log_info "Starting nginx on port 8099"
nginx &
readonly NGINX_PID=$!

refresh_worker() {
    local initial_reason=startup
    if [ "${REPAIR_SCAN_ON_START}" != "true" ]; then
        initial_reason=startup-skipped
    fi
    refresh "${initial_reason}" || log_warning "Refresh worker failed: reason=${initial_reason}"
    while true; do
        sleep "${INTERVAL}"
        refresh poll || log_warning "Refresh worker failed: reason=poll"
    done
}

log_info "Starting background refresh and Docs-link Repair worker"
refresh_worker &
readonly WORKER_PID=$!

trap 'kill "${WORKER_PID}" "${NGINX_PID}" "${ANNO_PID}" 2>/dev/null; exit 0' SIGTERM SIGINT

wait "${WORKER_PID}"

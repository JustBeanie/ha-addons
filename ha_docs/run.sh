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
WATCH_ENTITY_UPDATES=$(bashio::config 'watch_entity_updates')
ENTITY_UPDATE_DEBOUNCE=$(bashio::config 'entity_update_debounce')
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
# Alerted when a failed source check freezes the site. Empty means the Repairs
# issue is still raised, there is just no push -- same has_value guard as above
# so an unset option cannot arrive as the string "null".
NOTIFY_SERVICE=""
if bashio::config.has_value 'notify_service'; then
    NOTIFY_SERVICE=$(bashio::config 'notify_service')
fi
# Where the two checkers record what they are doing, for annotations.py to
# serve at /anno/scan. There is deliberately no default inside scan_status.py:
# unset makes every writer there a no-op, so running check_anchors.py by hand
# on a workstation cannot scatter status files across it.
export HA_DOCS_SCAN_STATUS_DIR=/data/scan
# Read by annotations.py so the site can say "switched off in the add-on
# configuration" rather than "this has never run".
export REPORT_DOC_LINK_REPAIRS WATCH_ENTITY_UPDATES
# ghslug.py is imported by mkdocs.yml via !!python/name:
export PYTHONPATH=/opt/ha_docs

readonly CONFIG=/opt/ha_docs/mkdocs.yml
readonly REPO_DIR=/data/repo
readonly SITE_DIR=/data/site
readonly STAMP_FILE=/data/.last_build
readonly DOC_LINK_AUDIT=/data/doc-link-repairs.jsonl
readonly DOC_LINK_READY=/data/.doc-link-checker-ready
# Touched by annotations.py when the Sync button in the site header is used.
readonly SYNC_REQUEST=/data/.sync-now
# Bumped after every completed refresh pass, changed or not, so the site can
# tell "still working" from "looked, nothing new".
readonly REFRESH_MARKER=/data/.last_refresh

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

# Keep authentication out of the repository URL. Git stores the remote URL in
# /data/repo/.git/config, and embedding a personal access token there would
# leave a long-lived secret in the add-on's persistent data. The temporary
# config environment below applies the header only to the Git process that
# needs it.
GIT_TOKEN=""
GIT_AUTH=""
if bashio::config.has_value 'git_token'; then
    GIT_TOKEN=$(bashio::config 'git_token')
    # GitHub's Git-over-HTTPS endpoint accepts a PAT as the password in HTTP
    # Basic authentication. Bearer is valid for the REST API, but Git treats
    # that header as unauthenticated and falls back to its username prompt.
    # Keep the encoded credential in the per-process environment only; never
    # put it in the persistent remote URL or command-line arguments.
    GIT_AUTH=$(printf 'x-access-token:%s' "${GIT_TOKEN}" | base64 | tr -d '\r\n')
    log_info "Using authenticated access for the docs repository"
fi

git_with_auth() {
    if [ -n "${GIT_TOKEN}" ]; then
        GIT_TERMINAL_PROMPT=0 \
        GIT_CONFIG_COUNT=1 \
        GIT_CONFIG_KEY_0=http.extraHeader \
        GIT_CONFIG_VALUE_0="Authorization: Basic ${GIT_AUTH}" \
        git "$@"
    else
        git "$@"
    fi
}

# The GitHub blob base for the configured repo, or a non-zero return when it is
# not a GitHub URL. It is derived from REPO only, so a configured git_token
# cannot reach an entity description, an audit record, or a page.
github_blob_base() {
    case "${REPO}" in
        https://github.com/*.git) echo "${REPO%.git}/blob/${BRANCH}" ;;
        https://github.com/*)     echo "${REPO}/blob/${BRANCH}" ;;
        *) return 1 ;;
    esac
}

# Read by mkdocs.yml via !ENV to put per-page "edit" and "view source" links on
# the site. Same token-safety rule as above: built from REPO, never from the
# authenticated Git value.
# Left empty for a non-GitHub repo, which switches the two actions off rather
# than pointing them somewhere wrong.
export REPO_URL=""
export EDIT_URI=""
case "${REPO}" in
    https://github.com/*)
        REPO_URL="${REPO%.git}"
        EDIT_URI="edit/${BRANCH}/"
        ;;
esac

sync_repo() {
    if [ -d "${REPO_DIR}/.git" ]; then
        # Normalize a remote left by an older release that embedded the token.
        git -C "${REPO_DIR}" remote set-url origin "${REPO}"
        git_with_auth -C "${REPO_DIR}" fetch --depth 1 --quiet origin "${BRANCH}" || return 1
        git -C "${REPO_DIR}" reset --hard --quiet "origin/${BRANCH}" || return 1
    else
        rm -rf "${REPO_DIR}"
        git_with_auth clone --depth 1 --quiet --branch "${BRANCH}" \
            "${REPO}" "${REPO_DIR}" || return 1
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
    # (rather than an authenticated Git value) here so a configured git token
    # cannot enter a description or an audit record.
    local base
    if ! base=$(github_blob_base); then
        log_warning "HA Docs-link Repair scan requires a GitHub repository URL"
        return 1
    fi

    HA_DOC_LINK_AUDIT="${DOC_LINK_AUDIT}" \
        python3 /opt/ha_docs/check_anchors.py --ha --report \
        --log-level "${LOG_LEVEL}" \
        --scan-concurrency "${REPAIR_SCAN_CONCURRENCY}" \
        --progress-interval "${REPAIR_PROGRESS_INTERVAL}" \
        --heartbeat-interval "${REPAIR_SCAN_HEARTBEAT_INTERVAL}" \
        --github-base "${base}" "${REPO_DIR}"
}

# Withdraw Repairs issues whose automation or script no longer exists. Needs
# neither the repository nor a GitHub base: it is about Home Assistant state,
# and the only thing it reads from the docs side is nothing at all.
reap_orphan_doc_link_repairs() {
    if [ "${REPORT_DOC_LINK_REPAIRS}" != "true" ]; then
        return 0
    fi
    HA_DOC_LINK_AUDIT="${DOC_LINK_AUDIT}" \
        python3 /opt/ha_docs/check_anchors.py --reap \
        --log-level "${LOG_LEVEL}" "${REPO_DIR}"
}

start_entity_update_watcher() {
    if [ "${REPORT_DOC_LINK_REPAIRS}" != "true" ] || [ "${WATCH_ENTITY_UPDATES}" != "true" ]; then
        log_info "Targeted entity-update Docs-link checks are disabled"
        return 0
    fi
    local base
    if ! base=$(github_blob_base); then
        log_warning "Targeted entity-update Docs-link checks require a GitHub repository URL"
        return 1
    fi
    log_info "Starting targeted automation/script Docs-link watcher: debounce=${ENTITY_UPDATE_DEBOUNCE}s"
    HA_DOCS_REPO_DIR="${REPO_DIR}" \
        HA_DOCS_GITHUB_BASE="${base}" \
        HA_DOC_LINK_AUDIT="${DOC_LINK_AUDIT}" \
        HA_DOCS_READY_FILE="${DOC_LINK_READY}" \
        HA_DOCS_LOG_LEVEL="${LOG_LEVEL}" \
        HA_DOCS_ENTITY_DEBOUNCE="${ENTITY_UPDATE_DEBOUNCE}" \
        HA_DOCS_SCAN_CONCURRENCY="${REPAIR_SCAN_CONCURRENCY}" \
        HA_DOCS_PROGRESS_INTERVAL="${REPAIR_PROGRESS_INTERVAL}" \
        HA_DOCS_HEARTBEAT_INTERVAL="${REPAIR_SCAN_HEARTBEAT_INTERVAL}" \
        python3 /opt/ha_docs/entity_watch.py &
    ENTITY_WATCHER_PID=$!
}

# One pull + conditional rebuild. Returns non-zero only on hard failure.
refresh() {
    local reason=$1 started_at=$SECONDS
    log_info "Refresh worker started: reason=${reason}"

    # First, and deliberately outside everything below it. A full scan only
    # visits entities that still exist, so an issue belonging to a deleted one
    # is invisible to every other path here. Ahead of sync_repo because it does
    # not depend on the docs: a site frozen by a broken anchor returns early
    # further down, and must not take the cleanup of stale Repairs with it.
    if ! reap_orphan_doc_link_repairs; then
        log_warning "Orphaned Docs-link Repair sweep failed"
    fi

    if ! sync_repo; then
        log_warning "Repository sync failed; continuing to serve the current site"
        return 1
    fi

    # Source validation is cheap and always runs.  The full HA reconciliation
    # below runs only at startup or when the source/builder changed; ordinary
    # entity updates are handled one-at-a-time by entity_watch.py.
    # A failed source check is the one failure a reader cannot see from the
    # site, because it is the site that stops updating. Report it the same way
    # the entity scan reports: a Repairs issue that clears itself, plus one
    # push on the way in.
    local source_args=(--source --log-level "${LOG_LEVEL}")
    if [ "${REPORT_DOC_LINK_REPAIRS}" = "true" ]; then
        source_args+=(--report)
        if [ -n "${NOTIFY_SERVICE}" ]; then
            source_args+=(--notify-service "${NOTIFY_SERVICE}")
        fi
    fi
    if ! python3 /opt/ha_docs/check_anchors.py "${source_args[@]}" "${REPO_DIR}"; then
        log_error "Source anchor check failed; continuing to serve the current site"
        return 1
    fi
    touch "${DOC_LINK_READY}"

    local sha stamp previous build_time source_changed=false
    sha=$(git -C "${REPO_DIR}" rev-parse HEAD)
    stamp="${sha} ${BUILDER_ID}"
    previous=$(cat "${STAMP_FILE}" 2>/dev/null || true)

    if [ "${stamp}" = "${previous}" ] && [ -d "${SITE_DIR}" ]; then
        log_debug "Docs source unchanged: commit=${sha:0:7}"
    else
        source_changed=true
        log_info "Building docs: commit=${sha:0:7} builder=${BUILDER_ID:0:7}"
        # Rendered into the site footer by mkdocs.yml, so a reader can tell which
        # commit they are looking at without opening this log.
        build_time=$(date '+%Y-%m-%d %H:%M')
        DOCS_BUILD_STAMP="commit ${sha:0:7} - built ${build_time}"
        export DOCS_BUILD_STAMP
        if build_site; then
            echo "${stamp}" > "${STAMP_FILE}"
            log_info "Docs site published: commit=${sha:0:7}"
        else
            log_error "MkDocs build failed; continuing to serve the previous site"
            return 1
        fi
    fi

    if [ "${reason}" != "startup-skipped" ]; then
        if [ "${reason}" = "startup" ] || [ "${source_changed}" = "true" ]; then
            if ! reconcile_ha_docs_links; then
                log_error "HA Docs-link Repair scan completed with failures"
                return 1
            fi
        else
            log_debug "HA Docs-link Repair full scan skipped: source unchanged; targeted watcher is active"
        fi
    else
        log_info "HA Docs-link Repair scan skipped by repair_scan_on_start=false"
    fi
    log_info "Refresh worker completed: reason=${reason} elapsed_seconds=$((SECONDS - started_at))"
}

# nginx needs something to serve even if the very first build failed. The page
# reloads itself, because a first-ever start otherwise leaves the reader looking
# at a dead page they have to remember to come back to.
if [ ! -d "${SITE_DIR}" ]; then
    mkdir -p "${SITE_DIR}"
    cat > "${SITE_DIR}/index.html" <<'HTML'
<!doctype html>
<meta charset="utf-8">
<meta http-equiv="refresh" content="10">
<title>HA Docs</title>
<h1>HA Docs</h1>
<p>Initial documentation sync is in progress. This page refreshes itself; check
the add-on log for status.</p>
HTML
fi

# A request left behind by a previous run would otherwise fire a pointless
# refresh the first time round the loop.
rm -f "${SYNC_REQUEST}"

# Highlights and notes live in /data, never in the docs repo - the add-on still
# only ever pulls. Start all ingress services before network and API work.
log_info "HA Docs starting: source=${REPO} branch=${BRANCH} poll_interval=${INTERVAL}s"
log_info "Starting annotation store"
python3 /opt/ha_docs/annotations.py &
readonly ANNO_PID=$!

log_info "Starting nginx on port 8099"
nginx &
readonly NGINX_PID=$!

# Sleep out the poll interval in slices rather than in one go, so a sync asked
# for from the site is picked up within seconds instead of waiting out whatever
# is left of poll_interval - which defaults to 15 minutes.
#
# Returns 0 when a sync was requested, 1 when the interval simply elapsed.
readonly SYNC_SLICE=5
wait_for_next_poll() {
    local waited=0
    while [ "${waited}" -lt "${INTERVAL}" ]; do
        if [ -f "${SYNC_REQUEST}" ]; then
            rm -f "${SYNC_REQUEST}"
            return 0
        fi
        sleep "${SYNC_SLICE}"
        waited=$((waited + SYNC_SLICE))
    done
    return 1
}

refresh_worker() {
    local initial_reason=startup
    if [ "${REPAIR_SCAN_ON_START}" != "true" ]; then
        initial_reason=startup-skipped
    fi
    refresh "${initial_reason}" || log_warning "Refresh worker failed: reason=${initial_reason}"
    date +%s > "${REFRESH_MARKER}"
    while true; do
        local reason=poll
        if wait_for_next_poll; then
            reason=sync-request
            log_info "Sync requested from the docs site"
        fi
        refresh "${reason}" || log_warning "Refresh worker failed: reason=${reason}"
        # Always, success or failure. The Sync button watches this to know the
        # worker has finished looking, and would otherwise sit out its whole
        # timeout every time a pull turned up nothing.
        date +%s > "${REFRESH_MARKER}"
    done
}

log_info "Starting background refresh and Docs-link Repair worker"
refresh_worker &
readonly WORKER_PID=$!
ENTITY_WATCHER_PID=""
start_entity_update_watcher || log_warning "Targeted entity-update Docs-link watcher did not start"

trap 'kill "${WORKER_PID}" "${NGINX_PID}" "${ANNO_PID}" ${ENTITY_WATCHER_PID:+"${ENTITY_WATCHER_PID}"} 2>/dev/null; exit 0' SIGTERM SIGINT

wait "${WORKER_PID}"

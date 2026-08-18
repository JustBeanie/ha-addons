#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -Eeuo pipefail

umask 077

readonly APP_DIR="/opt/bacnet-mqtt-gateway"
readonly CONFIG_ROOT="/config"
readonly DATA_ROOT="/data"
readonly INGRESS_SOURCE="172.30.32.2"

optional_config() {
    local key="${1}"

    if bashio::config.has_value "${key}"; then
        bashio::config "${key}"
    fi
}

validate_relative_path() {
    local value="${1}"
    local label="${2}"

    if [[ -z "${value}" || "${value}" == /* ]]; then
        bashio::exit.nok "${label} must be a non-empty path relative to the app configuration directory"
    fi

    if [[ "/${value}/" == *"/../"* || "/${value}/" == *"/./"* ]]; then
        bashio::exit.nok "${label} must not contain '.' or '..' path components"
    fi
}

resolve_config_file() {
    local key="${1}"
    local relative_path
    local resolved_path

    relative_path="$(optional_config "${key}")"
    if [[ -z "${relative_path}" ]]; then
        return 0
    fi

    validate_relative_path "${relative_path}" "${key}"

    if [[ ! -f "${CONFIG_ROOT}/${relative_path}" || ! -r "${CONFIG_ROOT}/${relative_path}" ]]; then
        bashio::exit.nok "${key} does not identify a readable file below ${CONFIG_ROOT}"
    fi

    resolved_path="$(readlink -f "${CONFIG_ROOT}/${relative_path}")"
    if [[ "${resolved_path}" != "${CONFIG_ROOT}/"* ]]; then
        bashio::exit.nok "${key} resolves outside ${CONFIG_ROOT}"
    fi

    printf '%s' "${resolved_path}"
}

mqtt_service_value() {
    local key="${1}"
    local value

    if ! value="$(bashio::services mqtt "${key}")"; then
        bashio::exit.nok "Unable to read '${key}' from the Supervisor MQTT service"
    fi

    printf '%s' "${value}"
}

configure_mqtt() {
    local mode
    local service
    local service_ssl
    local ca_path
    local cert_path
    local key_path

    mode="$(bashio::config mqtt_mode)"
    export MQTT_GATEWAY_ID="$(bashio::config mqtt_gateway_id)"

    case "${mode}" in
        supervisor)
            service="$(bashio::services mqtt 2>/dev/null || true)"
            if ! bashio::var.has_value "${service}" || [[ "${service}" == "null" ]]; then
                bashio::exit.nok \
                    "No Supervisor MQTT service is available. Install/configure an MQTT broker app or select external mode."
            fi

            export MQTT_HOST="$(mqtt_service_value host)"
            export MQTT_PORT="$(mqtt_service_value port)"
            export MQTT_USERNAME="$(mqtt_service_value username)"
            export MQTT_PASSWORD="$(mqtt_service_value password)"
            service_ssl="$(mqtt_service_value ssl)"
            if bashio::var.true "${service_ssl}"; then
                export MQTT_TLS_ENABLED=true
            else
                export MQTT_TLS_ENABLED=false
            fi
            bashio::log.info "Using the Supervisor MQTT service at ${MQTT_HOST}:${MQTT_PORT}"
            ;;
        external)
            export MQTT_HOST="$(optional_config mqtt_external_host)"
            if [[ -z "${MQTT_HOST//[[:space:]]/}" ]]; then
                bashio::exit.nok "mqtt_external_host is required when mqtt_mode is external"
            fi

            export MQTT_PORT="$(bashio::config mqtt_external_port)"
            export MQTT_USERNAME="$(optional_config mqtt_external_username)"
            export MQTT_PASSWORD="$(optional_config mqtt_external_password)"
            if bashio::config.true mqtt_tls; then
                export MQTT_TLS_ENABLED=true
            else
                export MQTT_TLS_ENABLED=false
            fi
            bashio::log.info "Using the external MQTT broker at ${MQTT_HOST}:${MQTT_PORT}"
            ;;
        *)
            bashio::exit.nok "Unsupported mqtt_mode: ${mode}"
            ;;
    esac

    if bashio::config.true mqtt_tls_verify; then
        export MQTT_TLS_REJECT_UNAUTHORIZED=true
    else
        export MQTT_TLS_REJECT_UNAUTHORIZED=false
        bashio::log.warning "MQTT TLS certificate verification is disabled"
    fi

    ca_path="$(resolve_config_file mqtt_tls_ca_file)"
    cert_path="$(resolve_config_file mqtt_tls_cert_file)"
    key_path="$(resolve_config_file mqtt_tls_key_file)"

    if [[ -n "${cert_path}" && -z "${key_path}" ]] || [[ -z "${cert_path}" && -n "${key_path}" ]]; then
        bashio::exit.nok "mqtt_tls_cert_file and mqtt_tls_key_file must be configured together"
    fi

    if [[ "${MQTT_TLS_ENABLED}" != "true" && ( -n "${ca_path}" || -n "${cert_path}" || -n "${key_path}" ) ]]; then
        bashio::exit.nok "MQTT TLS files were configured, but TLS is not enabled"
    fi

    export MQTT_TLS_CA_PATH="${ca_path}"
    export MQTT_TLS_CERT_PATH="${cert_path}"
    export MQTT_TLS_KEY_PATH="${key_path}"
}

configure_bacnet() {
    local relative_directory
    local config_directory

    relative_directory="$(bashio::config bacnet_config_directory)"
    validate_relative_path "${relative_directory}" "bacnet_config_directory"
    config_directory="${CONFIG_ROOT}/${relative_directory}"
    mkdir -p "${config_directory}"
    config_directory="$(readlink -f "${config_directory}")"

    if [[ "${config_directory}" != "${CONFIG_ROOT}/"* ]]; then
        bashio::exit.nok "bacnet_config_directory resolves outside ${CONFIG_ROOT}"
    fi

    export BACNET_CONFIG_FOLDER="${config_directory%/}/"
    export BACNET_INTERFACE="$(bashio::config bacnet_interface)"
    export BACNET_BROADCAST_ADDRESS="$(bashio::config bacnet_broadcast_address)"
    export BACNET_PORT="$(bashio::config bacnet_port)"
    export BACNET_APDU_TIMEOUT="$(bashio::config bacnet_apdu_timeout)"
    export BACNET_MAX_SEGMENTS="$(bashio::config bacnet_max_segments)"
    export BACNET_MAX_APDU="$(bashio::config bacnet_max_apdu)"
}

configure_polling() {
    export POLLING_GLOBAL_CONCURRENCY="$(bashio::config polling_global_concurrency)"
    export POLLING_OBJECT_CONCURRENCY="$(bashio::config polling_object_concurrency)"
    export POLLING_SCHEDULER_TICK_MS="$(bashio::config polling_scheduler_tick_ms)"
    export POLLING_DEFAULT_FRESHNESS_MS="$(bashio::config polling_default_freshness_ms)"
    export POLLING_FAILURE_THRESHOLD="$(bashio::config polling_failure_threshold)"
    export POLLING_BASE_BACKOFF_MS="$(bashio::config polling_base_backoff_ms)"
    export POLLING_MAX_BACKOFF_MS="$(bashio::config polling_max_backoff_ms)"
}

configure_runtime() {
    local secret_file="${DATA_ROOT}/jwt-secret"
    local temporary_secret

    mkdir -p "${DATA_ROOT}"
    if [[ ! -s "${secret_file}" ]]; then
        temporary_secret="$(mktemp "${DATA_ROOT}/.jwt-secret.XXXXXX")"
        if ! node -e "process.stdout.write(require('crypto').randomBytes(48).toString('base64url'))" > "${temporary_secret}"; then
            rm -f "${temporary_secret}"
            bashio::exit.nok "Unable to generate the persistent application secret"
        fi
        chmod 0600 "${temporary_secret}"
        mv -f "${temporary_secret}" "${secret_file}"
    fi

    export AUTH_DB_PATH="${DATA_ROOT}/auth.db"
    export AUTH_JWT_SECRET="$(<"${secret_file}")"
    export AUTH_TOKEN_EXPIRES_IN="1h"
    export AUTH_TRUST_INGRESS=true
    export AUTH_INGRESS_SOURCE="${INGRESS_SOURCE}"
    export RUNTIME_DB_PATH="${DATA_ROOT}/runtime.db"
    export HTTP_PORT=18082
    export OPENAPI_SERVER_URL="../"
    export LOG_LEVEL="$(bashio::config log_level)"
}

configure_mqtt
configure_bacnet
configure_polling
configure_runtime

bashio::log.info "Starting BACnet MQTT Gateway ${APP_VERSION:-unknown}"
cd "${APP_DIR}"
exec node src/app.js

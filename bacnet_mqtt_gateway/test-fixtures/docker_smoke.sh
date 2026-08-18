#!/bin/sh
set -eu

app_root="${1:?usage: docker_smoke.sh APP_ROOT}"
app_image="local/bacnet-mqtt-gateway:amd64"
app_container="codex-bacnet-smoke-20260810"
supervisor_container="codex-supervisor-mock-20260810"
mqtt_container="codex-mqtt-smoke-20260810"

cleanup() {
    docker stop --timeout 15 \
        "${app_container}" "${supervisor_container}" "${mqtt_container}" \
        >/dev/null 2>&1 || true
    docker rm \
        "${app_container}" "${supervisor_container}" "${mqtt_container}" \
        >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM
cleanup

docker run --detach --name "${mqtt_container}" --network host \
    --mount "type=bind,source=${app_root}/test-fixtures/mosquitto.conf,target=/mosquitto/config/mosquitto.conf,readonly" \
    eclipse-mosquitto:2 >/dev/null

docker run --detach --name "${supervisor_container}" --network host \
    --entrypoint node \
    --mount "type=bind,source=${app_root}/test-fixtures/mock_supervisor.js,target=/tmp/mock_supervisor.js,readonly" \
    --mount "type=bind,source=${app_root}/__tests__/fixtures/options.supervisor.json,target=/tmp/options.supervisor.json,readonly" \
    --mount "type=bind,source=${app_root}/__tests__/fixtures/service.mqtt.json,target=/tmp/service.mqtt.json,readonly" \
    "${app_image}" /tmp/mock_supervisor.js /tmp/options.supervisor.json 18083 /tmp/service.mqtt.json \
    >/dev/null

docker run --detach --name "${app_container}" --network host \
    --env SUPERVISOR_API=http://127.0.0.1:18083 \
    --env SUPERVISOR_TOKEN=smoke-test \
    "${app_image}" >/dev/null

attempt=0
while [ "${attempt}" -lt 30 ]; do
    health="$(docker exec "${app_container}" wget -qO- http://127.0.0.1:18082/health 2>/dev/null || true)"
    if printf '%s' "${health}" | grep -q '"status":"ok"'; then
        if docker logs "${app_container}" 2>&1 | grep -q 'redacted-test-password'; then
            echo "App logs exposed the test MQTT password" >&2
            exit 1
        fi
        printf '%s\n' "${health}"
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 1
done

docker logs "${app_container}" >&2 || true
echo "App did not become healthy within 30 seconds" >&2
exit 1

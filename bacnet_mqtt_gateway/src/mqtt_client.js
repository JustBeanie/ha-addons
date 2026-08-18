const mqtt = require('mqtt');
const config = require('config');
const fs = require('fs');
const EventEmitter = require('events');
const { logger } = require('./common');
const { version: appVersion } = require('../package.json');

const gatewayId = config.get('mqtt.gatewayId');
const host = config.get('mqtt.host');
const port = config.get('mqtt.port');
const username = config.get('mqtt.username');
const password = config.get('mqtt.password');
const tlsConfigRaw = config.has('mqtt.tls') ? config.get('mqtt.tls') : {};
const tlsConfig = {
    enabled: tlsConfigRaw.enabled === true || tlsConfigRaw.enabled === 'true',
    caPath: tlsConfigRaw.caPath,
    certPath: tlsConfigRaw.certPath,
    keyPath: tlsConfigRaw.keyPath,
    rejectUnauthorized: typeof tlsConfigRaw.rejectUnauthorized === 'string'
        ? tlsConfigRaw.rejectUnauthorized !== 'false'
        : tlsConfigRaw.rejectUnauthorized
};

const BACNET_UNITS = new Map([
    [3, 'A'],
    [5, 'V'],
    [18, 'Wh'],
    [19, 'kWh'],
    [27, 'Hz'],
    [29, '%'],
    [31, 'm'],
    [33, 'ft'],
    [47, 'W'],
    [48, 'kW'],
    [53, 'Pa'],
    [54, 'kPa'],
    [55, 'bar'],
    [62, '°C'],
    [64, '°F'],
    [71, 'h'],
    [72, 'min'],
    [73, 's'],
    [74, 'm/s'],
    [77, 'ft/min'],
    [84, 'ft³/min'],
    [85, 'm³/s'],
    [135, 'm³/h']
]);

const BINARY_OBJECT_TYPES = new Set([3, 4, 5, 55]);
const MEASUREMENT_OBJECT_TYPES = new Set([0, 1, 2, 12, 18, 23, 24, 46, 54]);
const MAX_PENDING_PUBLISHES = 5000;

function sanitizeTopicSegment(value) {
    return String(value)
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '_')
        .replace(/^_+|_+$/g, '') || 'unknown';
}

class MqttClient extends EventEmitter {
    constructor() {
        super();

        this.connected = false;
        this.closing = false;
        this.lastError = null;
        this.publishSuccessCount = 0;
        this.publishFailureCount = 0;
        this.lastPublishedAt = null;
        this.lastErrorLoggedAt = 0;
        this.lastLoggedError = null;
        this.discoveryPayloads = new Map();
        this.pendingPublishes = new Map();
        this.droppedPublishCount = 0;
        this.availabilityTopic = `bacnet-gateway/${gatewayId}/status`;

        const options = {
            host,
            port,
            protocol: tlsConfig.enabled ? 'mqtts' : 'mqtt',
            username,
            password,
            clientId: `bacnet-mqtt-${sanitizeTopicSegment(gatewayId)}`,
            reconnectPeriod: 5000,
            connectTimeout: 30000,
            queueQoSZero: false,
            will: {
                topic: this.availabilityTopic,
                payload: 'offline',
                qos: 1,
                retain: true
            }
        };

        this._applyTlsOptions(options);
        this.client = mqtt.connect(options);

        this.client.on('connect', () => this._onConnect());
        this.client.on('message', (topic, message) => this._onMessage(topic, message));
        this.client.on('error', (error) => {
            this.lastError = error.message;
            this.connected = false;
            if (this.closing) {
                return;
            }
            const now = Date.now();
            if (this.lastLoggedError !== error.message || now - this.lastErrorLoggedAt >= 30000) {
                logger.log('error', `[MQTT] Connection error: ${error.message}`);
                this.lastLoggedError = error.message;
                this.lastErrorLoggedAt = now;
            }
        });
        this.client.on('close', () => {
            this.connected = false;
        });
        this.client.on('offline', () => {
            this.connected = false;
        });
        this.client.on('reconnect', () => {
            this.connected = false;
        });
    }

    _applyTlsOptions(options) {
        if (!tlsConfig.enabled) {
            return;
        }

        const maybeRead = (filePath) => {
            try {
                if (filePath) {
                    return fs.readFileSync(filePath);
                }
            } catch (err) {
                logger.log('error', `[MQTT] Failed to read TLS file '${filePath}': ${err.message}`);
            }
            return undefined;
        };

        options.ca = maybeRead(tlsConfig.caPath);
        options.key = maybeRead(tlsConfig.keyPath);
        options.cert = maybeRead(tlsConfig.certPath);
        if (typeof tlsConfig.rejectUnauthorized === 'boolean') {
            options.rejectUnauthorized = tlsConfig.rejectUnauthorized;
        }
    }

    _onConnect() {
        if (this.closing) {
            return;
        }

        this.connected = true;
        this.lastError = null;
        this.lastLoggedError = null;
        this.lastErrorLoggedAt = 0;
        const writeTopicPattern = `bacnetwrite/${gatewayId}/+/+/+/set`;
        this.client.subscribe(writeTopicPattern, { qos: 1 }, (err) => {
            if (err) {
                logger.log('error', `[MQTT] Error subscribing to write topic pattern ${writeTopicPattern}: ${err}`);
            }
        });

        this._publish(this.availabilityTopic, 'online', { qos: 1, retain: true });
        for (const [topic, payload] of this.discoveryPayloads.entries()) {
            this._publish(topic, payload, { qos: 1, retain: true });
        }

        const pending = Array.from(this.pendingPublishes.entries());
        this.pendingPublishes.clear();
        for (const [topic, entry] of pending) {
            if (topic !== this.availabilityTopic && !this.discoveryPayloads.has(topic)) {
                this._publish(topic, entry.message, entry.options);
            }
        }
    }

    _onMessage(topic, message) {
        const topicParts = topic.split('/');
        if (topicParts.length !== 6 || topicParts[0] !== 'bacnetwrite' || topicParts[5] !== 'set') {
            return;
        }

        const receivedGatewayId = topicParts[1];
        const deviceIdFromTopic = topicParts[2];
        const objectKey = topicParts[3];
        const propertyIdFromTopicStr = topicParts[4];

        if (receivedGatewayId !== gatewayId) {
            logger.log('warn', `[MQTT Write] Received write command for wrong gatewayId. Expected ${gatewayId}, got ${receivedGatewayId}. Ignoring.`);
            return;
        }

        const objectIdParts = objectKey.split('_');
        if (objectIdParts.length !== 2) {
            logger.log('warn', `[MQTT Write] Malformed objectKey in topic ${topic}: ${objectKey}. Expected type_instance.`);
            return;
        }

        const objectType = parseInt(objectIdParts[0], 10);
        const objectInstance = parseInt(objectIdParts[1], 10);
        const propertyIdFromTopic = parseInt(propertyIdFromTopicStr, 10);

        if (isNaN(objectType) || isNaN(objectInstance) || isNaN(propertyIdFromTopic)) {
            logger.log('warn', `[MQTT Write] Invalid objectType, objectInstance, or propertyId in topic ${topic}. Parts: type=${objectType}, instance=${objectInstance}, propId=${propertyIdFromTopic}`);
            return;
        }

        let payload;
        try {
            payload = JSON.parse(message.toString());
        } catch (_e) {
            payload = { value: message.toString() };
        }

        if (payload.value === undefined) {
            logger.log('warn', `[MQTT Write] No 'value' field in JSON payload for topic ${topic}.`);
            return;
        }

        this.emit('bacnetWriteCommand', {
            deviceId: deviceIdFromTopic,
            objectKey,
            objectType,
            objectInstance,
            propertyId: propertyIdFromTopic,
            value: payload.value,
            priority: payload.priority,
            bacnetApplicationTag: payload.bacnetApplicationTag
        });
    }

    _publish(topic, message, options = {}) {
        if (!this.connected && !this.closing) {
            if (!this.pendingPublishes.has(topic) && this.pendingPublishes.size >= MAX_PENDING_PUBLISHES) {
                const oldestTopic = this.pendingPublishes.keys().next().value;
                this.pendingPublishes.delete(oldestTopic);
                this.droppedPublishCount += 1;
                logger.log('warn', `[MQTT] Offline publish buffer full; dropped oldest topic ${oldestTopic}.`);
            }
            this.pendingPublishes.delete(topic);
            this.pendingPublishes.set(topic, { message, options: { ...options } });
            return;
        }

        this.client.publish(topic, message, options, (err) => {
            if (err) {
                this.publishFailureCount += 1;
                this.lastError = err.message || String(err);
                logger.log('error', `[MQTT] Publish failed for ${topic}: ${this.lastError}`);
                return;
            }
            this.publishSuccessCount += 1;
            this.lastPublishedAt = Date.now();
        });
    }

    _getHaComponentType(objectKey) {
        const bacnetObjectType = Number(objectKey.split('_')[0]);
        if (BINARY_OBJECT_TYPES.has(bacnetObjectType)) {
            return 'binary_sensor';
        }
        return 'sensor';
    }

    _buildDiscovery(component, entityKey, objectKey, telemetry, stateTopic, attributesTopic) {
        const deviceId = String(telemetry.deviceId);
        const uniqueId = sanitizeTopicSegment(`${gatewayId}_${deviceId}_${objectKey}`);
        const payload = {
            name: telemetry.name || `BACnet ${objectKey}`,
            object_id: uniqueId,
            unique_id: uniqueId,
            state_topic: stateTopic,
            json_attributes_topic: attributesTopic,
            availability_topic: this.availabilityTopic,
            payload_available: 'online',
            payload_not_available: 'offline',
            device: {
                identifiers: [`${gatewayId}_${deviceId}`],
                name: `BACnet Device ${deviceId}`,
                manufacturer: 'BACnet',
                model: 'BACnet/IP device'
            },
            origin: {
                name: 'BACnet MQTT Gateway',
                sw_version: appVersion,
                support_url: 'https://github.com/JustBeanie/ha-addons'
            }
        };

        const freshnessMs = Number(telemetry.freshnessMs);
        if (Number.isFinite(freshnessMs) && freshnessMs > 0) {
            payload.expire_after = Math.max(1, Math.ceil(freshnessMs / 1000));
        }

        if (component === 'binary_sensor') {
            payload.payload_on = 'ON';
            payload.payload_off = 'OFF';
        } else {
            const unit = BACNET_UNITS.get(Number(telemetry.units));
            if (unit) {
                payload.unit_of_measurement = unit;
            }
            const objectType = Number(objectKey.split('_')[0]);
            if (typeof telemetry.value === 'number' && MEASUREMENT_OBJECT_TYPES.has(objectType)) {
                payload.state_class = 'measurement';
            }
        }

        const topic = `homeassistant/${component}/${sanitizeTopicSegment(gatewayId)}/${entityKey}/config`;
        return { topic, payload: JSON.stringify(payload) };
    }

    _normalizeState(component, value) {
        if (component === 'binary_sensor') {
            const active = value === true || value === 1 || value === '1' || String(value).toLowerCase() === 'active' || String(value).toLowerCase() === 'on';
            return active ? 'ON' : 'OFF';
        }
        if (value === null || value === undefined) {
            return 'unknown';
        }
        return typeof value === 'object' ? JSON.stringify(value) : String(value);
    }

    _publishTelemetryMap(telemetryMap) {
        for (const [objectKey, telemetry] of Object.entries(telemetryMap)) {
            const component = this._getHaComponentType(objectKey);
            const deviceSegment = sanitizeTopicSegment(telemetry.deviceId);
            const entityKey = sanitizeTopicSegment(`${deviceSegment}_${objectKey}`);
            const stateTopic = `bacnet-gateway/${gatewayId}/entities/${entityKey}/state`;
            const attributesTopic = `bacnet-gateway/${gatewayId}/entities/${entityKey}/attributes`;
            const canonicalTopic = `bacnet-gateway/${gatewayId}/telemetry/${telemetry.deviceId}/${objectKey}`;
            const discovery = this._buildDiscovery(component, entityKey, objectKey, telemetry, stateTopic, attributesTopic);
            const priorDiscovery = this.discoveryPayloads.get(discovery.topic);

            if (priorDiscovery !== discovery.payload) {
                this.discoveryPayloads.set(discovery.topic, discovery.payload);
                this._publish(discovery.topic, discovery.payload, { qos: 1, retain: true });
            }

            this._publish(stateTopic, this._normalizeState(component, telemetry.value), { qos: 1, retain: true });
            this._publish(attributesTopic, JSON.stringify({
                name: telemetry.name,
                deviceId: telemetry.deviceId,
                address: telemetry.address,
                units: telemetry.units,
                acquiredAt: telemetry.acquiredAt,
                publishedAt: telemetry.publishedAt,
                freshnessMs: telemetry.freshnessMs,
                sourceStatus: telemetry.sourceStatus,
                pollDurationMs: telemetry.pollDurationMs,
                pollClass: telemetry.pollClass
            }), { qos: 1, retain: true });
            this._publish(canonicalTopic, JSON.stringify(telemetry), { qos: 1, retain: true });
        }
    }

    publishMessage(messageJson) {
        if (messageJson && typeof messageJson === 'object' && !Array.isArray(messageJson)) {
            const keys = Object.keys(messageJson);
            const looksLikeTelemetryMap = keys.length > 0 && keys.every((key) => {
                const value = messageJson[key];
                return value && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, 'value');
            });

            if (looksLikeTelemetryMap) {
                this._publishTelemetryMap(messageJson);
                return;
            }

            if (typeof messageJson.deviceId !== 'undefined' && typeof messageJson.address !== 'undefined') {
                const topic = `bacnet-gateway/${gatewayId}/device_found/${messageJson.deviceId}`;
                this._publish(topic, JSON.stringify(messageJson), { qos: 1, retain: true });
                return;
            }
        }

        if (JSON.stringify(messageJson) === '{}') {
            logger.log('warn', '[MQTT] Received empty object to publish. Skipping.');
            return;
        }

        logger.log('warn', '[MQTT] Unknown message structure. Publishing to default/error topic.');
        this._publish(`bacnet-gateway/${gatewayId}/unknown_data`, JSON.stringify(messageJson), { qos: 1 });
    }

    publishWriteStatus(topic, status) {
        const expectedPrefix = `bacnetwrite_status/${gatewayId}/`;
        if (typeof topic !== 'string' || !topic.startsWith(expectedPrefix)) {
            throw new Error('Invalid BACnet write status topic');
        }
        this._publish(topic, JSON.stringify(status), { qos: 1 });
    }

    close() {
        if (this.closing) {
            return Promise.resolve();
        }
        this.closing = true;

        return new Promise((resolve) => {
            let ended = false;
            const endClient = () => {
                if (ended) {
                    return;
                }
                ended = true;
                this.connected = false;
                if (!this.client || typeof this.client.end !== 'function') {
                    resolve();
                    return;
                }
                this.client.end(false, {}, resolve);
            };

            if (!this.connected || !this.client || typeof this.client.publish !== 'function') {
                endClient();
                return;
            }

            this.client.publish(this.availabilityTopic, 'offline', { qos: 1, retain: true }, endClient);
        });
    }

    getStatus() {
        return {
            connected: this.connected,
            lastError: this.lastError,
            publishSuccessCount: this.publishSuccessCount,
            publishFailureCount: this.publishFailureCount,
            pendingPublishCount: this.pendingPublishes.size,
            droppedPublishCount: this.droppedPublishCount,
            lastPublishedAt: this.lastPublishedAt
        };
    }
}

module.exports = { MqttClient, sanitizeTopicSegment };

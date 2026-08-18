jest.mock('mqtt', () => {
    const { EventEmitter } = require('events');
    const publishMock = jest.fn((topic, message, options, cb) => {
        if (typeof options === 'function') {
            options();
        } else if (typeof cb === 'function') {
            cb();
        }
    });
    const subscribeMock = jest.fn((pattern, options, cb) => {
        if (typeof options === 'function') {
            options();
        } else if (typeof cb === 'function') {
            cb();
        }
    });
    const endMock = jest.fn((force, options, cb) => cb && cb());
    let clientInstance;
    return {
        __getMocks: () => ({
            publishMock,
            subscribeMock,
            endMock,
            get clientInstance() {
                return clientInstance;
            }
        }),
        connect: jest.fn(() => {
            clientInstance = new EventEmitter();
            clientInstance.publish = publishMock;
            clientInstance.subscribe = subscribeMock;
            clientInstance.end = endMock;
            return clientInstance;
        })
    };
});

jest.mock('../src/common', () => ({
    logger: { log: jest.fn() }
}));

describe('MqttClient', () => {
    const originalEnv = { ...process.env };
    let mqttMocks;

    beforeEach(() => {
        jest.clearAllMocks();
        process.env.NODE_CONFIG = JSON.stringify({
            mqtt: { gatewayId: 'test-gw', host: 'localhost', port: 1883, username: 'u', password: 'p' }
        });
        process.env.NODE_CONFIG_STRICT_MODE = '0';
        process.env.NODE_ENV = 'development';
        jest.resetModules();
        mqttMocks = require('mqtt').__getMocks();
    });

    afterEach(() => {
        Object.keys(process.env).forEach((k) => {
            if (!(k in originalEnv)) delete process.env[k];
        });
        Object.entries(originalEnv).forEach(([k, v]) => (process.env[k] = v));
        jest.resetModules();
    });

    test('publishMessage publishes telemetry to state, attributes, and canonical topics', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        mqttMocks.publishMock.mockClear();

        client.publishMessage({
            '2_202': {
                value: 42,
                name: 'Room Temp',
                deviceId: '114',
                address: '192.168.1.10',
                acquiredAt: 1000,
                publishedAt: 1100,
                freshnessMs: 5000,
                sourceStatus: 'fresh',
                pollDurationMs: 80,
                pollClass: 'fast',
                units: 62
            }
        });

        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'homeassistant/sensor/test-gw/114_2_202/config',
            expect.stringContaining('"unique_id":"test-gw_114_2_202"'),
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/entities/114_2_202/state',
            '42',
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/entities/114_2_202/attributes',
            expect.stringContaining('"sourceStatus":"fresh"'),
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/telemetry/114/2_202',
            expect.stringContaining('"pollClass":"fast"'),
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(JSON.parse(mqttMocks.publishMock.mock.calls[0][1])).toEqual(expect.objectContaining({
            availability_topic: 'bacnet-gateway/test-gw/status',
            expire_after: 5,
            state_class: 'measurement',
            unit_of_measurement: '°C'
        }));
        expect(client.getStatus().publishSuccessCount).toBe(5);
    });

    test('publishMessage skips empty object', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        mqttMocks.publishMock.mockClear();

        client.publishMessage({});

        expect(mqttMocks.publishMock).not.toHaveBeenCalled();
    });

    test('onMessage ignores messages for other gateways', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');

        const handler = jest.fn();
        client.on('bacnetWriteCommand', handler);

        const topic = 'bacnetwrite/other-gw/114/2_202/85/set';
        mqttMocks.clientInstance.emit('message', topic, Buffer.from('{"value":1}'));

        expect(handler).not.toHaveBeenCalled();
    });

    test('onMessage emits bacnetWriteCommand for matching gateway', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');

        const handler = jest.fn();
        client.on('bacnetWriteCommand', handler);

        const topic = 'bacnetwrite/test-gw/114/1_0/85/set';
        mqttMocks.clientInstance.emit('message', topic, Buffer.from('{"value":1,"priority":8}'));

        expect(handler).toHaveBeenCalledWith({
            deviceId: '114',
            objectKey: '1_0',
            objectType: 1,
            objectInstance: 0,
            propertyId: 85,
            value: 1,
            priority: 8,
            bacnetApplicationTag: undefined
        });
    });

    test('onConnect subscribes and updates connection status', async () => {
        const mqttModule = require('mqtt');
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();

        expect(mqttModule.connect).toHaveBeenCalledWith(expect.objectContaining({
            reconnectPeriod: 5000,
            connectTimeout: 30000,
            queueQoSZero: false
        }));

        mqttMocks.clientInstance.emit('connect');

        expect(mqttMocks.subscribeMock).toHaveBeenCalledWith(
            'bacnetwrite/test-gw/+/+/+/set',
            { qos: 1 },
            expect.any(Function)
        );
        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/status',
            'online',
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(client.getStatus().connected).toBe(true);
    });

    test('onMessage ignores malformed topics and missing values', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        const handler = jest.fn();
        client.on('bacnetWriteCommand', handler);

        mqttMocks.clientInstance.emit('message', 'bacnetwrite/test-gw/114/badkey/85/set', Buffer.from('{"value":1}'));
        mqttMocks.clientInstance.emit('message', 'bacnetwrite/test-gw/114/x_0/85/set', Buffer.from('{"value":1}'));
        mqttMocks.clientInstance.emit('message', 'bacnetwrite/test-gw/114/1_0/85/set', Buffer.from('{"priority":8}'));

        expect(handler).not.toHaveBeenCalled();
    });

    test('onMessage falls back to raw message string for non-JSON payloads', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        const handler = jest.fn();
        client.on('bacnetWriteCommand', handler);

        mqttMocks.clientInstance.emit('message', 'bacnetwrite/test-gw/114/1_0/85/set', Buffer.from('plain-text'));

        expect(handler).toHaveBeenCalledWith(expect.objectContaining({
            value: 'plain-text'
        }));
    });

    test('publishMessage publishes discovered devices and unknown payloads', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');

        client.publishMessage({ deviceId: '114', address: '192.168.1.10' });
        client.publishMessage('unexpected-payload');

        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/device_found/114',
            JSON.stringify({ deviceId: '114', address: '192.168.1.10' }),
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/unknown_data',
            JSON.stringify('unexpected-payload'),
            { qos: 1 },
            expect.any(Function)
        );
    });

    test('publishWriteStatus publishes only to the configured gateway namespace', () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        mqttMocks.publishMock.mockClear();

        client.publishWriteStatus('bacnetwrite_status/test-gw/114/1_0/85', { status: 'success' });

        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnetwrite_status/test-gw/114/1_0/85',
            JSON.stringify({ status: 'success' }),
            { qos: 1 },
            expect.any(Function)
        );
        expect(() => client.publishWriteStatus('untrusted/topic', {})).toThrow('Invalid BACnet write status topic');
    });

    test('client tracks connection errors and offline lifecycle events', async () => {
        const { logger } = require('../src/common');
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();

        mqttMocks.clientInstance.emit('connect');
        mqttMocks.clientInstance.emit('error', new Error('broker down'));
        mqttMocks.clientInstance.emit('error', new Error('broker down'));
        expect(client.getStatus()).toEqual(expect.objectContaining({
            connected: false,
            lastError: 'broker down'
        }));
        expect(logger.log).toHaveBeenCalledTimes(1);

        mqttMocks.clientInstance.emit('offline');
        expect(client.getStatus().connected).toBe(false);
        mqttMocks.clientInstance.emit('reconnect');
        expect(client.getStatus().connected).toBe(false);
        mqttMocks.clientInstance.emit('close');
        expect(client.getStatus().connected).toBe(false);
    });

    test('publish tracks publish failures', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        mqttMocks.clientInstance.publish = jest.fn((topic, message, options, cb) => cb(new Error('publish failed')));

        client.publishMessage({ deviceId: '114', address: '192.168.1.10' });

        expect(client.getStatus()).toEqual(expect.objectContaining({
            publishFailureCount: 1,
            lastError: 'publish failed'
        }));
    });

    test('coalesces offline publishes by topic and flushes the latest values on reconnect', () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();

        client.publishMessage({ deviceId: '114', address: '192.168.1.10' });
        client.publishMessage({ deviceId: '114', address: '192.168.1.11' });

        expect(mqttMocks.publishMock).not.toHaveBeenCalled();
        expect(client.getStatus().pendingPublishCount).toBe(1);

        mqttMocks.clientInstance.emit('connect');

        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/device_found/114',
            JSON.stringify({ deviceId: '114', address: '192.168.1.11' }),
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(client.getStatus().pendingPublishCount).toBe(0);
    });

    test('maps binary outputs as binary sensors and leaves life-safety values discrete', () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        mqttMocks.publishMock.mockClear();

        client.publishMessage({
            '4_1': { value: 1, name: 'Relay', deviceId: '10', freshnessMs: 2500 },
            '21_1': { value: 3, name: 'Life safety', deviceId: '10', freshnessMs: 2500 }
        });

        const binaryDiscovery = mqttMocks.publishMock.mock.calls.find(([topic]) => topic.includes('/binary_sensor/'));
        const lifeSafetyDiscovery = mqttMocks.publishMock.mock.calls.find(([topic]) => topic.includes('/sensor/') && topic.endsWith('/10_21_1/config'));
        expect(JSON.parse(binaryDiscovery[1])).toEqual(expect.objectContaining({ payload_on: 'ON', expire_after: 3 }));
        expect(JSON.parse(lifeSafetyDiscovery[1])).not.toHaveProperty('state_class');
    });

    test('subscribe errors are tolerated on connect', async () => {
        mqttMocks.subscribeMock.mockImplementationOnce((pattern, options, cb) => cb(new Error('subscribe failed')));
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();

        mqttMocks.clientInstance.emit('connect');

        expect(client.getStatus().connected).toBe(true);
    });

    test('close publishes offline availability and ends the connection', async () => {
        const { MqttClient } = require('../src/mqtt_client');
        const client = new MqttClient();
        mqttMocks.clientInstance.emit('connect');
        mqttMocks.publishMock.mockClear();

        await client.close();

        expect(mqttMocks.publishMock).toHaveBeenCalledWith(
            'bacnet-gateway/test-gw/status',
            'offline',
            { qos: 1, retain: true },
            expect.any(Function)
        );
        expect(mqttMocks.endMock).toHaveBeenCalledWith(false, {}, expect.any(Function));
        expect(client.getStatus().connected).toBe(false);
    });

    test('tls options are applied from config when enabled', async () => {
        jest.doMock('fs', () => ({
            readFileSync: jest.fn((filePath) => Buffer.from(`data:${filePath}`))
        }));
        process.env.NODE_CONFIG = JSON.stringify({
            mqtt: {
                gatewayId: 'test-gw',
                host: 'localhost',
                port: 8883,
                username: 'u',
                password: 'p',
                tls: {
                    enabled: true,
                    caPath: '/tmp/ca.pem',
                    certPath: '/tmp/cert.pem',
                    keyPath: '/tmp/key.pem',
                    rejectUnauthorized: false
                }
            }
        });
        jest.resetModules();
        mqttMocks = require('mqtt').__getMocks();
        const mqttModule = require('mqtt');
        const { MqttClient } = require('../src/mqtt_client');

        new MqttClient();

        expect(mqttModule.connect).toHaveBeenCalledWith(expect.objectContaining({
            protocol: 'mqtts',
            ca: Buffer.from('data:/tmp/ca.pem'),
            cert: Buffer.from('data:/tmp/cert.pem'),
            key: Buffer.from('data:/tmp/key.pem'),
            rejectUnauthorized: false
        }));
    });
});

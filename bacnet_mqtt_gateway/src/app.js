require('dotenv').config({ quiet: true });

const { BacnetClient } = require('./bacnet_client');
const { Server } = require('./server');
const { logger } = require('./common');
const { MqttClient } = require('./mqtt_client');
const { AuthService } = require('./auth_service');
const { deliverInitialAdminPassword } = require('./bootstrap_credentials');
const config = require('config');

const DEFAULT_SHUTDOWN_TIMEOUT_MS = 10000;

function configBoolean(configProvider, path, fallback = false) {
    if (typeof configProvider.has === 'function' && !configProvider.has(path)) {
        return fallback;
    }
    const value = configProvider.get(path);
    if (typeof value === 'string') {
        return value.toLowerCase() === 'true';
    }
    return value === true;
}

function formatError(error) {
    if (error && error.stack) {
        return error.stack;
    }
    if (error && error.message) {
        return error.message;
    }
    return String(error);
}

function invokeClose(target, methodName, args = []) {
    if (!target || typeof target[methodName] !== 'function') {
        return Promise.resolve();
    }

    return new Promise((resolve, reject) => {
        const method = target[methodName];
        let settled = false;
        const done = (error) => {
            if (settled) {
                return;
            }
            settled = true;
            if (error) {
                reject(error);
            } else {
                resolve();
            }
        };

        let result;
        try {
            result = method.call(target, ...args, done);
        } catch (error) {
            done(error);
            return;
        }

        if (result && typeof result.then === 'function') {
            result.then(() => done(), done);
        } else if (method.length <= args.length) {
            done();
        }
    });
}

function createApplication(options = {}) {
    const configProvider = options.config || config;
    const appLogger = options.logger || logger;
    const MqttClientClass = options.MqttClient || MqttClient;
    const BacnetClientClass = options.BacnetClient || BacnetClient;
    const AuthServiceClass = options.AuthService || AuthService;
    const ServerClass = options.Server || Server;
    const deliverPassword = options.deliverInitialAdminPassword || deliverInitialAdminPassword;
    const shutdownTimeoutMs = Number.isFinite(options.shutdownTimeoutMs)
        ? Math.max(1, options.shutdownTimeoutMs)
        : DEFAULT_SHUTDOWN_TIMEOUT_MS;
    const httpServerEnabled = configBoolean(configProvider, 'httpServer.enabled');
    const trustIngress = configBoolean(configProvider, 'auth.trustIngress');

    // Preserve the original startup order: MQTT and BACnet begin connecting,
    // then BACnet readiness gates auth initialization and the HTTP server.
    const mqttClient = options.mqttClient || new MqttClientClass();
    const bacnetClient = options.bacnetClient || new BacnetClientClass();
    const authService = trustIngress
        ? null
        : (options.authService || new AuthServiceClass());

    let server = null;
    let shuttingDown = false;
    let shutdownPromise = null;

    bacnetClient.on('deviceFound', (device) => {
        mqttClient.publishMessage(device);
    });

    bacnetClient.on('values', (device, values) => {
        mqttClient.publishMessage(values);
    });

    mqttClient.on('bacnetWriteCommand', (command) => {
        const { deviceId, objectKey, objectType, objectInstance, propertyId, value, priority, bacnetApplicationTag } = command;
        const targetDeviceConfig = bacnetClient.deviceConfigs.get(deviceId.toString());

        if (targetDeviceConfig && targetDeviceConfig.device && targetDeviceConfig.device.address) {
            const targetDeviceAddress = targetDeviceConfig.device.address;
            const bacnetObjectId = { type: objectType, instance: objectInstance };
            // Construct status topic using the new structure elements
            // Example: bacnetwrite_status/<gatewayId>/<deviceId>/<objectKey>/<propertyId>
            const gatewayIdForTopic = configProvider.get('mqtt.gatewayId');
            const writeStatusTopic = `bacnetwrite_status/${gatewayIdForTopic}/${deviceId}/${objectKey}/${propertyId}`;

            bacnetClient.writeProperty(targetDeviceAddress, bacnetObjectId, propertyId, value, priority, bacnetApplicationTag)
                .then(response => {
                    const successMsg = `[App] BACnet write successful for DeviceID: ${deviceId}, ObjectKey: ${objectKey}, Property: ${propertyId}: ${JSON.stringify(response)} (Priority: ${priority}, AppTag: ${bacnetApplicationTag})`;

                    mqttClient.publishWriteStatus(writeStatusTopic, {
                        status: 'success', detail: successMsg, writtenValue: value
                    });
                })
                .catch(error => {
                    const errorMsg = `[App] BACnet write failed for DeviceID: ${deviceId}, ObjectKey: ${objectKey}, Property: ${propertyId}: ${error.message || error}`;
                    appLogger.log('error', errorMsg);
                    mqttClient.publishWriteStatus(writeStatusTopic, {
                        status: 'error', detail: errorMsg, attemptedValue: value
                    });
                });
        } else {
            appLogger.log('warn', `[App] Could not find a configured device for DeviceID ${deviceId} (from topic) to perform write operation for objectKey ${objectKey}.`);
            const gatewayIdForTopic = configProvider.get('mqtt.gatewayId');
            const statusTopic = `bacnetwrite_status/${gatewayIdForTopic}/${deviceId || 'unknown_device'}/${objectKey}/${propertyId || 'unknown_property'}`;
            mqttClient.publishWriteStatus(statusTopic, {
                status: 'error', detail: `Device configuration not found for DeviceID ${deviceId}`
            });
        }
    });

    async function init() {
        await bacnetClient.ready;
        if (shuttingDown) {
            return;
        }

        if (authService) {
            const seededPassword = await authService.init();
            if (seededPassword) {
                deliverPassword('admin', seededPassword);
            }
        }
        if (shuttingDown) {
            return;
        }

        if (httpServerEnabled) {
            server = new ServerClass(bacnetClient, mqttClient, authService);
        }
    }

    function closeHttpServer() {
        if (!server) {
            return Promise.resolve();
        }
        if (typeof server.close === 'function') {
            return invokeClose(server, 'close');
        }
        const httpServer = server.httpServer || server.server;
        return invokeClose(httpServer, 'close');
    }

    function closeMqttClient() {
        if (typeof mqttClient.close === 'function') {
            return invokeClose(mqttClient, 'close');
        }
        if (mqttClient.client && typeof mqttClient.client.end === 'function') {
            return invokeClose(mqttClient.client, 'end', [false, {}]);
        }
        return Promise.resolve();
    }

    function shutdown(reason = 'shutdown requested') {
        if (shutdownPromise) {
            return shutdownPromise;
        }

        shuttingDown = true;
        appLogger.log('info', `[App] Shutting down: ${reason}`);

        const closers = [
            ['HTTP server', closeHttpServer],
            ['MQTT client', closeMqttClient],
            ['BACnet client and runtime state', () => invokeClose(bacnetClient, 'close')],
            ['auth service', () => invokeClose(authService, 'close')]
        ];
        const cleanup = Promise.all(closers.map(async ([name, close]) => {
            try {
                await close();
            } catch (error) {
                appLogger.log('error', `[App] Failed to close ${name}: ${formatError(error)}`);
            }
        }));

        shutdownPromise = new Promise((resolve) => {
            let finished = false;
            const finish = () => {
                if (finished) {
                    return;
                }
                finished = true;
                clearTimeout(timeoutHandle);
                resolve();
            };
            const timeoutHandle = setTimeout(() => {
                appLogger.log('error', `[App] Shutdown timed out after ${shutdownTimeoutMs}ms`);
                finish();
            }, shutdownTimeoutMs);

            cleanup.then(() => {
                appLogger.log('info', '[App] Shutdown complete');
                finish();
            });
        });

        return shutdownPromise;
    }

    return {
        init,
        shutdown,
        mqttClient,
        bacnetClient,
        authService,
        get server() {
            return server;
        },
        get isShuttingDown() {
            return shuttingDown;
        }
    };
}

function runApplication(options = {}) {
    const processRef = options.process || process;
    const appLogger = options.logger || logger;
    const application = options.application || createApplication(options);
    let requestedExitCode = 0;
    let terminationPromise = null;

    const requestStop = (reason, exitCode = 0, error = null) => {
        requestedExitCode = Math.max(requestedExitCode, exitCode);
        processRef.exitCode = requestedExitCode;

        if (error) {
            appLogger.log('error', `[App] Fatal ${reason}: ${formatError(error)}`);
        }

        if (!terminationPromise) {
            terminationPromise = Promise.resolve()
                .then(() => application.shutdown(reason))
                .catch((shutdownError) => {
                    appLogger.log('error', `[App] Shutdown failed: ${formatError(shutdownError)}`);
                })
                .then(() => {
                    processRef.exit(requestedExitCode);
                });
        }
        return terminationPromise;
    };

    processRef.once('SIGTERM', () => {
        void requestStop('SIGTERM');
    });
    processRef.once('SIGINT', () => {
        void requestStop('SIGINT');
    });
    processRef.once('unhandledRejection', (reason) => {
        void requestStop('unhandled rejection', 1, reason);
    });
    processRef.once('uncaughtException', (error) => {
        void requestStop('uncaught exception', 1, error);
    });

    const initPromise = Promise.resolve()
        .then(() => application.init())
        .catch((error) => requestStop('initialization failure', 1, error));

    return { application, initPromise, requestStop };
}

if (require.main === module) {
    runApplication();
}

module.exports = {
    DEFAULT_SHUTDOWN_TIMEOUT_MS,
    createApplication,
    runApplication
};

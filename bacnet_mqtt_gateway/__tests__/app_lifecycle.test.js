const EventEmitter = require('events');

const { createApplication, runApplication } = require('../src/app');

function createConfig({ trustIngress = false, httpServerEnabled = true } = {}) {
    const values = {
        'auth.trustIngress': trustIngress,
        'httpServer.enabled': httpServerEnabled,
        'mqtt.gatewayId': 'test-gateway'
    };
    return {
        has: jest.fn((path) => Object.prototype.hasOwnProperty.call(values, path)),
        get: jest.fn((path) => values[path])
    };
}

function createClients() {
    const mqttClient = new EventEmitter();
    mqttClient.publishMessage = jest.fn();
    mqttClient.publishWriteStatus = jest.fn();
    mqttClient.client = {
        end: jest.fn((_force, _options, callback) => callback())
    };

    const bacnetClient = new EventEmitter();
    bacnetClient.ready = Promise.resolve();
    bacnetClient.deviceConfigs = new Map();
    bacnetClient.writeProperty = jest.fn().mockResolvedValue({ ok: true });
    bacnetClient.close = jest.fn().mockResolvedValue();

    return { mqttClient, bacnetClient };
}

function createLogger() {
    return { log: jest.fn() };
}

function createProcess() {
    const processRef = new EventEmitter();
    processRef.exit = jest.fn();
    processRef.exitCode = undefined;
    return processRef;
}

describe('application initialization and lifecycle', () => {
    test('preserves event forwarding, auth initialization, and HTTP startup', async () => {
        const { mqttClient, bacnetClient } = createClients();
        const authService = {
            init: jest.fn().mockResolvedValue('initial-password'),
            close: jest.fn().mockResolvedValue()
        };
        const httpServer = {
            close: jest.fn((callback) => callback())
        };
        const ServerClass = jest.fn(function ServerMock() {
            return httpServer;
        });
        const deliverPassword = jest.fn();
        const application = createApplication({
            config: createConfig(),
            logger: createLogger(),
            mqttClient,
            bacnetClient,
            authService,
            Server: ServerClass,
            deliverInitialAdminPassword: deliverPassword
        });

        bacnetClient.emit('deviceFound', { deviceId: 114 });
        bacnetClient.emit('values', { deviceId: 114 }, { '2_202': { value: 21.5 } });
        await application.init();

        expect(mqttClient.publishMessage).toHaveBeenNthCalledWith(1, { deviceId: 114 });
        expect(mqttClient.publishMessage).toHaveBeenNthCalledWith(2, { '2_202': { value: 21.5 } });
        expect(authService.init).toHaveBeenCalledTimes(1);
        expect(deliverPassword).toHaveBeenCalledWith('admin', 'initial-password');
        expect(ServerClass).toHaveBeenCalledWith(bacnetClient, mqttClient, authService);
        expect(application.server).toBe(httpServer);
    });

    test('trustIngress skips AuthService construction and passes null to Server', async () => {
        const { mqttClient, bacnetClient } = createClients();
        const AuthServiceClass = jest.fn();
        const ServerClass = jest.fn(function ServerMock() {
            return { close: jest.fn((callback) => callback()) };
        });
        const application = createApplication({
            config: createConfig({ trustIngress: true }),
            logger: createLogger(),
            mqttClient,
            bacnetClient,
            AuthService: AuthServiceClass,
            Server: ServerClass
        });

        await application.init();

        expect(AuthServiceClass).not.toHaveBeenCalled();
        expect(application.authService).toBeNull();
        expect(ServerClass).toHaveBeenCalledWith(bacnetClient, mqttClient, null);
        await application.shutdown('test cleanup');
    });

    test('shutdown is idempotent and closes every initialized resource', async () => {
        const { mqttClient, bacnetClient } = createClients();
        const authService = {
            init: jest.fn().mockResolvedValue(),
            close: jest.fn().mockResolvedValue()
        };
        const httpServer = {
            close: jest.fn((callback) => callback())
        };
        const ServerClass = jest.fn(function ServerMock() {
            return httpServer;
        });
        const application = createApplication({
            config: createConfig(),
            logger: createLogger(),
            mqttClient,
            bacnetClient,
            authService,
            Server: ServerClass
        });
        await application.init();

        const firstShutdown = application.shutdown('SIGTERM');
        const secondShutdown = application.shutdown('SIGINT');

        expect(secondShutdown).toBe(firstShutdown);
        await firstShutdown;
        expect(application.isShuttingDown).toBe(true);
        expect(httpServer.close).toHaveBeenCalledTimes(1);
        expect(mqttClient.client.end).toHaveBeenCalledWith(false, {}, expect.any(Function));
        expect(bacnetClient.close).toHaveBeenCalledTimes(1);
        expect(authService.close).toHaveBeenCalledTimes(1);
    });

    test('shutdown timeout resolves when a resource does not close', async () => {
        jest.useFakeTimers();
        const { mqttClient, bacnetClient } = createClients();
        const appLogger = createLogger();
        const application = createApplication({
            config: createConfig({ httpServerEnabled: false }),
            logger: appLogger,
            mqttClient,
            bacnetClient,
            authService: {
                init: jest.fn().mockResolvedValue(),
                close: jest.fn(() => new Promise(() => {}))
            },
            shutdownTimeoutMs: 50
        });
        await application.init();

        const shutdown = application.shutdown('timeout test');
        await jest.advanceTimersByTimeAsync(50);
        await shutdown;

        expect(appLogger.log).toHaveBeenCalledWith('error', '[App] Shutdown timed out after 50ms');
        expect(bacnetClient.close).toHaveBeenCalledTimes(1);
        expect(mqttClient.client.end).toHaveBeenCalledTimes(1);
        jest.useRealTimers();
    });

    test('shutdown during BACnet initialization does not start auth or HTTP', async () => {
        const { mqttClient, bacnetClient } = createClients();
        let releaseReady;
        bacnetClient.ready = new Promise((resolve) => {
            releaseReady = resolve;
        });
        const authService = {
            init: jest.fn().mockResolvedValue(),
            close: jest.fn().mockResolvedValue()
        };
        const ServerClass = jest.fn();
        const application = createApplication({
            config: createConfig(),
            logger: createLogger(),
            mqttClient,
            bacnetClient,
            authService,
            Server: ServerClass
        });

        const initialization = application.init();
        await application.shutdown('SIGTERM');
        releaseReady();
        await initialization;

        expect(authService.init).not.toHaveBeenCalled();
        expect(ServerClass).not.toHaveBeenCalled();
    });
});

describe('process lifecycle handlers', () => {
    test.each(['SIGTERM', 'SIGINT'])('%s exits cleanly after cleanup', async (signal) => {
        const processRef = createProcess();
        const application = {
            init: jest.fn().mockResolvedValue(),
            shutdown: jest.fn().mockResolvedValue()
        };
        const runner = runApplication({
            process: processRef,
            application,
            logger: createLogger()
        });
        await runner.initPromise;

        processRef.emit(signal);
        await runner.requestStop('wait for signal cleanup');

        expect(application.shutdown).toHaveBeenCalledTimes(1);
        expect(application.shutdown).toHaveBeenCalledWith(signal);
        expect(processRef.exitCode).toBe(0);
        expect(processRef.exit).toHaveBeenCalledWith(0);
        expect(application.shutdown.mock.invocationCallOrder[0])
            .toBeLessThan(processRef.exit.mock.invocationCallOrder[0]);
    });

    test.each([
        ['unhandledRejection', 'unhandled rejection'],
        ['uncaughtException', 'uncaught exception']
    ])('%s exits nonzero after cleanup', async (eventName, shutdownReason) => {
        const processRef = createProcess();
        const application = {
            init: jest.fn().mockResolvedValue(),
            shutdown: jest.fn().mockResolvedValue()
        };
        const appLogger = createLogger();
        const runner = runApplication({ process: processRef, application, logger: appLogger });
        await runner.initPromise;

        processRef.emit(eventName, new Error('fatal test error'));
        await runner.requestStop('wait for fatal cleanup');

        expect(application.shutdown).toHaveBeenCalledWith(shutdownReason);
        expect(processRef.exitCode).toBe(1);
        expect(processRef.exit).toHaveBeenCalledWith(1);
        expect(application.shutdown.mock.invocationCallOrder[0])
            .toBeLessThan(processRef.exit.mock.invocationCallOrder[0]);
    });

    test('initialization failure exits nonzero after cleanup', async () => {
        const processRef = createProcess();
        const application = {
            init: jest.fn().mockRejectedValue(new Error('database failed')),
            shutdown: jest.fn().mockResolvedValue()
        };
        const runner = runApplication({
            process: processRef,
            application,
            logger: createLogger()
        });

        await runner.initPromise;

        expect(application.shutdown).toHaveBeenCalledWith('initialization failure');
        expect(processRef.exit).toHaveBeenCalledWith(1);
    });
});

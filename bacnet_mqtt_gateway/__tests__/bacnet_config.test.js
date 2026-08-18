const fs = require('fs');
const os = require('os');
const path = require('path');

describe('BacnetConfig', () => {
    let tempDir;
    let loggerMock;
    const originalNodeEnv = process.env.NODE_ENV;

    const loadModule = () => {
        jest.resetModules();
        jest.doMock('../src/common', () => {
            loggerMock = { log: jest.fn() };
            return { logger: loggerMock };
        });
        return require('../src/bacnet_config');
    };

    beforeAll(() => {
        process.env.NODE_ENV = 'development';
    });

    afterAll(() => {
        process.env.NODE_ENV = originalNodeEnv;
    });

    beforeEach(() => {
        process.env.NODE_CONFIG_STRICT_MODE = '0';
        tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bacnet-config-')) + path.sep;
        process.env.NODE_CONFIG = JSON.stringify({ bacnet: { configFolder: tempDir } });
    });

    afterEach(() => {
        delete process.env.NODE_CONFIG;
        delete process.env.NODE_CONFIG_STRICT_MODE;
        fs.rmSync(tempDir, { recursive: true, force: true });
        jest.resetModules();
    });

    test('delete removes file within configured devices folder', async () => {
        const configPath = path.join(tempDir, 'device.1.json');
        fs.writeFileSync(configPath, JSON.stringify({}));

        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();

        await config.delete(1);

        expect(fs.existsSync(configPath)).toBe(false);
    });

    test('load skips invalid JSON without crashing', async () => {
        const validPath = path.join(tempDir, 'device.2.json');
        const invalidPath = path.join(tempDir, 'device.invalid.json');
        fs.writeFileSync(validPath, JSON.stringify({ device: { deviceId: 2 } }));
        fs.writeFileSync(invalidPath, '{bad json');

        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();
        const loaded = [];

        config.on('configLoaded', (cfg) => loaded.push(cfg));
        const result = await config.load();

        expect(loaded).toHaveLength(1);
        expect(loaded[0].device.deviceId).toBe(2);
        expect(result).toEqual(loaded);
        expect(loggerMock.log).toHaveBeenCalledWith(
            'error',
            expect.stringContaining('Error while parsing config file')
        );
    });

    test('load skips deactivated files and logs the skip', async () => {
        const activePath = path.join(tempDir, 'device.3.json');
        const inactivePath = path.join(tempDir, '_device.4.json');
        fs.writeFileSync(activePath, JSON.stringify({ device: { deviceId: 3 } }));
        fs.writeFileSync(inactivePath, JSON.stringify({ device: { deviceId: 4 } }));

        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();
        const loaded = [];

        config.on('configLoaded', (cfg) => loaded.push(cfg));
        const result = await config.load();

        expect(loaded).toHaveLength(1);
        expect(loaded[0].device.deviceId).toBe(3);
        expect(result).toEqual(loaded);
        expect(loggerMock.log).toHaveBeenCalledWith(
            'info',
            expect.stringContaining('Skipping deactivated file _device.4.json')
        );
    });

    test('save writes config file and logs success', async () => {
        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();
        const deviceConfig = {
            device: { deviceId: 9, address: '192.168.1.9' },
            polling: { class: 'normal' },
            objects: [{ objectId: { type: 2, instance: 200 } }]
        };

        await config.save(deviceConfig);

        const savedPath = path.join(tempDir, 'device.9.json');
        expect(JSON.parse(fs.readFileSync(savedPath, 'utf8'))).toEqual(deviceConfig);
        expect(loggerMock.log).toHaveBeenCalledWith(
            'info',
            "Config file 'device.9.json' successfully saved."
        );
    });

    test('delete rejects when config file does not exist', async () => {
        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();

        await expect(config.delete(404)).rejects.toBeTruthy();
        expect(loggerMock.log).toHaveBeenCalledWith(
            'error',
            expect.stringContaining("Error while deleting config file")
        );
    });

    test('load logs folder read errors', async () => {
        fs.rmSync(tempDir, { recursive: true, force: true });

        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();

        await expect(config.load()).resolves.toEqual([]);

        expect(loggerMock.log).toHaveBeenCalledWith(
            'error',
            expect.stringContaining('Error while reading config folder')
        );
    });

    test('load waits for asynchronous configLoaded listeners before resolving', async () => {
        const configPath = path.join(tempDir, 'device.5.json');
        fs.writeFileSync(configPath, JSON.stringify({ device: { deviceId: 5 } }));

        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();
        let releaseListener;
        const listenerComplete = jest.fn();
        const listenerGate = new Promise((resolve) => {
            releaseListener = resolve;
        });

        config.on('configLoaded', async () => {
            await listenerGate;
            listenerComplete();
        });

        let loadResolved = false;
        const loadPromise = config.load().then((result) => {
            loadResolved = true;
            return result;
        });
        await new Promise((resolve) => setImmediate(resolve));

        expect(loadResolved).toBe(false);
        expect(listenerComplete).not.toHaveBeenCalled();

        releaseListener();
        await expect(loadPromise).resolves.toEqual([{ device: { deviceId: 5 } }]);
        expect(listenerComplete).toHaveBeenCalledTimes(1);
    });

    test('load logs and skips configs rejected by asynchronous listeners', async () => {
        const rejectedPath = path.join(tempDir, 'device.6.json');
        const acceptedPath = path.join(tempDir, 'device.7.json');
        fs.writeFileSync(rejectedPath, JSON.stringify({ device: { deviceId: 6 } }));
        fs.writeFileSync(acceptedPath, JSON.stringify({ device: { deviceId: 7 } }));

        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();
        config.on('configLoaded', async (deviceConfig) => {
            if (deviceConfig.device.deviceId === 6) {
                throw new Error('registration failed');
            }
        });

        await expect(config.load()).resolves.toEqual([{ device: { deviceId: 7 } }]);
        expect(loggerMock.log).toHaveBeenCalledWith(
            'error',
            expect.stringContaining("Error while registering config file 'device.6.json': Error: registration failed")
        );
    });

    test('buildConfigPath rejects invalid device ids outside safe filename set', () => {
        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();

        expect(() => config._buildConfigPath('../escape')).toThrow('Invalid deviceId for config path');
        expect(() => config._buildConfigPath('device/1')).toThrow('Invalid deviceId for config path');
    });

    test('save and delete reject invalid device ids early', async () => {
        const { BacnetConfig } = loadModule();
        const config = new BacnetConfig();

        await expect(config.save({ device: { deviceId: '../escape' } }))
            .rejects.toThrow('Invalid deviceId for config path');
        await expect(config.delete('../escape')).rejects.toThrow('Invalid deviceId for config path');

        expect(loggerMock.log).toHaveBeenCalledWith(
            'error',
            expect.stringContaining('Error while resolving config file path')
        );
    });
});

const fs = require('fs');
const path = require('path');
const EventEmitter = require('events');
const config = require('config');
const { DeviceObjectId, DeviceObject, logger } = require('./common');

const devicesFolder = config.get('bacnet.configFolder');

class BacnetConfig extends EventEmitter {
    _buildConfigPath(deviceId) {
        const safeDeviceId = String(deviceId);
        if (!/^[A-Za-z0-9_-]+$/.test(safeDeviceId)) {
            throw new Error(`Invalid deviceId for config path: ${safeDeviceId}`);
        }

        const filename = `device.${safeDeviceId}.json`;
        const baseDir = path.resolve(devicesFolder);
        const targetPath = path.resolve(baseDir, filename);
        const relativePath = path.relative(baseDir, targetPath);
        if (relativePath.startsWith('..') || path.isAbsolute(relativePath)) {
            throw new Error(`Resolved config path escaped config folder: ${filename}`);
        }

        return { filename, targetPath };
    }

    async _emitAsync(eventName, ...args) {
        // EventEmitter#emit does not observe promises returned by listeners. Invoke
        // the raw listeners directly so callers can treat load() as a real
        // readiness boundary while preserving EventEmitter ordering and `once`
        // listener behavior.
        for (const listener of this.rawListeners(eventName)) {
            await listener.apply(this, args);
        }
    }

    async load() {
        let files;
        try {
            files = await fs.promises.readdir(devicesFolder);
        } catch (err) {
            logger.log('error', `Error while reading config folder: ${err}`);
            return [];
        }

        logger.log('info', `Device configs found: ${files}`);
        const loadedConfigs = await Promise.all(files.map(async (file) => {
            // Files prefixed with _ are deactivated and therefore skipped.
            if (file.startsWith('_')) {
                logger.log('info', `Skipping deactivated file ${file}`);
                return null;
            }

            let contents;
            try {
                contents = await fs.promises.readFile(path.join(devicesFolder, file), 'utf8');
            } catch (err) {
                logger.log('error', `Error while reading config file '${file}': ${err}`);
                return null;
            }

            let deviceConfig;
            try {
                deviceConfig = JSON.parse(contents);
            } catch (parseErr) {
                logger.log('error', `Error while parsing config file '${file}': ${parseErr}`);
                return null;
            }

            try {
                await this._emitAsync('configLoaded', deviceConfig);
                return deviceConfig;
            } catch (listenerErr) {
                logger.log('error', `Error while registering config file '${file}': ${listenerErr}`);
                return null;
            }
        }));

        return loadedConfigs.filter((deviceConfig) => deviceConfig !== null);
    }

    save(deviceConfig) {
        let configPath;
        try {
            configPath = this._buildConfigPath(deviceConfig.device.deviceId);
        } catch (err) {
            logger.log('error', `Error while resolving config file path: ${err}`);
            return Promise.reject(err);
        }

        return new Promise((resolve, reject) => {
            fs.writeFile(configPath.targetPath, JSON.stringify(deviceConfig, null, 4), (err) => {
                if (err) {
                    logger.log('error', `Error while writing config file: ${err}`);
                    reject(err);
                    return;
                }
                logger.log('info', `Config file '${configPath.filename}' successfully saved.`);
                resolve();
            });
        });
    }

    delete(deviceId) {
        let configPath;
        try {
            configPath = this._buildConfigPath(deviceId);
        } catch (err) {
            logger.log('error', `Error while resolving config file path: ${err}`);
            return Promise.reject(err);
        }

        return new Promise((resolve, reject) => {
            fs.unlink(configPath.targetPath, (err) => {
                if (err) {
                    logger.log('error', `Error while deleting config file '${configPath.targetPath}': ${err}`);
                    reject(err);
                } else {
                    logger.log('info', `Config file '${configPath.filename}' successfully deleted.`);
                    resolve();
                }
            });
        });
    }
}

module.exports = { BacnetConfig };

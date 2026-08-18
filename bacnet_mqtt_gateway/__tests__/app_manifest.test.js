const fs = require('fs');
const path = require('path');
const YAML = require('yaml');

const appRoot = path.resolve(__dirname, '..');

function readYaml(relativePath) {
    return YAML.parse(fs.readFileSync(path.join(appRoot, relativePath), 'utf8'));
}

describe('Home Assistant App manifest', () => {
    const manifest = readYaml('config.yaml');
    const translations = readYaml('translations/en.yaml');
    const packageJson = JSON.parse(fs.readFileSync(path.join(appRoot, 'package.json'), 'utf8'));

    test('uses the current Supervisor app contract', () => {
        expect(manifest).toEqual(expect.objectContaining({
            name: 'BACnet MQTT Gateway',
            slug: 'bacnet_mqtt_gateway',
            version: packageJson.version,
            arch: ['aarch64', 'amd64'],
            host_network: true,
            ingress: true,
            ingress_port: 18082,
            ingress_entry: 'admin/',
            services: ['mqtt:want']
        }));
        expect(manifest.map).toContainEqual({
            type: 'app_config',
            read_only: false,
            path: '/config'
        });
        expect(manifest.map.some((entry) => entry.type === 'addon_config')).toBe(false);
    });

    test('defines defaults and translations for every required option', () => {
        const schemaKeys = Object.keys(manifest.schema).sort();
        const translationKeys = Object.keys(translations.configuration).sort();
        expect(translationKeys).toEqual(schemaKeys);

        for (const optionName of Object.keys(manifest.options)) {
            expect(manifest.schema).toHaveProperty(optionName);
        }
    });
});

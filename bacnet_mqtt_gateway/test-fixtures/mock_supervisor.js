const fs = require('fs');
const http = require('http');

const optionsPath = process.argv[2];
const port = Number(process.argv[3] || 18083);
const mqttServicePath = process.argv[4];

if (!optionsPath || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('Usage: node mock_supervisor.js <options.json> [port]');
}

const options = JSON.parse(fs.readFileSync(optionsPath, 'utf8'));
const mqttService = mqttServicePath
    ? JSON.parse(fs.readFileSync(mqttServicePath, 'utf8'))
    : null;
const server = http.createServer((request, response) => {
    if (request.method === 'GET' && request.url === '/addons/self/options/config') {
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ result: 'ok', data: options }));
        return;
    }

    if (request.method === 'GET' && request.url === '/services/mqtt' && mqttService) {
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ result: 'ok', data: mqttService }));
        return;
    }

    {
        response.writeHead(404, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ result: 'error', message: 'Not found' }));
    }
});

server.listen(port, '127.0.0.1');

for (const signal of ['SIGTERM', 'SIGINT']) {
    process.on(signal, () => server.close(() => process.exit(0)));
}

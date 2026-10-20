
// Local gateway for the bank-easy page. Serves index.html and forwards
// /api/<service>/... to that service, so the browser needs no CORS.
// Run port-forward.sh first so the targets below are reachable.
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.PORT || 8080);
const HOST = process.env.SERVICE_HOST || 'localhost';
const TARGETS = {
  auth: Number(process.env.AUTH_PORT || 4001),
  ledger: Number(process.env.LEDGER_PORT || 4002),
  payments: Number(process.env.PAYMENTS_PORT || 4003),
  loans: Number(process.env.LOANS_PORT || 4006),
};

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');

  if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/index.html')) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(fs.readFileSync(path.join(__dirname, 'index.html')));
  }

  const m = url.pathname.match(/^\/api\/([a-z]+)(\/.*)?$/);
  if (!m || !TARGETS[m[1]]) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ error: 'not found' }));
  }

  const name = m[1];
  const target = `http://${HOST}:${TARGETS[name]}${m[2] || '/'}${url.search}`;
  const hasBody = req.method !== 'GET' && req.method !== 'HEAD';
  const headers = { 'Content-Type': 'application/json' };
  if (req.headers.authorization) headers.Authorization = req.headers.authorization;

  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await readBody(req) : undefined,
    });
    const text = await upstream.text();
    res.writeHead(upstream.status, { 'Content-Type': 'application/json' });
    res.end(text);
  } catch (err) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: `${name} unreachable` }));
  }
});

server.listen(PORT, () => console.log(`bank-easy page on http://localhost:${PORT}`));

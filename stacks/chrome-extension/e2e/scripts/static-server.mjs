import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';

const host = '127.0.0.1';
const port = Number(process.env.E2E_FIXTURE_PORT || 4175);
const root = path.resolve(process.cwd(), 'test-pages');

const mimeTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.json': 'application/json; charset=utf-8',
};

function targetForRequest(urlPath) {
  const decoded = decodeURIComponent(urlPath);
  const relative = decoded === '/' ? 'navigation/index.html' : decoded.replace(/^\/+/, '');
  const target = path.resolve(root, relative);
  return target === root || target.startsWith(`${root}${path.sep}`) ? target : null;
}

const server = http.createServer(async (request, response) => {
  const requestUrl = new URL(request.url || '/', `http://${host}:${port}`);
  const target = targetForRequest(requestUrl.pathname);
  if (!target) {
    response.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' });
    response.end('Forbidden');
    return;
  }

  try {
    const body = await fs.readFile(target);
    response.writeHead(200, {
      'content-type':
        mimeTypes[path.extname(target).toLowerCase()] ||
        'application/octet-stream',
    });
    response.end(body);
  } catch {
    response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    response.end('Not Found');
  }
});

server.listen(port, host, () => {
  console.log(`[e2e-fixture] ${root} at http://${host}:${port}`);
});

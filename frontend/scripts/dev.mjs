import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const frontend = fileURLToPath(new URL('..', import.meta.url));
const backend = resolve(frontend, '../backend');
for (const file of ['.env.local', '.env']) {
  if (existsSync(resolve(frontend, file))) process.loadEnvFile(resolve(frontend, file));
}
const origin = new URL(process.env.API_BASE_URL || 'http://127.0.0.1:8000');
let api;
let next;
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  next?.kill('SIGTERM');
  api?.kill('SIGTERM');
  process.exitCode = code;
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
async function healthy() {
  try {
    const response = await fetch(new URL('/api/health', origin), { signal: AbortSignal.timeout(1000) });
    const data = await response.json();
    return response.ok && data.status === 'ok' && data.source === 'anime4up';
  } catch { return false; }
}
try {
  if (!await healthy()) {
    if (origin.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(origin.hostname)) {
      throw new Error('Configured API_BASE_URL is unavailable. Start that backend before Next.js.');
    }
    const python = process.env.BACKEND_PYTHON || resolve(backend, '.venv/bin/python');
    if (!existsSync(python)) throw new Error('Backend virtual environment is missing. Follow backend/README.md first.');
    console.log('[dev] Starting the Anime4Up backend…');
    api = spawn(python, ['-m', 'uvicorn', 'api:app', '--host', origin.hostname, '--port', origin.port || '80'], { cwd: backend, stdio: 'inherit' });
    api.on('error', error => { console.error('[dev]', error.message); stop(1); });
    api.on('exit', code => { if (!stopping) { console.error('[dev] Backend stopped.'); stop(code || 1); } });
    let ready = false;
    for (let attempt = 0; attempt < 30 && !stopping; attempt++) {
      if (await healthy()) { ready = true; break; }
      await delay(300);
    }
    if (!ready) throw new Error('Backend did not become healthy. See its startup error above.');
  } else {
    console.log('[dev] Using the running Anime4Up backend.');
  }
  if (!stopping) {
    next = spawn(process.execPath, [resolve(frontend, 'node_modules/next/dist/bin/next'), 'dev', ...process.argv.slice(2)], { cwd: frontend, stdio: 'inherit' });
    next.on('error', error => { console.error('[dev]', error.message); stop(1); });
    next.on('exit', code => stop(code || 0));
  }
} catch (error) {
  console.error('[dev]', error.message);
  stop(1);
}

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { heading, success, info, warn, fail, color } = require('../lib/theme');
const { run, commandExists } = require('../lib/exec');
const { ROOT, VAK_CLIENT, VAK_DEEPGRAM } = require('../lib/paths');

function venvPaths(venvDir) {
  const isWin = process.platform === 'win32';
  return {
    python: path.join(venvDir, isWin ? 'Scripts' : 'bin', isWin ? 'python.exe' : 'python'),
    pip: path.join(venvDir, isWin ? 'Scripts' : 'bin', isWin ? 'pip.exe' : 'pip'),
  };
}

// Tracks which requirements.txt the venv was last installed from. Keyed by
// content hash so editing requirements.txt re-installs, and so an install that
// dies halfway (network drop, Ctrl-C) leaves no stamp and is retried next run.
function requirementsStamp() {
  const reqPath = path.join(VAK_DEEPGRAM, 'requirements.txt');
  const hash = crypto.createHash('sha256').update(fs.readFileSync(reqPath)).digest('hex');
  return { stampPath: path.join(VAK_DEEPGRAM, 'venv', '.vak-requirements'), hash };
}

async function ensureBackendReady() {
  const envPath = path.join(VAK_DEEPGRAM, '.env');
  if (!fs.existsSync(envPath)) {
    warn('VakDeepGram/.env not found — run `./vak init` first (or copy .env.example manually).');
    return false;
  }

  const venvDir = path.join(VAK_DEEPGRAM, 'venv');
  const { python, pip } = venvPaths(venvDir);
  if (!fs.existsSync(python)) {
    info('Creating a Python virtual environment for VakDeepGram (first run only)...');
    const pythonCmd = commandExists('python3') ? 'python3' : 'python';
    const code = await run(pythonCmd, ['-m', 'venv', 'venv'], { cwd: VAK_DEEPGRAM });
    if (code !== 0) {
      fail('Failed to create the Python virtual environment.');
      return false;
    }
  }

  // Deliberately keyed on the stamp, not on the venv existing: a venv created
  // successfully but left empty by a failed `pip install` would otherwise look
  // "ready" forever and fail later with a bare ModuleNotFoundError.
  const { stampPath, hash } = requirementsStamp();
  const installed = fs.existsSync(stampPath) && fs.readFileSync(stampPath, 'utf8').trim() === hash;
  if (!installed) {
    info('Installing Python dependencies (this can take a minute)...');
    const installCode = await run(pip, ['install', '-r', 'requirements.txt'], { cwd: VAK_DEEPGRAM });
    if (installCode !== 0) {
      fail('Failed to install Python dependencies.');
      info(`Try running it directly to see the full error:`);
      info(`  ${path.relative(ROOT, pip)} install -r requirements.txt`);
      return false;
    }
    fs.writeFileSync(stampPath, hash + '\n');
    success('VakDeepGram dependencies installed.');
  }
  return true;
}

async function ensureClientReady() {
  const nodeModules = path.join(VAK_CLIENT, 'node_modules');
  if (!fs.existsSync(nodeModules)) {
    info('Installing VakClient dependencies (first run only)...');
    const code = await run('npm', ['install'], { cwd: VAK_CLIENT });
    if (code !== 0) {
      fail('Failed to install VakClient dependencies.');
      return false;
    }
  }
  return true;
}

function spawnPrefixed(label, colorFn, command, args, options) {
  const child = spawn(command, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'] });
  const prefix = colorFn(`[${label}] `);
  const pipe = (stream) =>
    stream.on('data', (chunk) => {
      const text = chunk.toString();
      for (const line of text.split('\n')) {
        if (line.length > 0) process.stdout.write(prefix + line + '\n');
      }
    });
  pipe(child.stdout);
  pipe(child.stderr);
  return child;
}

async function dev() {
  heading('Starting Vak locally');

  const backendOk = await ensureBackendReady();
  const clientOk = await ensureClientReady();
  if (!backendOk || !clientOk) {
    fail('Fix the issue above and re-run `./vak dev`.');
    process.exitCode = 1;
    return;
  }

  const { python } = venvPaths(path.join(VAK_DEEPGRAM, 'venv'));
  const backendEnv = { ...process.env, PYTHONPATH: `${process.env.PYTHONPATH || ''}${path.delimiter}${path.join(VAK_DEEPGRAM, 'src')}` };

  info('Backend:  http://localhost:8080  (WebSocket at /ws)');
  info('Frontend: http://localhost:5173');
  console.log('');

  const backend = spawnPrefixed('backend', color.blue, python, [
    '-m', 'uvicorn', 'vakdeepgram.api.main:app',
    '--host', '0.0.0.0', '--port', '8080', '--reload',
  ], { cwd: VAK_DEEPGRAM, env: backendEnv });

  const frontend = spawnPrefixed('client', color.magenta, 'npm', ['run', 'dev'], { cwd: VAK_CLIENT });

  let shuttingDown = false;
  const shutdown = () => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log('');
    info('Shutting down...');
    backend.kill('SIGTERM');
    frontend.kill('SIGTERM');
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  backend.on('close', shutdown);
  frontend.on('close', shutdown);
}

module.exports = { dev };

'use strict';

const { spawn } = require('node:child_process');

/** Run a command, streaming stdio, resolving with the exit code (never rejects on non-zero). */
function run(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: 'inherit', ...options });
    child.on('close', (code) => resolve(code ?? 1));
    child.on('error', (err) => {
      console.error(`  Failed to run "${command}": ${err.message}`);
      resolve(1);
    });
  });
}

/** Run a command and capture stdout as a trimmed string, or null on failure. */
function capture(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'ignore'], ...options });
    let out = '';
    child.stdout.on('data', (d) => (out += d.toString()));
    child.on('close', (code) => resolve(code === 0 ? out.trim() : null));
    child.on('error', () => resolve(null));
  });
}

function commandExists(command) {
  const { spawnSync } = require('node:child_process');
  const probe = process.platform === 'win32' ? 'where' : 'which';
  const result = spawnSync(probe, [command], { stdio: 'ignore' });
  return result.status === 0;
}

module.exports = { run, capture, commandExists };

'use strict';

const fs = require('node:fs');
const path = require('node:path');

/**
 * Merge `updates` (a Map or plain object of KEY -> value) into an existing
 * .env file's text, preserving comments and untouched keys. Keys that don't
 * already exist are appended under a "Set by `vak init`" section. Falsy
 * values (undefined/null) are skipped so we never write "KEY=undefined".
 */
function upsertEnvFile(filePath, updates) {
  let original = '';
  if (fs.existsSync(filePath)) {
    original = fs.readFileSync(filePath, 'utf8');
  } else {
    const examplePath = `${filePath}.example`;
    if (fs.existsSync(examplePath)) {
      original = fs.readFileSync(examplePath, 'utf8');
    }
  }

  const lines = original.length > 0 ? original.split('\n') : [];
  const seen = new Set();
  const entries = Object.entries(updates).filter(([, v]) => v !== undefined && v !== null);

  const nextLines = lines.map((line) => {
    const match = /^([A-Za-z_][A-Za-z0-9_]*)=/.exec(line);
    if (!match) return line;
    const key = match[1];
    const entry = entries.find(([k]) => k === key);
    if (!entry) return line;
    seen.add(key);
    return `${key}=${formatValue(entry[1])}`;
  });

  const remaining = entries.filter(([k]) => !seen.has(k));
  if (remaining.length > 0) {
    if (nextLines.length > 0 && nextLines[nextLines.length - 1].trim() !== '') {
      nextLines.push('');
    }
    nextLines.push("# Set by `vak init`");
    for (const [key, value] of remaining) {
      nextLines.push(`${key}=${formatValue(value)}`);
    }
  }

  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, nextLines.join('\n').replace(/\n{3,}/g, '\n\n') + '\n');
}

function formatValue(value) {
  const str = String(value);
  return /[\s#"']/.test(str) ? JSON.stringify(str) : str;
}

/** Parse a .env file into a plain object. Returns {} if the file doesn't exist. */
function readEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const result = {};
  const lines = fs.readFileSync(filePath, 'utf8').split('\n');
  for (const line of lines) {
    const match = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(line);
    if (!match) continue;
    let value = match[2];
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      try {
        value = JSON.parse(value.startsWith("'") ? `"${value.slice(1, -1)}"` : value);
      } catch {
        value = value.slice(1, -1);
      }
    }
    result[match[1]] = value;
  }
  return result;
}

module.exports = { upsertEnvFile, readEnvFile };

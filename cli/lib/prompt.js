'use strict';

const fs = require('node:fs');
const readline = require('node:readline');
const { color } = require('./theme');

const isInteractive = Boolean(process.stdin.isTTY);

// Node's readline has a sharp edge with piped (non-TTY) input: if multiple
// lines are already buffered when a `.question()` call is made, readline can
// flush several 'line' events synchronously, but `.question()` only ever
// consumes one — the rest are silently dropped before the next question is
// even asked. That's invisible with a real terminal (a human can't type
// ahead of a prompt they haven't seen yet) but corrupts any piped/scripted
// input. Side-step it entirely: when stdin isn't a TTY, slurp it all up
// front and serve it as a plain queue. This also makes `vak init` scriptable.
let pipedLines = null;
function nextPipedLine() {
  if (pipedLines === null) {
    let raw = '';
    try {
      raw = fs.readFileSync(0, 'utf8');
    } catch {
      raw = '';
    }
    pipedLines = raw.split('\n');
  }
  return pipedLines.length > 0 ? pipedLines.shift().trim() : '';
}

let sharedInterface = null;
function getInterface() {
  if (!sharedInterface) {
    sharedInterface = readline.createInterface({ input: process.stdin, output: process.stdout });
  }
  return sharedInterface;
}

function closePrompt() {
  if (sharedInterface) {
    sharedInterface.close();
    sharedInterface = null;
  }
}

function ask(query) {
  if (!isInteractive) {
    const line = nextPipedLine();
    process.stdout.write(query + line + '\n');
    return Promise.resolve(line);
  }
  return new Promise((resolve) => getInterface().question(query, resolve));
}

/** Free-text prompt with an optional default value. */
async function text(question, { default: def, allowEmpty = true } = {}) {
  const suffix = def ? color.dim(` (${def})`) : '';
  while (true) {
    const answer = await ask(`  ${question}${suffix}: `);
    const value = answer.trim() || def || '';
    if (value || allowEmpty) return value;
    console.log(color.yellow('  A value is required.'));
  }
}

/**
 * Masked prompt for secrets. On a real TTY, echoes '*' per keystroke using
 * the shared interface (so it can't collide with other prompts over the
 * same stdin). Piped input just falls back to a plain question.
 */
async function password(question) {
  if (!isInteractive) {
    return ask(`  ${question}: `);
  }

  const rl = getInterface();
  return new Promise((resolve) => {
    // eslint-disable-next-line no-underscore-dangle
    const original = rl._writeToOutput.bind(rl);
    let masking = false;
    // eslint-disable-next-line no-underscore-dangle
    rl._writeToOutput = (chunk) => {
      original(masking ? '*'.repeat(chunk.length) : chunk);
    };
    masking = true;
    rl.question(`  ${question}: `, (answer) => {
      // eslint-disable-next-line no-underscore-dangle
      rl._writeToOutput = original;
      resolve(answer);
    });
  });
}

/** Single-choice prompt from a list of { value, label } options. */
async function select(question, choices, { default: def } = {}) {
  console.log(`  ${question}`);
  choices.forEach((choice, i) => {
    const marker = choice.value === def ? color.cyan('>') : ' ';
    console.log(`  ${marker} ${i + 1}) ${choice.label}`);
  });
  const defIndex = def ? choices.findIndex((c) => c.value === def) + 1 : 1;
  while (true) {
    const answer = await ask(`  Enter a number${color.dim(` (${defIndex})`)}: `);
    const raw = answer.trim();
    const n = raw === '' ? defIndex : parseInt(raw, 10);
    if (Number.isInteger(n) && n >= 1 && n <= choices.length) {
      return choices[n - 1].value;
    }
    console.log(color.yellow(`  Enter a number between 1 and ${choices.length}.`));
  }
}

/** Yes/no prompt. */
async function confirm(question, { default: def = true } = {}) {
  const hint = def ? 'Y/n' : 'y/N';
  const answer = await ask(`  ${question} (${hint}): `);
  const trimmed = answer.trim().toLowerCase();
  if (!trimmed) return def;
  return trimmed === 'y' || trimmed === 'yes';
}

module.exports = { text, password, select, confirm, closePrompt };

'use strict';

const isTTY = process.stdout.isTTY && process.env.NO_COLOR === undefined;

function paint(code) {
  return (text) => (isTTY ? `[${code}m${text}[0m` : String(text));
}

const color = {
  bold: paint('1'),
  dim: paint('2'),
  red: paint('31'),
  green: paint('32'),
  yellow: paint('33'),
  blue: paint('34'),
  magenta: paint('35'),
  cyan: paint('36'),
};

/** A section header. Minimal by design: one blank line, bold text, no glyphs. */
function heading(text) {
  console.log('');
  console.log(color.bold(text));
}

/** A quieter sub-line under a heading — context, not an instruction. */
function info(text) {
  console.log(color.dim('  ' + text));
}

function success(text) {
  console.log(color.green('  ✓ ') + text);
}

function warn(text) {
  console.log(color.yellow('  ! ') + text);
}

function fail(text) {
  console.log(color.red('  ✗ ') + text);
}

function banner() {
  console.log('');
  console.log(color.bold('vak'));
  console.log(color.dim('Set up, run, and deploy a voice agent.'));
}

module.exports = { color, heading, info, success, warn, fail, banner, isTTY };

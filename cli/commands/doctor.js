'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { heading, success, warn, fail, info } = require('../lib/theme');
const { commandExists, capture } = require('../lib/exec');
const { ROOT } = require('../lib/paths');

async function checkNode() {
  const version = process.versions.node;
  const major = parseInt(version.split('.')[0], 10);
  if (major >= 20) {
    success(`Node.js ${version}`);
  } else {
    fail(`Node.js ${version} — Vak needs Node 20+`);
  }
  return major >= 20;
}

async function checkPython() {
  for (const cmd of ['python3', 'python']) {
    if (commandExists(cmd)) {
      const version = await capture(cmd, ['--version']);
      success(`${version || cmd} found`);
      return true;
    }
  }
  fail('Python 3.8+ not found — required for VakDeepGram');
  return false;
}

async function checkDocker() {
  if (!commandExists('docker')) {
    warn('Docker not found — needed to build/push the VakDeepGram image for AWS deploys');
    return false;
  }
  const info_ = await capture('docker', ['info']);
  if (info_ === null) {
    warn('Docker CLI found but the daemon is not running');
    return false;
  }
  success('Docker is installed and running');
  return true;
}

async function checkAwsCli() {
  if (!commandExists('aws')) {
    warn('AWS CLI not found — needed for AWS deploys (not required for local dev)');
    return false;
  }
  const identity = await capture('aws', ['sts', 'get-caller-identity', '--output', 'json']);
  if (!identity) {
    warn('AWS CLI installed, but no credentials configured (run `aws configure`)');
    return false;
  }
  try {
    const parsed = JSON.parse(identity);
    success(`AWS CLI authenticated as ${parsed.Arn || parsed.UserId}`);
  } catch {
    success('AWS CLI installed and authenticated');
  }
  return true;
}

async function checkCdk() {
  if (commandExists('cdk')) {
    success('AWS CDK CLI found (global install)');
    return true;
  }
  const cdkBin = path.join(ROOT, 'VakInfra', 'node_modules', '.bin', 'cdk');
  if (fs.existsSync(cdkBin)) {
    success('AWS CDK CLI found (via VakInfra/node_modules)');
    return true;
  }
  info('AWS CDK CLI not found globally — `npx cdk` will fetch it on demand during `vak deploy`');
  return true;
}

function checkEnvFiles() {
  const files = [
    path.join(ROOT, 'VakDeepGram', '.env'),
    path.join(ROOT, 'VakClient', '.env'),
  ];
  let allPresent = true;
  for (const file of files) {
    const rel = path.relative(ROOT, file);
    if (fs.existsSync(file)) {
      success(`${rel} exists`);
    } else {
      warn(`${rel} missing — run \`./vak init\` to create it`);
      allPresent = false;
    }
  }
  return allPresent;
}

async function doctor() {
  heading('Checking your environment');
  await checkNode();
  await checkPython();
  await checkDocker();
  await checkAwsCli();
  await checkCdk();

  heading('Checking project configuration');
  checkEnvFiles();

  console.log('');
  info('Run `./vak init` to fix missing configuration, or `./vak dev` if everything looks good.');
}

module.exports = { doctor };

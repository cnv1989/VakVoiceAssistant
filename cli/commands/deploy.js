'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { heading, success, info, warn, fail, color } = require('../lib/theme');
const { confirm, closePrompt } = require('../lib/prompt');
const { run, commandExists, capture } = require('../lib/exec');
const { readEnvFile } = require('../lib/env-file');
const { VAK_INFRA, VAK_DEEPGRAM } = require('../lib/paths');

// Maps VakInfra/.env keys (see VakInfra/README.md's context table) to CDK
// `-c key=value` context flags.
const CONTEXT_KEYS = {
  VAK_STACK_NAME: 'stackName',
  VAK_STAGE: 'stage',
  AWS_REGION: 'awsRegion',
  IMAGE_TAG: 'imageTag',
  ECR_REPOSITORY_NAME: 'ecrRepositoryName',
  DEEPGRAM_API_KEY: 'deepgramApiKey',
  DEEPGRAM_API_KEY_SECRET_ARN: 'deepgramApiKeySecretArn',
  LLM_PROVIDER: 'llmProvider',
  LLM_MODEL_ID: 'llmModelId',
  ANTHROPIC_API_KEY: 'anthropicApiKey',
  ANTHROPIC_API_KEY_SECRET_ARN: 'anthropicApiKeySecretArn',
  OPENAI_API_KEY: 'openaiApiKey',
  OPENAI_API_KEY_SECRET_ARN: 'openaiApiKeySecretArn',
  DEEPGRAM_SPEAKING_PROVIDER: 'deepgramSpeakingProvider',
  DEEPGRAM_SPEAKING_MODEL_ID: 'deepgramSpeakingModelId',
  DEEPGRAM_SPEAKING_VOICE_ID: 'deepgramSpeakingVoiceId',
  DEEPGRAM_THINKING_PROVIDER: 'deepgramThinkingProvider',
  DEEPGRAM_THINKING_MODEL: 'deepgramThinkingModel',
  BUSINESS_NAME: 'businessName',
  BUSINESS_VERTICAL: 'businessVertical',
  BUSINESS_ROLE_DESCRIPTION: 'businessRoleDescription',
  DOMAIN_NAME: 'domainName',
  HOSTED_ZONE_DOMAIN: 'hostedZoneDomain',
  CERTIFICATE_ARN: 'certificateArn',
  API_KEY: 'apiKey',
  ENABLE_TWILIO_ONLY_ACCESS: 'enableTwilioOnlyAccess',
  TWILIO_ACCOUNT_SID: 'twilioAccountSid',
  TWILIO_FROM_NUMBER: 'twilioFromNumber',
  TWILIO_AUTH_TOKEN: 'twilioAuthToken',
  TWILIO_AUTH_TOKEN_SECRET_ARN: 'twilioAuthTokenSecretArn',
  CHAT_API_KEY: 'chatApiKey',
  COGNITO_DOMAIN_PREFIX: 'cognitoDomainPrefix',
  ALARM_EMAIL: 'alarmEmail',
};

async function preflight() {
  if (!commandExists('aws')) {
    fail('AWS CLI not found. Install it, run `aws configure`, then re-run `./vak deploy`.');
    return false;
  }
  const identity = await capture('aws', ['sts', 'get-caller-identity', '--output', 'json']);
  if (!identity) {
    fail('AWS CLI has no valid credentials. Run `aws configure` (or set up SSO) and try again.');
    return false;
  }
  let account, arn;
  try {
    const parsed = JSON.parse(identity);
    account = parsed.Account;
    arn = parsed.Arn;
  } catch {
    // fall through with unknowns
  }
  success(`AWS credentials OK${account ? ` (account ${account}, ${arn})` : ''}`);

  if (!fs.existsSync(path.join(VAK_INFRA, 'node_modules'))) {
    info('Installing VakInfra dependencies...');
    const code = await run('npm', ['install'], { cwd: VAK_INFRA });
    if (code !== 0) {
      fail('npm install failed in VakInfra.');
      return false;
    }
  }
  return true;
}

// Keys already configured for local dev (VakDeepGram/.env) that should carry
// over to a deploy without re-entering them, for anyone who skipped the AWS
// section of `vak init`. VakInfra/.env (spread second) always wins on conflict.
const LOCAL_DEV_FALLBACK_KEYS = [
  'DEEPGRAM_API_KEY', 'LLM_PROVIDER', 'LLM_MODEL_ID', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY',
  'DEEPGRAM_SPEAKING_PROVIDER', 'BUSINESS_NAME', 'BUSINESS_VERTICAL', 'BUSINESS_ROLE_DESCRIPTION',
  'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER',
];

function buildContextArgs() {
  const infraEnv = readEnvFile(path.join(VAK_INFRA, '.env'));
  const deepgramEnv = readEnvFile(path.join(VAK_DEEPGRAM, '.env'));

  const fallback = {};
  for (const key of LOCAL_DEV_FALLBACK_KEYS) {
    if (deepgramEnv[key] !== undefined) fallback[key] = deepgramEnv[key];
  }
  const merged = { ...fallback, ...infraEnv };

  const args = [];
  for (const [envKey, contextKey] of Object.entries(CONTEXT_KEYS)) {
    const value = merged[envKey];
    if (value !== undefined && value !== '') {
      args.push('-c', `${contextKey}=${value}`);
    }
  }
  return { args, region: merged.AWS_REGION || 'us-west-2' };
}

async function deploy() {
  heading('Deploy Vak to AWS');

  if (!(await preflight())) {
    process.exitCode = 1;
    return;
  }

  const { args: contextArgs, region } = buildContextArgs();
  const hasDeepgramKey = contextArgs.some((a) => a.startsWith('deepgramApiKey=') || a.startsWith('deepgramApiKeySecretArn='));
  if (!hasDeepgramKey) {
    fail('No Deepgram API key found. Run `./vak init` first, or set DEEPGRAM_API_KEY in VakDeepGram/.env.');
    process.exitCode = 1;
    return;
  }

  heading('Bootstrapping CDK (safe to re-run — skips if already done)');
  const bootstrapCode = await run('npx', ['cdk', 'bootstrap'], { cwd: VAK_INFRA });
  if (bootstrapCode !== 0) {
    fail('CDK bootstrap failed. Check the output above.');
    process.exitCode = 1;
    return;
  }

  console.log('');
  warn(`This will create real AWS resources in region ${color.bold(region)} and may incur cost.`);
  const proceed = await confirm('Continue with `cdk deploy --all`?', { default: false });
  closePrompt();
  if (!proceed) {
    info('Cancelled — no changes made.');
    return;
  }

  heading('Deploying (this can take 5-10 minutes on the first run)');
  const deployCode = await run(
    'npx',
    ['cdk', 'deploy', '--all', '--require-approval', 'never', ...contextArgs],
    { cwd: VAK_INFRA }
  );
  if (deployCode !== 0) {
    fail('cdk deploy failed. Check the output above.');
    process.exitCode = 1;
    return;
  }

  success('Infrastructure deployed.');
  heading('Next: push the VakDeepGram image');
  console.log(`  ${color.cyan('cd VakDeepGram && ./deploy-to-ecr.sh')}`);
  console.log('  Then force a new deployment so ECS picks it up:');
  console.log(`  ${color.cyan('aws ecs update-service --cluster vak-cluster-production --service <service-name> --force-new-deployment')}`);
  console.log('');
  info('The WebSocketUrl output above is what VakClient\'s VITE_WS_URL should point to.');
}

module.exports = { deploy };

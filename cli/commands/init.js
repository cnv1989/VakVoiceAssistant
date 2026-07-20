'use strict';

const path = require('node:path');
const crypto = require('node:crypto');
const { heading, success, info, warn, color } = require('../lib/theme');
const { text, password, select, confirm, closePrompt } = require('../lib/prompt');
const { upsertEnvFile } = require('../lib/env-file');
const { ROOT, VAK_CLIENT, VAK_DEEPGRAM, VAK_INFRA } = require('../lib/paths');

const USE_CASES = [
  { value: 'generic', label: 'General assistant (default) — no specific industry' },
  { value: 'barber', label: 'Barber shop / grooming studio' },
  { value: 'salon', label: 'Hair salon' },
  { value: 'spa', label: 'Spa / wellness studio' },
  { value: 'medical', label: 'Medical / clinic' },
  { value: 'fitness', label: 'Fitness studio / gym' },
  { value: 'home_services', label: 'Home services (repair, cleaning, etc.)' },
  { value: 'custom', label: 'Something else — write my own persona' },
];

const LLM_PROVIDERS = [
  { value: 'bedrock', label: 'AWS Bedrock / Claude (default — uses your AWS credentials, no key needed)' },
  { value: 'anthropic', label: 'Anthropic API directly' },
  { value: 'openai', label: 'OpenAI API directly (GPT-4o, etc.)' },
];

const VOICE_PROVIDERS = [
  { value: 'eleven_labs', label: 'ElevenLabs (default — richer voices, proxied through Deepgram, no extra key)' },
  { value: 'deepgram', label: 'Deepgram Aura (lower latency)' },
  { value: 'other', label: 'Something else Deepgram supports (e.g. Cartesia) — I\'ll type the name' },
];

async function init() {
  heading('vak init');
  info('Every question below has a default — press Enter to accept it and move on.');
  info('Re-running this later only touches the keys you change.');

  // ── Use case ─────────────────────────────────────────────────────────────
  heading('Use case (optional)');
  info('What should this assistant do? Skip for a general-purpose assistant.');
  const businessName = await text('Name (shown in greetings, optional)');
  const useCase = await select('Use case', USE_CASES, { default: 'generic' });
  let roleDescription = '';
  if (useCase === 'custom') {
    info('Describe it in a sentence or two — it follows "You are ...".');
    roleDescription = await text(
      'e.g. "a friendly front-desk assistant for an auto repair shop. You help with hours, quotes, and booking service appointments."'
    );
  }

  // ── AI model ─────────────────────────────────────────────────────────────
  heading('AI model');
  info('Powers conversation and tool use (booking, lookups, etc.).');
  const llmProvider = await select('Provider', LLM_PROVIDERS, { default: 'bedrock' });
  let anthropicApiKey = '';
  let openaiApiKey = '';
  if (llmProvider === 'anthropic') {
    anthropicApiKey = await password('Anthropic API key');
  } else if (llmProvider === 'openai') {
    openaiApiKey = await password('OpenAI API key');
  }

  // ── Voice ────────────────────────────────────────────────────────────────
  heading('Voice');
  info('Deepgram handles speech-to-text always, and text-to-speech by default.');
  info('Get a free key at https://console.deepgram.com');
  let deepgramApiKey = '';
  while (!deepgramApiKey) {
    deepgramApiKey = await password('Deepgram API key');
    if (!deepgramApiKey) warn('A Deepgram API key is required.');
  }
  let speakingProvider = await select('Text-to-speech voice', VOICE_PROVIDERS, { default: 'eleven_labs' });
  if (speakingProvider === 'other') {
    speakingProvider = await text('Deepgram TTS provider name (e.g. cartesia)');
  }

  // ── Business data ────────────────────────────────────────────────────────
  heading('Business data');
  const dataMode = await select(
    'How should the agent get business data (hours, services, staff, bookings)?',
    [
      { value: 'local', label: 'Local test mode — a mock business, no real bookings (recommended for first run)' },
      { value: 'connected', label: "I'll connect a real Square/Setmore account (see docs/CONFIGURATION.md)" },
    ],
    { default: 'local' }
  );
  if (dataMode === 'connected') {
    info('Real accounts are wired up per docs/CONFIGURATION.md and VakDeepGram/scripts/seed_setmore_account.py.');
    info('This wizard still writes working defaults — swap in real table/account details afterwards.');
  }

  // ── Twilio (optional) ─────────────────────────────────────────────────────
  heading('Phone calls via Twilio (optional)');
  const setupTwilio = await confirm('Set up Twilio phone integration now?', { default: false });
  let twilio = {};
  if (setupTwilio) {
    twilio.accountSid = await text('Twilio Account SID');
    twilio.authToken = await password('Twilio Auth Token');
    twilio.fromNumber = await text('Twilio phone number (E.164, e.g. +15551234567)');
    info('Run `./vak twilio` next to point that number\'s webhooks at this backend.');
  }

  // ── Write VakDeepGram/.env ────────────────────────────────────────────────
  const deepgramEnv = {
    BUSINESS_NAME: businessName || undefined,
    BUSINESS_VERTICAL: useCase === 'custom' ? 'generic' : useCase,
    BUSINESS_ROLE_DESCRIPTION: roleDescription || undefined,
    LLM_PROVIDER: llmProvider,
    ANTHROPIC_API_KEY: anthropicApiKey || undefined,
    OPENAI_API_KEY: openaiApiKey || undefined,
    DEEPGRAM_API_KEY: deepgramApiKey,
    DEEPGRAM_SPEAKING_PROVIDER: speakingProvider,
    ENVIRONMENT: dataMode === 'local' ? 'development' : 'production',
    OAUTH_ALLOW_LOCALHOST_NOAUTH: dataMode === 'local' ? 'true' : 'false',
  };
  if (setupTwilio) {
    deepgramEnv.TWILIO_ACCOUNT_SID = twilio.accountSid;
    deepgramEnv.TWILIO_AUTH_TOKEN = twilio.authToken;
    deepgramEnv.TWILIO_FROM_NUMBER = twilio.fromNumber;
    deepgramEnv.TWILIO_BUSINESS_NUMBER = twilio.fromNumber;
  }
  upsertEnvFile(path.join(VAK_DEEPGRAM, '.env'), deepgramEnv);
  success(`Wrote ${path.relative(ROOT, path.join(VAK_DEEPGRAM, '.env'))}`);

  // ── Write VakClient/.env ──────────────────────────────────────────────────
  heading('Web client');
  const wsUrl = await text('Backend WebSocket URL for local dev', { default: 'ws://localhost:8080/ws' });
  upsertEnvFile(path.join(VAK_CLIENT, '.env'), {
    VITE_WS_URL: wsUrl,
    VITE_BUSINESS_NAME: businessName || undefined,
  });
  success(`Wrote ${path.relative(ROOT, path.join(VAK_CLIENT, '.env'))}`);

  // ── AWS deployment (optional) ────────────────────────────────────────────
  heading('AWS deployment (optional — you can run this later with `./vak deploy`)');
  const setupAws = await confirm('Configure AWS deployment settings now?', { default: false });
  if (setupAws) {
    const region = await text('AWS region', { default: 'us-west-2' });
    const useDomain = await confirm('Do you have a custom domain in Route 53 to use?', { default: false });
    let domainName, hostedZoneDomain;
    if (useDomain) {
      domainName = await text('Full API domain (e.g. voice.example.com)');
      hostedZoneDomain = await text('Route 53 hosted zone (e.g. example.com)');
    }
    const useWaf = await confirm('Protect the API with a WAF API key?', { default: false });
    let apiKey;
    if (useWaf) {
      apiKey = crypto.randomBytes(24).toString('hex');
      info(`Generated API key: ${color.bold(apiKey)} (also saved to VakInfra/.env)`);
    }
    upsertEnvFile(path.join(VAK_INFRA, '.env'), {
      AWS_REGION: region,
      BUSINESS_NAME: businessName || undefined,
      BUSINESS_VERTICAL: useCase === 'custom' ? 'generic' : useCase,
      DOMAIN_NAME: domainName,
      HOSTED_ZONE_DOMAIN: hostedZoneDomain,
      API_KEY: apiKey,
    });
    success(`Wrote ${path.relative(ROOT, path.join(VAK_INFRA, '.env'))}`);
  } else {
    info('Skipped — run `./vak deploy` whenever you\'re ready.');
  }

  closePrompt();

  heading('Ready');
  console.log(`  ${color.cyan('./vak dev')}      Start the backend + web client locally`);
  console.log(`  ${color.cyan('./vak deploy')}   Deploy to AWS when you're ready`);
  console.log(`  ${color.cyan('./vak doctor')}   Re-check your environment any time`);
  console.log('');
}

module.exports = { init };

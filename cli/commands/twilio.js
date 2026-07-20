'use strict';

const path = require('node:path');
const { heading, success, info, warn, fail, color } = require('../lib/theme');
const { text, password, select, confirm, closePrompt } = require('../lib/prompt');
const { upsertEnvFile, readEnvFile } = require('../lib/env-file');
const { ROOT, VAK_DEEPGRAM, VAK_INFRA } = require('../lib/paths');

const TWILIO_API_BASE = 'https://api.twilio.com/2010-04-01';

function basicAuthHeader(user, pass) {
  return 'Basic ' + Buffer.from(`${user}:${pass}`).toString('base64');
}

async function twilioRequest(method, urlPath, { user, pass, body } = {}) {
  const res = await fetch(`${TWILIO_API_BASE}${urlPath}`, {
    method,
    headers: {
      Authorization: basicAuthHeader(user, pass),
      ...(body ? { 'Content-Type': 'application/x-www-form-urlencoded' } : {}),
    },
    body: body ? new URLSearchParams(body).toString() : undefined,
  });
  let data;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const message = (data && (data.message || data.detail)) || `HTTP ${res.status}`;
    throw new Error(message);
  }
  return data;
}

async function twilio(args) {
  heading('vak twilio');
  info('Points a Twilio phone number\'s webhooks at this VakDeepGram backend.');
  info('This changes a real, live Twilio number — you\'ll confirm before anything is applied.');

  const deepgramEnvPath = path.join(VAK_DEEPGRAM, '.env');
  const deepgramEnv = readEnvFile(deepgramEnvPath);

  let accountSid = deepgramEnv.TWILIO_ACCOUNT_SID;
  let authToken = deepgramEnv.TWILIO_AUTH_TOKEN;
  let savedNewCreds = false;

  heading('Account');
  if (accountSid) {
    info(`Using Twilio Account SID from VakDeepGram/.env: ${accountSid}`);
  } else {
    accountSid = await text('Twilio Account SID');
    savedNewCreds = true;
  }
  if (!authToken) {
    authToken = await password('Twilio Auth Token');
    savedNewCreds = true;
  }

  info('');
  info('For listing/updating phone numbers, you can use your main Auth Token, or a');
  info('scoped API Key (Twilio console → Account → API keys & tokens) — recommended,');
  info('since it can be revoked independently and never needs to live in this app\'s');
  info('runtime environment (only the Auth Token does, for webhook signature checks).');
  const useApiKey = await confirm('Use a scoped API Key for this instead of the Auth Token?', { default: false });
  let authUser = accountSid;
  let authPass = authToken;
  if (useApiKey) {
    authUser = await text('API Key SID (starts with SK)');
    authPass = await password('API Key Secret');
  }

  // ── List numbers ──────────────────────────────────────────────────────────
  heading('Phone number');
  let numbers;
  try {
    const data = await twilioRequest('GET', `/Accounts/${accountSid}/IncomingPhoneNumbers.json?PageSize=50`, {
      user: authUser,
      pass: authPass,
    });
    numbers = data.incoming_phone_numbers || [];
  } catch (err) {
    fail(`Couldn't reach Twilio: ${err.message}`);
    fail('Check your Account SID / Auth Token (or API Key) and try again.');
    closePrompt();
    process.exitCode = 1;
    return;
  }

  if (numbers.length === 0) {
    warn('No phone numbers found on this account.');
    info('Buy one at https://console.twilio.com/us1/develop/phone-numbers/manage/search first.');
    closePrompt();
    return;
  }

  const numberChoices = numbers.map((n) => ({
    value: n.sid,
    label: `${n.phone_number}${n.friendly_name && n.friendly_name !== n.phone_number ? ` (${n.friendly_name})` : ''}`,
  }));
  const selectedSid = await select('Which number should point at Vak?', numberChoices, {
    default: numberChoices[0].value,
  });
  const selected = numbers.find((n) => n.sid === selectedSid);

  // ── Base URL ─────────────────────────────────────────────────────────────
  heading('Backend URL');
  info('Twilio needs a public HTTPS URL — not localhost. Use your deployed');
  info('VakInfra URL, or a tunnel (e.g. ngrok) for local testing.');
  const infraEnv = readEnvFile(path.join(VAK_INFRA, '.env'));
  const suggestedBase = infraEnv.DOMAIN_NAME ? `https://${infraEnv.DOMAIN_NAME}` : '';
  const baseUrl = (
    await text('Backend base URL', suggestedBase ? { default: suggestedBase } : {})
  ).replace(/\/+$/, '');

  if (!baseUrl) {
    fail('A base URL is required.');
    closePrompt();
    process.exitCode = 1;
    return;
  }
  if (!baseUrl.startsWith('https://')) {
    warn('Twilio requires HTTPS for webhooks in practice — an http:// URL will likely fail.');
  }

  const voiceUrl = `${baseUrl}/twilio/twiml`;
  const smsUrl = `${baseUrl}/twilio-chat`;

  heading('Review');
  console.log(`  Number:       ${color.bold(selected.phone_number)}`);
  console.log(`  Voice webhook: ${selected.voice_url || '(none)'}  →  ${color.cyan(voiceUrl)}`);
  console.log(`  SMS webhook:   ${selected.sms_url || '(none)'}  →  ${color.cyan(smsUrl)}`);
  const proceed = await confirm('Apply these webhook URLs to the number above?', { default: false });
  if (!proceed) {
    info('Cancelled — no changes made.');
    closePrompt();
    return;
  }

  try {
    await twilioRequest('POST', `/Accounts/${accountSid}/IncomingPhoneNumbers/${selectedSid}.json`, {
      user: authUser,
      pass: authPass,
      body: {
        VoiceUrl: voiceUrl,
        VoiceMethod: 'POST',
        SmsUrl: smsUrl,
        SmsMethod: 'POST',
      },
    });
  } catch (err) {
    fail(`Failed to update the number: ${err.message}`);
    closePrompt();
    process.exitCode = 1;
    return;
  }
  success(`${selected.phone_number} now routes calls and texts to this backend.`);

  const updates = { TWILIO_BUSINESS_NUMBER: selected.phone_number };
  if (savedNewCreds) {
    updates.TWILIO_ACCOUNT_SID = accountSid;
    updates.TWILIO_AUTH_TOKEN = authToken;
  }
  upsertEnvFile(deepgramEnvPath, updates);
  success(`Wrote ${path.relative(ROOT, deepgramEnvPath)}`);

  closePrompt();

  heading('Security checklist');
  info('- Keep TWILIO_SIGNATURE_VERIFICATION_ENABLED=true (the default) in production —');
  info('  requests without a valid Twilio signature are rejected, not just logged.');
  info('- For a real deploy, store the Auth Token in Secrets Manager instead of plaintext:');
  info('  see VakInfra/README.md\'s twilioAuthTokenSecretArn option.');
  info('- Consider `-c enableTwilioOnlyAccess=true` on `./vak deploy` to restrict the');
  info('  ALB to Twilio\'s published IP ranges if this deployment only serves calls/SMS.');
  info('See docs/TWILIO.md for the full security model.');
}

module.exports = { twilio };

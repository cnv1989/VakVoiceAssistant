# Configuration Reference

Each component reads its own `.env` file. `./vak init` generates all three;
this page documents every variable in full, for when you need more than the
wizard asks.

## VakDeepGram (`VakDeepGram/.env`)

### Business profile

| Variable | Default | Description |
|---|---|---|
| `BUSINESS_NAME` | — | Used in greetings and the generated system prompt |
| `BUSINESS_VERTICAL` | `generic` | `generic`, `barber`, `salon`, `spa`, `medical`, `fitness`, `home_services` — see [CUSTOMIZING_YOUR_AGENT.md](./CUSTOMIZING_YOUR_AGENT.md) |
| `BUSINESS_ROLE_DESCRIPTION` | — | Full override for the agent's role sentence, bypassing the vertical preset |

### AI model (LLM provider)

Powers the `/chat` endpoint and voice function-calling (the Strands Agent
that decides when to check availability, book an appointment, etc.). This
is separate from Deepgram's own STT/TTS and from the Deepgram Voice Agent's
internal LLM bridge (`DEEPGRAM_THINKING_PROVIDER` below).

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `bedrock` | `bedrock` (AWS Bedrock/Claude — uses your AWS credentials, no key here), `anthropic` (direct Anthropic API), or `openai` (direct OpenAI API) |
| `LLM_MODEL_ID` | provider default | Override the model (e.g. `claude-sonnet-4-5`, `gpt-4o`, a Bedrock inference profile ID) |
| `ANTHROPIC_API_KEY` | — | Required if `LLM_PROVIDER=anthropic` |
| `OPENAI_API_KEY` | — | Required if `LLM_PROVIDER=openai` |
| `BEDROCK_MAX_TOKENS` / `BEDROCK_TEMPERATURE` | `8192` / `0.4` | Generation settings, shared across all three providers despite the name |

Adding another Strands-supported provider (Gemini, Mistral, Ollama, ...)
just needs a branch in
[`VakDeepGram/src/vakdeepgram/llm.py`](../VakDeepGram/src/vakdeepgram/llm.py)
— every call site already asks that module for "the configured model."

### Deepgram (speech-to-text and voice text-to-speech)

| Variable | Default | Description |
|---|---|---|
| `DEEPGRAM_API_KEY` | — | **Required.** [console.deepgram.com](https://console.deepgram.com) |
| `DEEPGRAM_PROJECT_ID` | — | Optional Deepgram project ID |
| `DEEPGRAM_AGENT_ID` | — | Optional — leave empty to create the agent dynamically |
| `DEEPGRAM_AGENT_LANGUAGE` | `en` | |
| `DEEPGRAM_LISTENING_MODEL` | `flux-general-en` | STT model |
| `DEEPGRAM_LISTENING_VERSION` | `v2` | |
| `DEEPGRAM_THINKING_PROVIDER` | `google` | LLM bridge used *inside* the Deepgram Voice Agent (voice calls only). Accepts any provider type Deepgram's Voice Agent API supports — `open_ai`, `anthropic`, `google`, `amazon_bedrock`, and others as Deepgram adds them — passed straight through |
| `DEEPGRAM_THINKING_MODEL` | `gemini-2.0-flash` | |
| `DEEPGRAM_SPEAKING_PROVIDER` | `eleven_labs` | `eleven_labs` and `deepgram` (Aura) have first-class field mapping; any other value Deepgram's Voice Agent API supports (e.g. `cartesia`) is passed through generically via the fields below |
| `DEEPGRAM_SPEAKING_MODEL_ID` | `eleven_flash_v2_5` | Used when the speaking provider is `eleven_labs`, or as the generic "model_id" field for other providers |
| `DEEPGRAM_SPEAKING_VOICE_ID` | — | ElevenLabs voice ID, or the generic "voice_id" field for other providers |
| `DEEPGRAM_SPEAKING_MODEL` | — | Used when the speaking provider is `deepgram` (e.g. `aura-2-odysseus-en`), or as the generic "model" field for other providers |
| `DEEPGRAM_INPUT_SAMPLE_RATE` | `48000` | Must match the client's capture rate |
| `DEEPGRAM_OUTPUT_SAMPLE_RATE` | `24000` | |
| `DEEPGRAM_STS_TIMEOUT_SECONDS` | `300` | |
| `DEEPGRAM_AGENT_GREETING` | `"Hi, how can I help you today?"` | Fallback greeting until business context resolves a name |

### Server

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | |
| `PORT` | `8080` | |
| `LOG_LEVEL` | `INFO` | |
| `WORKERS` | `2` | |
| `ENVIRONMENT` | `development` | `development`, `staging`, or `production` |

### Local test mode

| Variable | Default | Description |
|---|---|---|
| `OAUTH_ALLOW_LOCALHOST_NOAUTH` | `false` | When `true` **and** `ENVIRONMENT=development`, serves a mock business (fake hours/services/staff) with no DynamoDB or Square/Setmore account needed. This is what `./vak init`'s "local test mode" sets. |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `CHAT_API_KEY` | — | Bearer key required on `/chat`. Unset = no auth (fine for local dev only) |
| `OAUTH_JWKS_URL` / `OAUTH_ISSUER` / `OAUTH_AUDIENCE` / `OAUTH_REQUIRED_SCOPE` | — | JWT validation for OAuth-protected endpoints |
| `CORS_ALLOWED_ORIGINS` | (allow all) | Comma-separated list; set explicitly in production |
| `RATE_LIMIT_PER_MINUTE` | `100` | Per-IP request rate limit |
| `MAX_WEBSOCKET_CONNECTIONS_PER_IP` | `10` | |

### Twilio (optional — phone, SMS, WhatsApp)

| Variable | Default | Description |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | — | |
| `TWILIO_AUTH_TOKEN` | — | Required for signature verification and sending SMS |
| `TWILIO_SIGNATURE_VERIFICATION_ENABLED` | `true` | Set `false` only for local testing |
| `TWILIO_FROM_NUMBER` | — | Outbound SMS sender (defaults to the business number) |
| `TWILIO_BUSINESS_NUMBER` | — | Inbound Twilio number |
| `TWILIO_WHATSAPP_NUMBER` | Twilio sandbox number | |

### Providers, storage, and AWS

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `us-west-2` | |
| `SQUARE_ENVIRONMENT` | `production` | `sandbox` or `production` |
| `SQUARE_ACCOUNT_TABLE`, `SETMORE_ACCOUNT_TABLE`, `BUSINESS_NUMBER_TABLE`, `BUSINESS_AUTOMATIONS_TABLE`, `CALL_RECORD_TABLE`, `VOICE_CUSTOMER_TABLE`, `USER_BOOKING_LINK_TABLE` | `Vak-<Model>-production` | DynamoDB table names — match what VakInfra's CDK stack creates by default |
| `RECORDINGS_BUCKET` | — | S3 bucket for call transcripts/recordings; unset disables uploads |
| `RECORDINGS_KEY_PREFIX` | `call-sessions` | |
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-opus-4-6-v1` | |
| `BEDROCK_MAX_TOKENS` / `BEDROCK_TEMPERATURE` | `8192` / `0.4` | |
| `AGENTCORE_MEMORY_ID` | — | Optional Bedrock AgentCore Memory for chat session persistence |

## VakClient (`VakClient/.env`)

| Variable | Default | Description |
|---|---|---|
| `VITE_WS_URL` | `ws://localhost:8080/ws` | Backend WebSocket URL for the voice page |
| `VITE_CHAT_API_URL` | — | Backend URL for the chat page's "Deployed" option |
| `VITE_BUSINESS_NAME` | `Vak Assistant` | Shown in the header and chat page |

## VakInfra (`VakInfra/.env`)

See [VakInfra/README.md](../VakInfra/README.md#configuration) for the full
context/env-var reference (region, domain, WAF, Cognito, table imports,
etc.) — `./vak deploy` reads this file automatically.

## Connecting a real Square or Setmore account

Local test mode is enough to try Vak end-to-end, but it doesn't touch real
booking data. Wiring up a live business account is a separate, deliberately
manual step because it involves per-business credentials:

- **Setmore**: use `VakDeepGram/scripts/seed_setmore_account.py` to write a
  refresh token into the `SetmoreAccount` table, and a matching record in
  `BusinessNumber` mapping your Twilio/business phone number to that
  account. Run `python -m scripts.seed_setmore_account --help` for options.
- **Square**: Square accounts are connected via OAuth and stored in the
  `SquareAccount` table the same way. If you're not already running a
  companion dashboard app that handles the OAuth flow, you'll need to
  implement that handshake yourself — see `providers/square/` and
  `utils/square_client.py` for the client Vak uses once credentials exist.

Once seeded, set `ENVIRONMENT=production` and
`OAUTH_ALLOW_LOCALHOST_NOAUTH=false` so VakDeepGram resolves business
context from DynamoDB instead of the local mock.

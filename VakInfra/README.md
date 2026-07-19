# VakInfra

AWS CDK v2 (TypeScript) infrastructure for the Vak voice assistant. One
`cdk deploy` stands up everything VakDeepGram needs — VPC, ECR repo, ECS
Fargate service, ALB, DynamoDB tables, and an S3 bucket — with no external
dependencies. Custom domain/TLS, WAF, and Cognito auth are all optional
opt-ins layered on top of that baseline.

For the guided version of everything below, run `./vak deploy` from the repo
root instead — it wraps the same CDK commands with prompts. See
[docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) for the full walkthrough and
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for how the pieces fit
together.

## Stacks

| Stack | Contents |
|---|---|
| `<name>NetworkStack` | VPC (2 AZs, 1 NAT gateway), ECR repository |
| `<name>AppStack` | ECS Fargate service, ALB, DynamoDB tables, S3 bucket, IAM roles, optional WAF/TLS/Cognito |
| `<name>MonitoringStack` | CloudWatch dashboards, alarms, SNS topic |

`<name>` defaults to `Vak` (override with `-c stackName=...`).

## Prerequisites

- Node.js 20+
- AWS CLI configured with credentials for the target account
- AWS CDK CLI: `npm install -g aws-cdk` (or use `npx cdk`)
- A Deepgram API key ([console.deepgram.com](https://console.deepgram.com))

## Quick deploy

```bash
npm install

# One-time per account/region:
cdk bootstrap

# Deploy with just a Deepgram key — everything else uses sane defaults.
cdk deploy --all -c deepgramApiKey=YOUR_DEEPGRAM_KEY
```

This gives you a working HTTP/WS endpoint (`AlbDns` output) you can point
`VakClient`'s `VITE_WS_URL` at immediately. Add a custom domain and TLS
whenever you're ready to go live — see below.

Then build and push the VakDeepGram image (see
[`../VakDeepGram/deploy-to-ecr.sh`](../VakDeepGram/deploy-to-ecr.sh)) and
force a new ECS deployment to pick it up:

```bash
cd ../VakDeepGram && ./deploy-to-ecr.sh
aws ecs update-service --cluster vak-cluster-production --service <service-name> --force-new-deployment
```

## Configuration

Everything is passed as CDK context (`-c key=value`) or an equivalent
environment variable — use whichever fits your workflow (context for
one-offs, env vars for CI). Context takes precedence when both are set.

| Context key | Env var | Default | Description |
|---|---|---|---|
| `stackName` | `VAK_STACK_NAME` | `Vak` | Prefix for all stack/resource names |
| `stage` | `VAK_STAGE` | `production` | Logical environment label (used in resource names/tags) |
| `awsRegion` | `AWS_REGION` | `us-west-2` | Deployment region |
| `imageTag` | `IMAGE_TAG` | `latest` | ECR image tag to deploy |
| `ecrRepositoryName` | `ECR_REPOSITORY_NAME` | `vak-deepgram` | ECR repo name (created by the network stack) |
| `deepgramApiKey` | `DEEPGRAM_API_KEY` | — | Deepgram API key (plaintext; fine for a first deploy) |
| `deepgramApiKeySecretArn` | `DEEPGRAM_API_KEY_SECRET_ARN` | — | Secrets Manager ARN instead of plaintext (recommended for production) |
| `llmProvider` | `LLM_PROVIDER` | `bedrock` | `bedrock` (default, no key needed), `anthropic`, or `openai` — see [docs/CONFIGURATION.md](../docs/CONFIGURATION.md) |
| `llmModelId` | `LLM_MODEL_ID` | — | Overrides the provider's default model ID |
| `anthropicApiKey` / `anthropicApiKeySecretArn` | `ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY_SECRET_ARN` | — | Required if `llmProvider=anthropic` |
| `openaiApiKey` / `openaiApiKeySecretArn` | `OPENAI_API_KEY` / `OPENAI_API_KEY_SECRET_ARN` | — | Required if `llmProvider=openai` |
| `deepgramSpeakingProvider` | `DEEPGRAM_SPEAKING_PROVIDER` | `eleven_labs` | TTS voice provider — `eleven_labs`, `deepgram`, or any other Deepgram's Voice Agent API supports |
| `deepgramSpeakingModelId` / `deepgramSpeakingVoiceId` | `DEEPGRAM_SPEAKING_MODEL_ID` / `DEEPGRAM_SPEAKING_VOICE_ID` | ElevenLabs defaults | Voice selection, forwarded as-is |
| `deepgramThinkingProvider` / `deepgramThinkingModel` | `DEEPGRAM_THINKING_PROVIDER` / `DEEPGRAM_THINKING_MODEL` | `google` / `gemini-2.5-flash` | LLM bridge *inside* the Deepgram Voice Agent (independent of `llmProvider`) |
| `businessName` | `BUSINESS_NAME` | — | Forwarded to the container as `BUSINESS_NAME` |
| `businessVertical` | `BUSINESS_VERTICAL` | `generic` | Forwarded as `BUSINESS_VERTICAL` — see [docs/CUSTOMIZING_YOUR_AGENT.md](../docs/CUSTOMIZING_YOUR_AGENT.md) |
| `businessRoleDescription` | `BUSINESS_ROLE_DESCRIPTION` | — | Full custom persona override, bypassing `businessVertical` presets |
| `domainName` | `DOMAIN_NAME` | — | Custom API domain, e.g. `voice.example.com` |
| `hostedZoneDomain` | `HOSTED_ZONE_DOMAIN` | — | Name of an **existing** Route 53 public hosted zone that owns `domainName`; CDK creates a DNS-validated cert + A record automatically |
| `certificateArn` | `CERTIFICATE_ARN` | — | Use a pre-existing ACM certificate instead of `hostedZoneDomain` |
| `apiKey` | `API_KEY` | — | Require `X-Api-Key` header (enforced by WAF) on all requests except `/health` |
| `enableTwilioOnlyAccess` | `ENABLE_TWILIO_ONLY_ACCESS` | `false` | Restrict the ALB to Twilio's published Media Streams IP ranges |
| `twilioAccountSid` | `TWILIO_ACCOUNT_SID` | — | Forwarded to the container |
| `twilioFromNumber` | `TWILIO_FROM_NUMBER` | — | Forwarded to the container |
| `twilioAuthToken` | `TWILIO_AUTH_TOKEN` | — | Plaintext (fine for a first deploy) |
| `twilioAuthTokenSecretArn` | `TWILIO_AUTH_TOKEN_SECRET_ARN` | — | Secrets Manager ARN instead of plaintext |
| `chatApiKey` | `CHAT_API_KEY` | — | Bearer key required on `/chat` (omit to leave `/chat` unauthenticated — fine for local testing only) |
| `cognitoDomainPrefix` | `COGNITO_DOMAIN_PREFIX` | — | Enables Cognito hosted-UI auth in front of `/ws` and `/chat` at the ALB layer (requires `domainName`) |
| `alarmEmail` | `ALARM_EMAIL` | — | Email address subscribed to CloudWatch alarm notifications (no subscription created if omitted) |

### Bringing your own tables

If you already run a separate business-management app that owns the
Square/Setmore account tables, import them instead of letting this stack
create fresh ones:

| Context key | Env var |
|---|---|
| `squareAccountTable` | `EXISTING_SQUARE_ACCOUNT_TABLE` |
| `setmoreAccountTable` | `EXISTING_SETMORE_ACCOUNT_TABLE` |
| `businessNumberTable` | `EXISTING_BUSINESS_NUMBER_TABLE` |
| `businessAutomationsTable` | `EXISTING_BUSINESS_AUTOMATIONS_TABLE` |
| `callRecordTable` | `EXISTING_CALL_RECORD_TABLE` |
| `voiceCustomerTable` | `EXISTING_VOICE_CUSTOMER_TABLE` |
| `userBookingLinkTable` | `EXISTING_USER_BOOKING_LINK_TABLE` |

Any table left unset gets created fresh by this stack with the schema
VakDeepGram expects (see [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)).

## Custom domain + TLS

```bash
cdk deploy --all \
  -c deepgramApiKey=YOUR_DEEPGRAM_KEY \
  -c domainName=voice.example.com \
  -c hostedZoneDomain=example.com
```

This requires `example.com` to already be a Route 53 public hosted zone in
the same account. CDK creates a DNS-validated ACM certificate, an HTTPS
listener, and an A record automatically. Prefer to manage certificates
yourself? Pass `-c certificateArn=...` instead of `hostedZoneDomain`.

Without a domain, the stack still serves plain HTTP/WS on the ALB's
auto-generated DNS name — convenient for testing, not recommended for
production (no encryption in transit).

## WAF API key protection

```bash
cdk deploy --all -c deepgramApiKey=YOUR_DEEPGRAM_KEY -c apiKey=$(openssl rand -hex 32)
```

Every request other than `/health` must include a matching `X-Api-Key`
header, enforced by a WAF WebACL in front of the ALB.

## Twilio-only access

If the deployment only needs to accept Twilio Media Stream connections (no
direct browser client), lock the ALB down to Twilio's published IP ranges:

```bash
cdk deploy --all -c deepgramApiKey=YOUR_DEEPGRAM_KEY -c enableTwilioOnlyAccess=true
```

## Useful commands

```bash
npm run synth   # cdk synth — render CloudFormation without deploying
npm run diff    # cdk diff — preview changes against the deployed stack
npm run deploy  # cdk deploy
```

## Outputs

| Output | Description |
|---|---|
| `ApiUrl` | `https://` (or `http://` without a cert) base URL |
| `WebSocketUrl` | WebSocket URL — set as `VakClient`'s `VITE_WS_URL` |
| `AlbDns` | Raw ALB DNS name |
| `EcsCluster` | ECS cluster name (for `aws ecs update-service`) |
| `EcrRepositoryUri` | Push VakDeepGram images here |

## CI/CD

`.github/workflows/deploy-vak-infra.yml` deploys on push to `main` when
files under `VakInfra/` change, using an OIDC role (`AWS_ROLE_ARN` secret).
Run `cdk bootstrap` once in the target account/region before the first
automated deploy.

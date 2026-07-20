# Twilio phone integration

Vak can answer real phone calls and texts through a Twilio phone number:
Twilio streams call audio to `WebSocket /twilio` and posts SMS to
`POST /twilio-chat`, both handled by VakDeepGram. This doc covers how to
connect a number, and the security model behind it.

## Quick start

```bash
./vak twilio
```

This is the connector: it lists the phone numbers on your Twilio account,
asks which one to use, and points that number's Voice and SMS webhooks at
your VakDeepGram backend. It shows you the before/after URLs and asks for
confirmation before changing anything — it's editing a live Twilio
resource, not local config.

Prerequisites:

- A Twilio account with at least one phone number (buy one in the
  [Twilio console](https://console.twilio.com/us1/develop/phone-numbers/manage/search)
  if you don't have one yet).
- Your Twilio **Account SID** and **Auth Token**, or a scoped **API Key**
  (see below). `./vak init` asks for these up front if you opt in to
  Twilio during setup; otherwise `./vak twilio` will prompt for them and
  save them to `VakDeepGram/.env`.
- A public HTTPS URL for VakDeepGram — a real deployment
  (`./vak deploy`), or a tunnel like [ngrok](https://ngrok.com) for local
  testing. Twilio cannot reach `localhost`.

Re-run `./vak twilio` any time you change domains or want to point a
different number at Vak.

## What gets configured

For the selected number, `./vak twilio` sets:

| Webhook | URL | Handles |
|---|---|---|
| Voice | `{base}/twilio/twiml` | Inbound calls — returns TwiML that connects the call to the `/twilio` media-streaming WebSocket |
| SMS | `{base}/twilio-chat` | Inbound texts — routed to the AI agent, which can reply by SMS |

It also writes `TWILIO_BUSINESS_NUMBER` (and, if you entered them fresh,
`TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`) to `VakDeepGram/.env`. See
[docs/CONFIGURATION.md](./CONFIGURATION.md#twilio-optional--phone-sms-whatsapp)
for the full list of Twilio-related variables.

## Security model

Twilio webhooks are unauthenticated HTTP/WebSocket requests from Twilio's
infrastructure to a public URL. Anyone who finds that URL can send it
fake requests unless it's verified. Vak's defenses, in order:

### 1. Twilio request signature verification (on by default)

Every Twilio-facing endpoint — `/twilio/twiml`, `/twilio-chat`,
`/whatsapp-chat`, and the `/twilio` WebSocket — validates Twilio's
`X-Twilio-Signature` header using your `TWILIO_AUTH_TOKEN`
([`twilio.request_validator.RequestValidator`](https://www.twilio.com/docs/usage/security#validating-requests)).
This proves the request actually came from Twilio and wasn't tampered
with in transit.

- Controlled by `TWILIO_SIGNATURE_VERIFICATION_ENABLED` (default `true`).
  Leave it on in any deployment that's reachable from the internet.
- **If `TWILIO_AUTH_TOKEN` isn't set, verification fails closed** —
  requests are rejected, not silently allowed through. A missing secret
  can never be mistaken for a verified request.
- The HTTP webhooks (`/twilio/twiml`, `/twilio-chat`, `/whatsapp-chat`)
  additionally only *enforce* rejection when `ENVIRONMENT=production`;
  outside production a failed check is logged as a warning but still
  allowed, so you can exercise the endpoints locally without real Twilio
  signatures. `/twilio/twiml` enforces on any failed check regardless of
  environment. Keep `ENVIRONMENT=production` set on real deployments —
  `./vak deploy` does this for you.

### 2. Network-level allowlisting (optional, recommended for phone-only deployments)

If a deployment exists only to serve Twilio calls/SMS — nothing else
hits it directly — restrict the load balancer to
[Twilio's published IP ranges](https://www.twilio.com/docs/sip-trunking/ip-addresses)
with the WAF option:

```bash
./vak deploy -c enableTwilioOnlyAccess=true
```

This is defense in depth on top of signature verification, not a
replacement for it: it stops unrelated traffic from reaching the app at
all, including scans and volumetric abuse that a signature check alone
wouldn't prevent.

### 3. Credential handling

- **`TWILIO_AUTH_TOKEN`** must live in the VakDeepGram runtime — it's
  used to verify inbound signatures, so this is unavoidable. For a real
  deployment, don't put it in `VakInfra/.env` as plaintext; store it in
  AWS Secrets Manager and pass the ARN instead:
  `-c twilioAuthTokenSecretArn=arn:aws:secretsmanager:...` (see
  [VakInfra/README.md](../VakInfra/README.md#configuration)).
- **Managing the phone number itself** (what `./vak twilio` does — listing
  numbers, updating webhook URLs) is a separate concern from verifying
  inbound webhooks, and needs different credentials. You can use the same
  Account SID + Auth Token, or — recommended — a
  [scoped API Key](https://www.twilio.com/docs/iam/api-keys) created in
  the Twilio console. An API Key can be revoked independently of your
  main Auth Token, is scoped to REST API access only, and never needs to
  be stored in VakDeepGram's runtime environment at all (it's only used
  interactively, by the CLI, on your machine, at connect time).
- Never commit `VakDeepGram/.env` — it's already gitignored. Treat the
  Auth Token and any API Key secret like any other credential.

### 4. Outbound SMS

`TWILIO_FROM_NUMBER` (falling back to `TWILIO_BUSINESS_NUMBER`) is the
sender for outbound SMS, e.g. booking confirmation links. There's no
built-in fallback to any number you don't own — if neither is set,
outbound SMS is refused rather than silently sent from an unconfigured
or arbitrary number.

## Multi-tenant / multiple numbers

VakDeepGram can route more than one Twilio number to different business
contexts via the `BusinessNumber` DynamoDB table, keyed by the inbound
`To` number — see
[VakDeepGram/README.md](../VakDeepGram/README.md#multi-tenant-sms--voice-routing).
`./vak twilio` covers the common single-number case; for multi-tenant
setups, register additional numbers directly in that table.

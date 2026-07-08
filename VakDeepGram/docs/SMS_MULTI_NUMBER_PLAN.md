# Multi-Number Twilio SMS & Voice Plan

Each Integrin customer (business) gets a dedicated Twilio phone number. That number handles both **inbound SMS** (AI text chat) and **inbound voice calls** (AI voice agent), and is also used as the `from` number for **outbound SMS** (booking links, confirmations).

---

## Current State

| Area | Status |
|------|--------|
| Inbound SMS routing | Working — `/twilio-chat` routes by `To` number |
| Inbound voice routing | Working — `/twilio` WebSocket routes by `customParameters.businessNumber` |
| Outbound SMS (booking links) | Working — `send_booking_link_sms()` via Twilio REST |
| Number provisioning | **Hardcoded** single number `+15104054454` in `generateBusinessNumber` Lambda |
| Webhook configuration | Manual — must be set per number in Twilio Console |
| A2P compliance | Documented only — no automation |

---

## Target Architecture

```
Customer's phone
       │
       │ calls or texts +1-XXX-YYY-ZZZZ  (business's dedicated number)
       ▼
  Twilio Cloud
       │
       ├─ SMS ──────────────────► POST https://your-domain.example.com/twilio-chat
       │                               ↓ lookup BusinessNumber by To
       │                               ↓ resolve business context
       │                               ↓ Strands AI agent responds
       │                               ↓ Twilio sends reply SMS
       │
       └─ Voice call ──────────► POST https://your-domain.example.com/twilio/twiml
                                       ↓ returns <Connect><Stream> TwiML
                                       ↓ Twilio opens WebSocket to /twilio
                                       ↓ lookup by customParameters.businessNumber
                                       ↓ resolve business context
                                       ↓ Deepgram Voice Agent answers
```

---

## Phase 1: Dynamic Number Provisioning

### Problem
`generateBusinessNumber` Lambda hardcodes a single number and will fail (or return an error) once it's assigned to any customer.

### Solution

Update `generateBusinessNumber` to:
1. Call Twilio REST API to search for an available local number in the customer's area
2. Purchase the number
3. Configure the number's webhooks (SMS + Voice) to point to VakDeepGram
4. Store the number in `BusinessNumber` table

#### Lambda changes (`amplify/functions/generateBusinessNumber/handler.ts`)

```typescript
import twilio from 'twilio';

const twilioClient = twilio(
  process.env.TWILIO_ACCOUNT_SID,
  process.env.TWILIO_AUTH_TOKEN
);

// 1. Search for available number (prefer matching area code of merchant)
const available = await twilioClient
  .availablePhoneNumbers('US')
  .local.list({ areaCode: merchantAreaCode, limit: 1 });

if (!available.length) throw new Error('No numbers available in requested area');

// 2. Purchase and configure webhooks
const purchased = await twilioClient.incomingPhoneNumbers.create({
  phoneNumber: available[0].phoneNumber,
  smsUrl: 'https://your-domain.example.com/twilio-chat',
  smsMethod: 'POST',
  voiceUrl: 'https://your-domain.example.com/twilio/twiml',
  voiceMethod: 'POST',
  friendlyName: `VakAI - ${merchantId ?? setmoreAccountId}`,
});

// 3. Store in DynamoDB
await client.models.BusinessNumber.create({
  phoneNumber: purchased.phoneNumber.replace('+1', ''),  // strip +1 for consistency
  countryCode: '+1',
  provider,
  twilioSid: purchased.sid,   // <-- new field needed in schema
  ...
});
```

#### Required environment variables (add to Amplify secrets)
```
TWILIO_ACCOUNT_SID  → already in use
TWILIO_AUTH_TOKEN   → already in use
```

#### BusinessNumber schema addition (`amplify/data/resource.ts`)
```typescript
twilioSid: a.string(),   // Twilio IncomingPhoneNumber SID (e.g. PN...)
```
This is needed to update or release the number later.

---

## Phase 2: VoiceTwiML Endpoint

### Problem
Twilio needs an HTTP endpoint to call first when a customer dials the business number. It expects a TwiML response that starts the media stream to VakDeepGram.

### Solution: Add `POST /twilio/twiml` to VakDeepGram

```python
@app.post("/twilio/twiml")
async def twilio_voice_twiml(request: Request):
    """Return TwiML that starts a Twilio Media Stream to /twilio WebSocket."""
    form = await request.form()
    to_number = form.get("To", "")
    # Strip +1 to match BusinessNumber table format
    business_number = to_number.lstrip("+1") if to_number.startswith("+1") else to_number

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://your-domain.example.com/twilio">
      <Parameter name="businessNumber" value="{business_number}"/>
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")
```

The `businessNumber` custom parameter is already read by the `/twilio` WebSocket handler's `start` event processing (`customParameters`).

**Webhook URL to configure per number:** `https://your-domain.example.com/twilio/twiml` (POST)

---

## Phase 3: Outbound SMS — Use Business Number as From

### Current behaviour
`send_booking_link_sms()` uses `config.settings.twilio_from_number` as an override, falling back to the `from_number` argument passed by the caller.

### Correct behaviour for multi-number
The `from_number` passed to `send_booking_link_sms()` comes from `connection_context["business_number"]`, which is already the customer's dedicated number. No code change is needed here **as long as provisioned numbers are E.164-formatted** consistently.

**Verify in `business_logic.py`:**
```python
from_number = config.settings.twilio_from_number or from_number
```
When `twilio_from_number` is `None` (production default), the business number from context is used correctly.

---

## Phase 4: A2P 10DLC Campaign (Per-Customer Compliance)

US carriers require approved A2P campaigns for 10DLC numbers sending SMS. See [`TWILIO_SMS_A2P_CAMPAIGN_SETUP.md`](./TWILIO_SMS_A2P_CAMPAIGN_SETUP.md) for the full manual registration steps.

### Multi-Tenant A2P Strategy (ISV Path)

As a software platform sending SMS on behalf of our customers, register as an **ISV** with Twilio's Messaging Services:

1. **One Messaging Service per customer** — each service maps to one A2P Campaign
2. **Add each number to its customer's Messaging Service Sender Pool**
3. When sending outbound SMS, use `messagingServiceSid` instead of a direct `from` number:
   ```python
   client.messages.create(
       messaging_service_sid="MGxxxxxxxxx",  # customer's service SID
       to=customer_phone,
       body=message_body
   )
   ```

#### Schema addition
```typescript
twilioMessagingServiceSid: a.string(),  // set after campaign approval
```

#### Automation via `generateBusinessNumber` Lambda
After provisioning a number, auto-create a Messaging Service:
```typescript
const service = await twilioClient.messaging.v1.services.create({
  friendlyName: `VakAI SMS - ${merchantId}`,
  inboundRequestUrl: 'https://your-domain.example.com/twilio-chat',
});
await twilioClient.messaging.v1.services(service.sid)
  .phoneNumbers.create({ phoneNumberSid: purchased.sid });
```

**Note:** Brand + Campaign registration still requires manual steps in Twilio Console until Twilio's ISV-specific automation APIs are available.

---

## Phase 5: Number Lifecycle Management (Integrin UI)

### BusinessNumber management UI (future)

Add to the Automations page or a dedicated Phone Numbers page:

| Feature | Description |
|---------|-------------|
| **Provision number** | One-click "Get AI Phone Number" — calls `generateBusinessNumber` |
| **Number status** | Shows number, A2P status (pending/approved), SMS/voice enabled |
| **Release number** | Calls Twilio API to release number, clears BusinessNumber record |
| **Re-provision** | If number released or ported, provision a new one |
| **A2P status link** | Deep link to Twilio Console campaign page |

---

## Webhook URL Reference

| Endpoint | Purpose | Configure on |
|----------|---------|-------------|
| `POST https://your-domain.example.com/twilio-chat` | Inbound SMS webhook | Each Twilio number's SMS URL |
| `POST https://your-domain.example.com/twilio/twiml` | Voice call → TwiML response | Each Twilio number's Voice URL |
| `WSS https://your-domain.example.com/twilio` | Twilio Media Stream (voice audio) | Referenced in TwiML `<Stream url>` |

---

## Implementation Checklist

### Immediate (Phase 1 + 2)
- [ ] Add `POST /twilio/twiml` endpoint to VakDeepGram `main.py`
- [ ] Add `twilioSid` to `BusinessNumber` schema in `amplify/data/resource.ts`
- [ ] Update `generateBusinessNumber` Lambda to call Twilio API and configure webhooks
- [ ] Add `twilio` npm package as Lambda dependency
- [ ] Add `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` to Lambda environment via Amplify secrets
- [ ] Deploy VakDeepGram (for TwiML endpoint)
- [ ] Deploy Amplify backend (for Lambda + schema changes)

### Near-term (Phase 3 + 4)
- [ ] Add `twilioMessagingServiceSid` to `BusinessNumber` schema
- [ ] Create Messaging Service per customer in `generateBusinessNumber` Lambda
- [ ] Update outbound SMS (`send_booking_link_sms`) to use Messaging Service SID when available
- [ ] Begin ISV A2P Brand registration with Twilio
- [ ] Register Campaigns per customer once Brand is approved

### Future (Phase 5)
- [ ] Add Number Management section to Automations page or new page
- [ ] Display A2P approval status
- [ ] Add release/re-provision capability

---

## Security Notes

- **Signature verification:** All incoming Twilio webhooks are verified via HMAC-SHA1 using `TWILIO_AUTH_TOKEN`. The `/twilio/twiml` endpoint should also verify the Twilio signature (same pattern as `/twilio-chat`).
- **WAF rules:** VakInfra ALB WAF should allow Twilio's published IP ranges for `/twilio-chat` and `/twilio/twiml`. Current WAF config uses an opt-in IP allowlist — ensure Twilio's CIDRs are included or rely on signature verification alone.
- **Twilio credentials:** Never hardcode SID/token. Use Amplify secrets for Lambda, AWS SSM/Secrets Manager for ECS task env vars.

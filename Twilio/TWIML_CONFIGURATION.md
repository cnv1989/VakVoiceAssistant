# TwiML Configuration for Vak Voice Assistant

## Required TwiML Configuration

Your TwiML Bin **must** use the `/twilio` endpoint (not `/ws`) because:

1. **Different Protocol**: Twilio uses a different WebSocket message format than browser clients
2. **Audio Format**: Twilio sends/receives mulaw audio (8kHz), while browser clients use PCM16 (48kHz)
3. **Message Format**: Twilio uses `{"event": "start/media/stop"}` format, browser uses `{"action": "start-recording"}`

## Correct TwiML Configuration

### Basic Configuration (Recommended)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" />
    </Start>
    <Say>Connecting to voice assistant.</Say>
    <Pause length="30" />
</Response>
```

### Enhanced Configuration (Longer Conversations)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" />
    </Start>
    <Say>Welcome to your voice assistant. How can I help you today?</Say>
    <Pause length="60" />
</Response>
```

### Advanced Configuration (With Track Control)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="en-US">
        Welcome to your voice assistant. Please wait while we connect.
    </Say>
    <Start>
        <Stream 
            url="wss://vak.tutzi.ai/twilio" 
            track="both_tracks"
        />
    </Start>
    <Say voice="alice" language="en-US">
        Connected. How can I help you today?
    </Say>
    <Pause length="300" />
    <Say voice="alice" language="en-US">
        Thank you for calling. Goodbye.
    </Say>
</Response>
```

## Important Requirements

### 1. **Must Use WSS (Secure WebSocket)**
- ✅ **Correct**: `wss://vak.tutzi.ai/twilio`
- ❌ **Wrong**: `ws://vak.tutzi.ai/twilio` (Twilio requires HTTPS/WSS)

### 2. **Must Use `/twilio` Endpoint**
- ✅ **Correct**: `wss://vak.tutzi.ai/twilio`
- ❌ **Wrong**: `wss://vak.tutzi.ai/ws` (Browser endpoint, won't work with Twilio)

### 3. **SSL Certificate Required**
Your ALB must have a valid SSL certificate for `vak.tutzi.ai`:
- Certificate must be in ACM (us-west-2 region)
- Certificate must cover `*.tutzi.ai` or `vak.tutzi.ai`
- ALB must have HTTPS listener (port 443) configured

## Setup Steps

### 1. Create TwiML Bin in Twilio Console

1. Go to [Twilio Console](https://console.twilio.com/)
2. Navigate to **Runtime** → **TwiML Bins**
3. Click **Create new TwiML Bin**
4. Name: `Vak Voice Assistant`
5. Copy the XML content from above
6. **Important**: Ensure URL is `wss://vak.tutzi.ai/twilio`
7. Click **Create**

### 2. Configure Phone Number

1. Go to **Phone Numbers** → **Manage** → **Active numbers**
2. Click your Twilio phone number
3. Under **Voice & Fax**:
   - **A CALL COMES IN**: Select **TwiML Bin** → Choose `Vak Voice Assistant`
   - Or paste TwiML Bin URL directly

### 3. Verify DNS Configuration

Ensure DNS is configured:
```
vak.tutzi.ai → VakApp-VakAl-S9TUK4zMiO73-829936755.us-west-2.elb.amazonaws.com (CNAME)
```

### 4. Test Connection

1. Call your Twilio phone number
2. You should hear: "Connecting to voice assistant."
3. The call should connect to the WebSocket endpoint
4. You can speak and the AI should respond

## Troubleshooting

### Connection Fails

**Check:**
- ✅ DNS: `vak.tutzi.ai` resolves to ALB DNS name
- ✅ Certificate: Valid SSL certificate in ACM (us-west-2)
- ✅ ALB: HTTPS listener (port 443) is configured
- ✅ Endpoint: Using `/twilio` (not `/ws`)
- ✅ Protocol: Using `wss://` (not `ws://`)

**Test WebSocket manually:**
```bash
# Test WSS connection
wscat -c wss://vak.tutzi.ai/twilio
```

### Audio Issues

**Check:**
- ✅ ECS task is running and healthy
- ✅ WebSocket endpoint is receiving connections
- ✅ Audio conversion (mulaw ↔ PCM16) is working
- ✅ Deepgram session is active

**Check logs:**
```bash
aws logs tail VakAppStack-VakTaskDefinitionVakDeepGramLogGroupCD5846F3-O5EbLA6vdGt4 --follow --region us-west-2
```

### Twilio-Specific Issues

**Check Twilio Event Logs:**
1. Go to Twilio Console → Monitor → Logs → Calls
2. Click on your call
3. Check for WebSocket connection errors

**Common Errors:**
- `WebSocket connection failed`: Check SSL certificate and DNS
- `Connection timeout`: Check ALB security groups allow Twilio IPs
- `Invalid endpoint`: Ensure using `/twilio` endpoint

## Twilio Media Streams Protocol

The `/twilio` endpoint handles:

### Incoming Messages (from Twilio)
- `{"event": "connected"}` - Connection established
- `{"event": "start", "start": {"streamSid": "..."}}` - Stream started
- `{"event": "media", "media": {"payload": "...", "track": "inbound"}}` - Audio data (mulaw, base64)
- `{"event": "stop"}` - Stream ended

### Outgoing Messages (to Twilio)
- `{"event": "media", "streamSid": "...", "media": {"payload": "..."}}` - Audio data (mulaw, base64)
- `{"event": "clear", "streamSid": "..."}` - Clear audio buffer (barge-in)

## Security

1. **SSL/TLS**: Required for Twilio (WSS only)
2. **Firewall**: Consider whitelisting Twilio IPs if using security groups
3. **Rate Limiting**: Implement rate limiting on `/twilio` endpoint
4. **Monitoring**: Monitor WebSocket connections and audio streams

## Resources

- [Twilio Media Streams Docs](https://www.twilio.com/docs/voice/twiml/stream)
- [TwiML Bins Guide](https://www.twilio.com/docs/runtime/twiml-bins)
- [Twilio IP Ranges](https://www.twilio.com/docs/voice/ip-addresses)

# Twilio TwiML Bins for Vak Voice Assistant

This directory contains TwiML Bin configurations for connecting Twilio voice calls to the Vak WebSocket endpoint.

**⚠️ Important Note**: Twilio Media Streams **requires WSS (secure WebSocket)** - it does not support plain `ws://` connections. If your ALB is configured for HTTP-only (no certificate), Twilio integration will not work. You must have HTTPS/WSS enabled on your ALB for Twilio to connect.

## TwiML Bin Configuration

### Basic TwiML Bin (`twiml-bin.xml`)

Simple configuration that:
- Starts Media Streams to your WebSocket endpoint
- Plays a connection message
- Allows 30 seconds of conversation

**TwiML Content:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/ws" />
    </Start>
    <Say>Connecting to voice assistant.</Say>
    <Pause length="30" />
</Response>
```

### Enhanced TwiML Bin (`twiml-bin-with-parameters.xml`)

Enhanced version with:
- Welcome message
- Longer conversation window (60 seconds)
- Better user experience

## Setup Instructions

### 1. Create TwiML Bin in Twilio Console

1. Go to [Twilio Console](https://console.twilio.com/)
2. Navigate to **Runtime** → **TwiML Bins**
3. Click **Create new TwiML Bin**
4. Name it: `Vak Voice Assistant`
5. Copy the content from `twiml-bin.xml` or `twiml-bin-with-parameters.xml`
6. Click **Create**

### 2. Get TwiML Bin URL

After creating the TwiML Bin, you'll get a URL like:
```
https://handler.twilio.com/twiml/EHXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

### 3. Configure Twilio Phone Number

1. Go to **Phone Numbers** → **Manage** → **Active numbers**
2. Click on your Twilio phone number
3. Under **Voice & Fax**, set:
   - **A CALL COMES IN**: Select **TwiML Bin** → Choose your bin
   - Or use the TwiML Bin URL directly

### 4. Test the Connection

Call your Twilio phone number. The call should:
1. Connect to Twilio
2. Start Media Streams to `wss://vak.tutzi.ai/ws`
3. Stream audio bidirectionally between the call and your WebSocket endpoint

## WebSocket Endpoint Requirements

Your WebSocket endpoint (`wss://vak.tutzi.ai/ws`) must:

1. **Accept WebSocket connections** from Twilio Media Streams
2. **Handle Media Streams protocol**:
   - Receive JSON messages with audio data
   - Send JSON messages with audio data
   - Handle `connected`, `start`, `media`, `stop` events

3. **Audio Format**:
   - Input: PCMU (μ-law) or PCMA (A-law) audio
   - Output: PCMU (μ-law) or PCMA (A-law) audio
   - Sample rate: 8000 Hz (standard telephony)

## Twilio Media Streams Protocol

### Incoming Messages (from Twilio)

```json
{
  "event": "connected",
  "protocol": "Call",
  "version": "1.0",
  "streamSid": "MZxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

```json
{
  "event": "start",
  "sequenceNumber": "1",
  "start": {
    "accountSid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "callSid": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "tracks": {
      "inbound": {
        "pcmu": {
          "payloadType": 0
        }
      },
      "outbound": {
        "pcmu": {
          "payloadType": 0
        }
      }
    },
    "mediaFormat": {
      "encoding": "audio/x-mulaw",
      "sampleRate": 8000,
      "channels": 1
    },
    "streamSid": "MZxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
}
```

```json
{
  "event": "media",
  "sequenceNumber": "2",
  "media": {
    "track": "inbound",
    "chunk": "1",
    "timestamp": "1609459200",
    "payload": "base64-encoded-audio-data"
  }
}
```

### Outgoing Messages (to Twilio)

```json
{
  "event": "media",
  "streamSid": "MZxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "media": {
    "payload": "base64-encoded-audio-data"
  }
}
```

## Advanced Configuration

### Custom Parameters

You can pass custom parameters to your WebSocket endpoint:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/ws?caller={{From}}&amp;called={{To}}" />
    </Start>
    <Say>Connecting to voice assistant.</Say>
    <Pause length="30" />
</Response>
```

### Longer Conversations

Increase the pause duration for longer conversations:

```xml
<Pause length="300" />  <!-- 5 minutes -->
```

### Custom Greeting

Modify the greeting message:

```xml
<Say voice="alice" language="en-US">Welcome to your AI assistant. How can I help you today?</Say>
```

## Troubleshooting

### Connection Issues

1. **Check WebSocket endpoint**: Ensure `wss://vak.tutzi.ai/ws` is accessible
2. **Verify certificate**: Twilio requires valid SSL/TLS certificate
3. **Check firewall**: Ensure Twilio IPs can reach your endpoint

### Audio Issues

1. **Audio format**: Ensure your endpoint handles PCMU/PCMA format
2. **Sample rate**: Must be 8000 Hz for telephony
3. **Encoding**: Use base64 encoding for audio payloads

### Twilio IPs

Twilio uses specific IP ranges. If you have firewall rules, whitelist:
- [Twilio IP Ranges](https://www.twilio.com/docs/voice/ip-addresses)

## Security Considerations

1. **Authentication**: Consider adding API key authentication
2. **Rate limiting**: Implement rate limiting on your WebSocket endpoint
3. **Validation**: Validate incoming Twilio requests
4. **Monitoring**: Monitor WebSocket connections and audio streams

## Resources

- [Twilio Media Streams Documentation](https://www.twilio.com/docs/voice/twiml/stream)
- [TwiML Bins Documentation](https://www.twilio.com/docs/runtime/twiml-bins)
- [Twilio WebSocket Protocol](https://www.twilio.com/docs/voice/media-streams)

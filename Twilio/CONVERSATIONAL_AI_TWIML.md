# TwiML Configuration for Conversational AI

## Recommended Configuration for Conversational AI

This TwiML configuration is optimized for natural, flowing conversations with your AI assistant.

### Standard Conversational AI Configuration

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" track="both_tracks" />
    </Start>
    <Say voice="alice" language="en-US">
        Hello! I'm your AI assistant. How can I help you today?
    </Say>
    <Pause length="600" />
</Response>
```

**Features:**
- ✅ Stream starts immediately (bidirectional audio)
- ✅ Natural greeting from AI assistant
- ✅ 10-minute conversation window (600 seconds)
- ✅ Both audio tracks enabled (`track="both_tracks"`)
- ✅ Professional Alice voice

### Extended Conversational AI Configuration

For longer conversations or customer service scenarios:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="en-US">
        Connecting you to your AI assistant.
    </Say>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" track="both_tracks" />
    </Start>
    <Pause length="1800" />
    <Say voice="alice" language="en-US">
        Thank you for calling. Have a great day!
    </Say>
</Response>
```

**Features:**
- ✅ Connection message before stream starts
- ✅ 30-minute conversation window (1800 seconds)
- ✅ Professional closing message
- ✅ Both audio tracks enabled

### Minimal Configuration (AI Handles Everything)

If your AI assistant provides its own greeting:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" track="both_tracks" />
    </Start>
    <Pause length="600" />
</Response>
```

**Features:**
- ✅ Stream starts immediately
- ✅ No Twilio greeting (AI provides greeting)
- ✅ 10-minute conversation window
- ✅ Minimal interruption

## Configuration Options

### Stream Attributes

- `url`: **Required** - WebSocket endpoint (`wss://vak.tutzi.ai/twilio`)
- `track`: Optional - Audio tracks to stream
  - `"both_tracks"` - Both inbound (caller) and outbound (AI) audio (recommended)
  - `"inbound_track"` - Only caller audio
  - `"outbound_track"` - Only AI audio

### Say Element Options

- `voice`: Voice to use
  - `"alice"` - Natural female voice (recommended)
  - `"man"` - Male voice
  - `"woman"` - Female voice
- `language`: Language code
  - `"en-US"` - US English (recommended)
  - `"en-GB"` - British English
  - `"es-ES"` - Spanish

### Pause Length

- `30` - 30 seconds (short test)
- `300` - 5 minutes (standard)
- `600` - 10 minutes (recommended for conversations)
- `1800` - 30 minutes (extended conversations)

## Setup Instructions

### 1. Create TwiML Bin

1. Go to [Twilio Console](https://console.twilio.com/)
2. Navigate to **Runtime** → **TwiML Bins**
3. Click **Create new TwiML Bin**
4. Name: `Vak Conversational AI`
5. Copy one of the configurations above
6. **Critical**: Ensure URL is `wss://vak.tutzi.ai/twilio`
7. Click **Create**

### 2. Configure Phone Number

1. Go to **Phone Numbers** → **Manage** → **Active numbers**
2. Click your Twilio phone number
3. Under **Voice & Fax**:
   - **A CALL COMES IN**: Select **TwiML Bin** → Choose `Vak Conversational AI`
4. Click **Save**

### 3. Test the Configuration

1. Call your Twilio phone number
2. You should hear the greeting
3. Stream connects immediately
4. Start speaking - AI should respond
5. Have a natural conversation

## Conversation Flow

### With Greeting (Recommended)

```
Caller calls → Twilio plays greeting → Stream starts → AI ready → Conversation begins
```

### Without Greeting (AI Provides Greeting)

```
Caller calls → Stream starts immediately → AI provides greeting → Conversation begins
```

## Best Practices for Conversational AI

1. **Use `track="both_tracks"`** - Enables full bidirectional audio
2. **Longer pause** - Use 600+ seconds for real conversations
3. **Natural greeting** - Let AI provide greeting or use friendly Twilio greeting
4. **Professional voice** - Use `voice="alice"` for natural sound
5. **Immediate stream** - Start stream before greeting for faster connection

## Troubleshooting

### AI Not Responding

- Check that stream URL is correct: `wss://vak.tutzi.ai/twilio`
- Verify SSL certificate is valid
- Check ECS logs for connection errors

### AI Not Listening

- Ensure `track="both_tracks"` is set
- Verify inbound audio is being received
- Check Deepgram session is active in logs

### Audio Quality Issues

- Ensure using `wss://` (secure WebSocket)
- Check ALB health checks passing
- Verify ECS task is running and healthy

## Example Use Cases

### Customer Service Bot

```xml
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" track="both_tracks" />
    </Start>
    <Say voice="alice" language="en-US">
        Thank you for calling. I'm your virtual assistant. How can I help you today?
    </Say>
    <Pause length="900" />
</Response>
```

### Personal Assistant

```xml
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" track="both_tracks" />
    </Start>
    <Say voice="alice" language="en-US">
        Hi there! I'm ready to help. What would you like to do?
    </Say>
    <Pause length="600" />
</Response>
```

### Information Hotline

```xml
<Response>
    <Start>
        <Stream url="wss://vak.tutzi.ai/twilio" track="both_tracks" />
    </Start>
    <Say voice="alice" language="en-US">
        Welcome to our information line. Ask me anything!
    </Say>
    <Pause length="1200" />
</Response>
```

## Current Implementation Status

✅ **Working Features:**
- Immediate session start on connection
- Bidirectional audio streaming
- Mulaw audio format (8kHz)
- Barge-in support (user can interrupt AI)
- Natural conversation flow

✅ **Optimized For:**
- Real-time conversations
- Low latency responses
- Natural speech patterns
- Extended conversations (10+ minutes)

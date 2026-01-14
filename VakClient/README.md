# Vak Client

React + Vite client application for the Vak Voice Assistant.

## Features

- WebSocket connection to VakDeepGram server
- Text message input and sending
- Real-time bidirectional audio streaming (PCM16, 48kHz)
- Real-time display of LLM streaming tokens
- PCM audio playback using Web Audio API (24kHz TTS output)
- Connection status indicator
- Live transcription display
- Message pair tracking (user input + AI response)

## Setup

1. Install dependencies:
```bash
npm install
```

2. Start development server:
```bash
npm run dev
```

3. Build for production:
```bash
npm run build
```

4. Preview production build:
```bash
npm run preview
```

## Usage

### Local Development

1. Start the VakDeepGram server on `localhost:8080`
2. The client defaults to `ws://localhost:8080/ws` for local development
3. Click "Connect" to establish WebSocket connection
4. **Text Mode**: Type a message and click "Send" or press Enter
5. **Voice Mode**: Click "🎙️ Start Conversation" to start recording, then click "⏹️ End Conversation" when done

### Production/AWS

1. Set `VITE_WS_URL` environment variable or update the WebSocket URL in the connection field
2. Enter the WebSocket URL (from CDK stack output) in the connection field
3. Click "Connect" to establish WebSocket connection
4. Use text or voice modes as described above

### Environment Variables

Create a `.env` file (see `.env.example`):
- `VITE_WS_URL`: WebSocket URL (default: `ws://localhost:8080/ws`)

## WebSocket URL Format

The WebSocket URL should be in the format:
```
wss://{api-id}.execute-api.{region}.amazonaws.com/prod
```

Get this from the CDK stack output `WebSocketUrl`.

## Message Protocol

### Client → Server

**Text Message:**
```json
{
  "action": "message",
  "text": "Hello, how are you?"
}
```

**Audio:**
Binary PCM16 audio chunks (48kHz) sent directly via WebSocket.

### Server → Client

**LLM Token:**
```json
{
  "t": "llm-token",
  "token": "Hello"
}
```

**TTS Audio:**
```json
{
  "t": "tts",
  "audio": "base64-encoded-pcm16-data",
  "messageId": "msg_123",
  "connectionId": "ws-abc123"
}
```

**Transcript:**
```json
{
  "t": "transcript",
  "text": "Hello world",
  "messageId": "msg_123",
  "role": "user"
}
```

**Partial Transcript:**
```json
{
  "t": "partial-transcript",
  "text": "Hello",
  "messageId": "msg_123"
}
```

**Message ID:**
```json
{
  "t": "message-id",
  "messageId": "msg_123",
  "connectionId": "ws-abc123"
}
```

**Deepgram Ready:**
```json
{
  "t": "deepgram-ready",
  "connectionId": "ws-abc123"
}
```

**Ready to Listen:**
```json
{
  "t": "ready-to-listen",
  "messageId": "msg_123"
}
```

**Error:**
```json
{
  "t": "error",
  "message": "Error description"
}
```

## Audio Format

- **Input**: PCM16, 48kHz, mono
- **Output**: PCM16, 24kHz, mono (from Deepgram Voice Agents)

## Browser Requirements

- Modern browser with WebSocket support
- Web Audio API support (Chrome, Firefox, Edge, Safari)
- Microphone permissions
- ScriptProcessorNode support (for PCM16 audio capture)

## Development

The app runs on `http://localhost:5173` by default (Vite default port). Hot module replacement is enabled for fast development.

## Backend Compatibility

This client is designed to work with **VakDeepGram** server, which uses Deepgram Voice Agents for:
- Speech-to-text (STT)
- Large language model (LLM) processing
- Text-to-speech (TTS)

The server accepts 48kHz input and returns 24kHz TTS audio.

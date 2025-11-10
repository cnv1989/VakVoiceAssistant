# Vak Client

React + Vite client application for the Vak Voice Assistant.

## Features

- WebSocket connection to API Gateway
- Text message input and sending
- MediaRecorder for Ogg Opus audio streaming
- Real-time display of LLM streaming tokens
- PCM audio playback using Web Audio API (16kHz)
- Connection status indicator

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

1. Start the VakServer on `localhost:8080`
2. The client defaults to `ws://localhost:8080/ws` for local development
3. Click "Connect" to establish WebSocket connection
4. **Text Mode**: Type a message and click "Send" or press Enter
5. **Voice Mode**: Click "🎙️ Start Opus" to start recording, then click "Stop" when done

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
Binary Ogg Opus chunks sent directly via WebSocket

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
  "audio": "base64-encoded-pcm-data"
}
```

**Transcript:**
```json
{
  "t": "transcript",
  "text": "Hello world"
}
```

**Error:**
```json
{
  "t": "error",
  "message": "Error description"
}
```

## Browser Requirements

- Modern browser with WebSocket support
- MediaRecorder API support (Chrome, Firefox, Edge)
- Web Audio API support
- Microphone permissions

## Development

The app runs on `http://localhost:3000` by default. Hot module replacement is enabled for fast development.

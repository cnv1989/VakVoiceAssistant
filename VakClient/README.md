# VakClient

React + Vite web client for the Vak voice assistant — a voice page and a
text chat page, both talking to the same VakDeepGram backend.

Prefer the guided setup? Run `./vak init` and `./vak dev` from the repo
root instead of the steps below — see [../docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md).

## Features

- WebSocket connection to VakDeepGram, with real-time bidirectional PCM16
  audio streaming (48kHz capture, 24kHz TTS playback)
- Live transcript display and barge-in (interrupting the agent mid-reply)
- A collapsible "Advanced settings" panel for the WebSocket URL, test
  business/customer numbers, and voice selection
- A separate text chat page hitting the same backend's REST `/chat` endpoint

## Setup

```bash
npm install
cp .env.example .env   # then edit VITE_WS_URL / VITE_BUSINESS_NAME as needed
npm run dev
```

The dev server runs on [http://localhost:5173](http://localhost:5173) by
default (Vite's standard port).

```bash
npm run build      # production build to dist/
npm run preview    # preview the production build locally
```

## Environment variables

See `.env.example`. Full reference: [../docs/CONFIGURATION.md](../docs/CONFIGURATION.md#vakclient-vakclientenv).

| Variable | Default | Description |
|---|---|---|
| `VITE_WS_URL` | `ws://localhost:8080/ws` | Backend WebSocket URL for the voice page |
| `VITE_CHAT_API_URL` | — | Backend URL for the chat page's "Deployed" option |
| `VITE_BUSINESS_NAME` | `Vak Assistant` | Shown in the header and chat page |

For a deployed backend, use the `WebSocketUrl` output from `cdk deploy`
(see [../VakInfra/README.md](../VakInfra/README.md)) — no API Gateway
involved, VakDeepGram serves `/ws` directly behind an ALB.

## WebSocket protocol

### Client → Server

```json
{ "action": "start-recording" }
{ "action": "stop-recording" }
```
Plus binary PCM16 audio frames (48kHz, mono) sent directly over the socket
while recording.

### Server → Client

| `type` | Payload | Meaning |
|---|---|---|
| `welcome` | `message` | Sent on connect |
| `message-id` | `messageId` | New conversational turn started |
| `partial-transcript` | `text`, `messageId` | Live STT (not yet final) |
| `transcript` | `text`, `messageId` | Final STT for this turn |
| `llm-token` | `token`, `messageId` | Streaming LLM output |
| `tts` | `audio` (base64 PCM16), `messageId` | TTS audio chunk, 24kHz |
| `ready-to-listen` | `messageId` | Agent finished responding |
| `user-started-speaking` | — | Triggers client-side barge-in (stops playback) |
| `agent-started-speaking` | — | Agent has started producing audio |
| `error` | `message` | Something went wrong |

Each conversational turn gets a server-generated `messageId`; the client
pairs the user's transcript with the agent's reply using it.

## Browser requirements

- WebSocket and Web Audio API support (Chrome, Firefox, Edge, Safari)
- Microphone permission for the voice page
- Note: microphone access requires `https://` or `http://localhost` — it
  won't work over plain HTTP on a non-localhost origin

## Backend compatibility

Built against **VakDeepGram**, which uses the Deepgram Voice Agent API for
STT, LLM bridging, and TTS. The server accepts 48kHz PCM16 input and
returns 24kHz PCM16 TTS audio.

# Quick Start Guide - VakClient

## Local Development

1. **Install dependencies:**
```bash
npm install
```

2. **Start development server:**
```bash
npm run dev
```

3. **Open browser:**
   - The app will open at `http://localhost:3001`
   - WebSocket URL defaults to `ws://localhost:8080/ws`
   - Make sure VakDeepGram is running on port 8080

4. **Connect and test:**
   - Click "Connect" button
   - Type a message and click "Send" to test text mode
   - Click "🎙️ Start Opus" to test voice mode

## Environment Variables

Create a `.env` file in the VakClient directory:

```env
VITE_WS_URL=ws://localhost:8080/ws
```

For production/AWS deployment:
```env
VITE_WS_URL=wss://your-api-id.execute-api.us-west-2.amazonaws.com/prod
```

## Building for Production

```bash
npm run build
```

The built files will be in the `dist` directory.

## Preview Production Build

```bash
npm run preview
```

This serves the production build locally for testing.

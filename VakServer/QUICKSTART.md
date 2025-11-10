# Quick Start Guide - Local Testing

This guide will help you run VakServer and VakClient locally for testing.

## Prerequisites

1. **Node.js 20+** installed
2. **AWS Credentials** configured (for Bedrock, Transcribe, Polly, DynamoDB, S3)
   - Run `aws configure` or set environment variables:
     - `AWS_ACCESS_KEY_ID`
     - `AWS_SECRET_ACCESS_KEY`
     - `AWS_REGION` (default: us-west-2)

## Step 1: Start VakServer

1. Navigate to VakServer directory:
```bash
cd VakServer
```

2. Install dependencies:
```bash
npm install
```

3. Copy environment file:
```bash
cp .env.example .env
```

4. Edit `.env` if needed (defaults should work for local testing)

5. Start the server:
```bash
npm run dev
```

The server will start on `http://localhost:8080` and WebSocket server on `ws://localhost:8080/ws`

## Step 2: Start VakClient

1. Open a new terminal and navigate to VakClient directory:
```bash
cd VakClient
```

2. Install dependencies:
```bash
npm install
```

3. (Optional) Create `.env` file if you want to customize WebSocket URL:
```bash
cp .env.example .env
```

4. Start the development server:
```bash
npm run dev
```

The client will open at `http://localhost:3000` (or the port shown in terminal)

## Step 3: Test the Application

1. In the browser, the WebSocket URL should already be set to `ws://localhost:8080/ws`
2. Click **"Connect"** button
3. You should see "Status: Connected"
4. **Test Text Mode:**
   - Type a message in the input box
   - Click "Send" or press Enter
   - You should see streaming LLM tokens appear
   - Audio playback should start automatically
5. **Test Voice Mode:**
   - Click "🎙️ Start Opus" button
   - Grant microphone permissions if prompted
   - Speak into your microphone
   - Click "Stop" when done
   - You should see transcript and then LLM response with audio

## Troubleshooting

### Server won't start
- Check if port 8080 is already in use
- Verify AWS credentials are configured
- Check server logs for errors

### WebSocket connection fails
- Ensure server is running on port 8080
- Check browser console for errors
- Verify WebSocket URL is `ws://localhost:8080/ws`

### No audio playback
- Check browser console for errors
- Ensure microphone permissions are granted
- Verify AWS Polly service is accessible

### AWS Service Errors
- Verify your AWS credentials have permissions for:
  - Bedrock (InvokeModel)
  - Transcribe (StartStreamTranscription)
  - Polly (SynthesizeSpeech)
  - DynamoDB (PutItem, DeleteItem)
  - S3 (optional for local testing)

## Next Steps

Once local testing works, you can:
1. Deploy the infrastructure using CDK (see VakInfra/README.md)
2. Build and push Docker image to ECR
3. Update client to use AWS WebSocket endpoint

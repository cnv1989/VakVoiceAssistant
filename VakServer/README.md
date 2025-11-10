# Vak Server

Fastify server for handling WebSocket connections and processing voice/text interactions with AWS services.

## Features

- Health check endpoint (`/health`)
- WebSocket route handlers (`/connect`, `/disconnect`, `/default`)
- Amazon Transcribe Streaming for audio-to-text (Ogg Opus)
- Amazon Bedrock for LLM responses (streaming)
- Amazon Polly for text-to-speech (PCM16, 16kHz)
- DynamoDB session management
- API Gateway Management API for WebSocket communication

## Environment Variables

- `LOCAL_MODE`: Set to `'true'` to enable local WebSocket server (default: enabled if `WS_API_ENDPOINT` is not set)
- `REGION`: AWS region (default: us-west-2)
- `WS_API_ENDPOINT`: API Gateway WebSocket endpoint URL (format: `https://{api-id}.execute-api.{region}.amazonaws.com/prod`)
  - Leave empty for local development mode
  - Required for AWS deployment
- `MODEL_ID`: Bedrock model ID (default: anthropic.claude-3-haiku-20240307-v1:0)
- `POLLY_VOICE`: Polly voice ID (default: Ruth - generative voice)
- `POLLY_ENGINE`: Polly engine type - 'standard', 'neural', or 'generative' (default: generative)
- `BUCKET`: S3 bucket name for artifacts (optional for local testing)
- `DDB_TABLE`: DynamoDB table name for sessions (optional for local testing)
- `PORT`: Server port (default: 8080)
- `HOST`: Server host (default: 0.0.0.0)

**Note**: The `WS_API_ENDPOINT` should be the HTTP(S) endpoint, not the WebSocket URL. It's used by the ApiGatewayManagementApi client to send messages back to connected clients.

## Local Development

For local testing, the server automatically enables WebSocket support when `WS_API_ENDPOINT` is not set:

1. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

2. Start the server:
```bash
npm run dev
```

3. The WebSocket server will be available at `ws://localhost:8080/ws`

4. Configure the client to connect to `ws://localhost:8080/ws` (this is the default)

## Development

1. Install dependencies:
```bash
npm install
```

2. Build TypeScript:
```bash
npm run build
```

3. Run server:
```bash
npm start
```

4. Development mode with hot reload:
```bash
npm run dev
```

## Docker Build & ECR Deployment

### Automated Deployment

The easiest way to deploy to ECR is using the provided deployment script:

```bash
npm run deploy:ecr
```

Or run the script directly:

```bash
./deploy-to-ecr.sh
```

The script will:
1. Get your AWS account ID
2. Authenticate Docker to ECR
3. Create the ECR repository if it doesn't exist
4. Build the Docker image
5. Tag and push the image to ECR

You can customize the deployment by setting environment variables:
- `AWS_REGION`: AWS region (default: us-west-2)
- `IMAGE_TAG`: Docker image tag (default: latest)

Example:
```bash
AWS_REGION=us-east-1 IMAGE_TAG=v1.0.0 npm run deploy:ecr
```

### Manual Deployment

If you prefer to deploy manually:

1. Build image:
```bash
docker build -t vak-server .
```

2. Get ECR repository URI (from CDK outputs or construct it):
```bash
# Get account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/vak-server"
```

3. Authenticate Docker to ECR:
```bash
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin $ECR_REPO_URI
```

4. Tag and push:
```bash
docker tag vak-server:latest $ECR_REPO_URI:latest
docker push $ECR_REPO_URI:latest
```

## Routes

### GET /health
Health check endpoint. Returns `{ status: 'ok', timestamp: '...' }`.

### POST /connect
Handles WebSocket connection. Stores session in DynamoDB with TTL.

### POST /disconnect
Handles WebSocket disconnection. Removes session from DynamoDB.

### POST /default
Handles WebSocket messages:
- **JSON payload**: `{ action: 'message', text: '...' }` - Processes text through Bedrock and Polly
- **Binary payload**: Ogg Opus audio - Processes through Transcribe, then Bedrock and Polly

## Message Format

### Client → Server
- Text: `{ action: 'message', text: 'Hello' }`
- Audio: Binary Ogg Opus chunks

### Server → Client
- LLM tokens: `{ t: 'llm-token', token: '...' }`
- TTS audio: `{ t: 'tts', audio: 'base64-encoded-pcm' }`
- Transcript: `{ t: 'transcript', text: '...' }`
- Error: `{ t: 'error', message: '...' }`

# Vak - Voice Assistant Kit

A complete voice AI platform for deploying intelligent voice agents that integrate with business platforms.

## Overview

Vak enables businesses to deploy AI-powered voice assistants that can handle customer calls, book appointments, answer questions, and perform business operations through natural conversation.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  VakClient  │────▶│ VakDeepGram │────▶│   Deepgram  │────▶│   Square/   │
│  (React)    │ WS  │  (FastAPI)  │ WS  │  Voice API  │     │   Setmore   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  VakInfra   │
                    │  (AWS CDK)  │
                    └─────────────┘
```

## Components

| Component | Description | Tech Stack |
|-----------|-------------|------------|
| [VakClient](./VakClient/) | Web-based voice interface | React, Vite, TypeScript |
| [VakDeepGram](./VakDeepGram/) | Voice agent server | FastAPI, Python, Strands |
| [VakInfra](./VakInfra/) | AWS infrastructure | CDK, TypeScript |

## Features

- **Real-time Voice** - Bidirectional audio streaming via WebSocket
- **AI Agent** - Strands Agent framework with AWS Bedrock (Claude)
- **Voice Processing** - Deepgram for STT, ElevenLabs/Deepgram for TTS
- **Business Integration** - Square and Setmore appointment booking
- **Phone Support** - Twilio media stream integration
- **Scalable Infrastructure** - ECS Fargate, ALB, DynamoDB

## Quick Start

### Prerequisites

- Node.js 20+
- Python 3.8+
- Docker
- AWS CLI configured
- AWS CDK CLI (`npm install -g aws-cdk`)

### Local Development

**1. Start the backend:**
```bash
cd VakDeepGram
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Deepgram API key

# Run server
./docker-run.sh
# Or: uvicorn vakdeepgram.api.main:app --port 8080
```

**2. Start the frontend:**
```bash
cd VakClient
npm install
npm run dev
```

**3. Open browser:**
Navigate to [http://localhost:5173](http://localhost:5173)

### AWS Deployment

```bash
# Deploy infrastructure
cd VakInfra
npm install
cdk deploy VakNetworkStack

# Build and push Docker image
cd ../VakDeepGram
./deploy-to-ecr.sh

# Deploy application
cd ../VakInfra
cdk deploy VakAppStack
```

## Project Structure

```
vak/
├── VakClient/              # React frontend
│   ├── src/
│   │   ├── App.tsx         # Main voice app
│   │   └── ws-signer.ts    # AWS SigV4 signing
│   └── package.json
│
├── VakDeepGram/            # Python backend
│   ├── src/vakdeepgram/
│   │   ├── main.py         # FastAPI server
│   │   ├── config.py       # Configuration
│   │   ├── deepgram_handler.py
│   │   ├── business_logic.py
│   │   └── providers/      # Square/Setmore adapters
│   ├── requirements.txt
│   └── Dockerfile
│
├── VakInfra/               # AWS CDK
│   ├── lib/
│   │   ├── vak-network-stack.ts
│   │   ├── vak-app-stack.ts
│   │   └── vak-monitoring-stack.ts
│   └── package.json
│
├── docs/                   # Documentation
│   ├── DESIGN.md
│   └── ARCHITECTURE.md
│
└── .github/workflows/      # CI/CD
```

## Documentation

- [Design Document](./docs/DESIGN.md) - System architecture and design decisions
- [Architecture Guide](./docs/ARCHITECTURE.md) - Technical implementation details
- [VakDeepGram README](./VakDeepGram/README.md) - Backend setup and API reference
- [VakInfra README](./VakInfra/README.md) - Infrastructure deployment guide

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPGRAM_API_KEY` | Deepgram API key | Yes |
| `DEEPGRAM_PROJECT_ID` | Deepgram project ID | Yes |
| `DEEPGRAM_SPEAKING_PROVIDER` | TTS provider (eleven_labs/deepgram) | No |
| `DEEPGRAM_SPEAKING_VOICE_ID` | ElevenLabs voice ID | No |
| `AWS_REGION` | AWS region | Yes |
| `DDB_TABLE` | DynamoDB table name | Yes |

See [VakDeepGram README](./VakDeepGram/README.md) for complete configuration reference.

## API Reference

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `/ws` | Web client connection |
| `/twilio` | Twilio media stream |

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service info |
| `/health` | GET | Health check |
| `/chat` | POST | REST chat interface |

## Agent Tools

The voice agent can perform these actions:

| Tool | Description |
|------|-------------|
| `get_appointments` | List scheduled appointments |
| `check_availability` | Find open time slots |
| `book_appointment` | Create new booking |
| `get_customers` | List customer records |
| `get_staff` | List staff members |
| `get_services` | List available services |
| `get_business_hours` | Get operating hours |

## CI/CD

GitHub Actions workflows deploy on push to `main`:

- **VakDeepGram**: Build Docker image → Push to ECR → Update ECS
- **VakInfra**: CDK diff → CDK deploy

## Related Projects

- [Integrin Dashboard](../integrin/) - Business management dashboard

## License

ISC

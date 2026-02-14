# Vak - Voice Assistant Kit

A monorepo containing the complete Vak voice assistant application with client, Deepgram server, and infrastructure components.

## Repository Structure

```
vak/
├── VakClient/      # React/TypeScript frontend client
├── VakDeepGram/    # Python/FastAPI WebSocket server (Deepgram Voice Agent)
├── VakInfra/       # AWS CDK infrastructure as code
└── Twilio/         # Twilio integration helpers and test clients
```

## Components

### VakClient
React-based web client for the voice assistant. Built with Vite, TypeScript, and WebSocket for real-time communication.

**Key Features:**
- WebSocket connection to API Gateway
- Real-time audio streaming
- Text and voice input
- LLM response display
- Text-to-speech audio playback

**Quick Start:**
```bash
cd VakClient
npm install
npm run dev
```

### VakDeepGram
FastAPI-based WebSocket server handling real-time audio via Deepgram Voice Agents.

**Key Features:**
- WebSocket audio streaming (`/ws`)
- Deepgram Voice Agent integration
- Twilio media stream support (`/twilio`)

**Quick Start:**
```bash
cd VakDeepGram
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### VakInfra
AWS CDK infrastructure definitions for deploying the complete Vak application to AWS.

**Architecture:**
- **VakNetworkStack**: VPC, subnets, ECR repository
- **VakAppStack**: ECS Fargate, ALB, DynamoDB, S3

**Key Resources:**
- VPC with public/private subnets
- ECS Fargate cluster and service
- API Gateway WebSocket API
- Network Load Balancer
- DynamoDB for sessions
- S3 for artifacts
- ECR for container images

**Quick Start:**
```bash
cd VakInfra
npm install

# Deploy network stack
cdk deploy VakNetworkStack

# Build and push Docker image
cd ../VakDeepGram
./deploy-to-ecr.sh

# Deploy application stack
cd ../VakInfra
cdk deploy VakAppStack
```

## Prerequisites

- Node.js 20+
- Docker
- AWS CLI configured
- AWS CDK CLI (`npm install -g aws-cdk`)
- GitHub account (for repository)

## Development

Each component can be developed independently:

1. **Client Development**: Run `VakClient` locally with `npm run dev`
2. **Server Development**: Run `VakDeepGram` locally with `python main.py`
3. **Infrastructure**: Deploy stacks using CDK commands

## Deployment

See individual component READMEs for detailed deployment instructions:
- [VakClient README](./VakClient/README.md)
- [VakDeepGram README](./VakDeepGram/README.md)
- [VakInfra README](./VakInfra/README.md)

## License

ISC

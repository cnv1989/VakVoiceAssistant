# Vak - Voice Assistant Kit

A monorepo containing the complete Vak voice assistant application with client, server, and infrastructure components.

## Repository Structure

```
vak/
├── VakClient/      # React/TypeScript frontend client
├── VakServer/      # Node.js/TypeScript backend server
└── VakInfra/       # AWS CDK infrastructure as code
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

### VakServer
Fastify-based backend server handling WebSocket connections, AWS service integrations, and business logic.

**Key Features:**
- WebSocket connection handling
- AWS Bedrock integration for LLM
- AWS Transcribe for speech-to-text
- AWS Polly for text-to-speech
- DynamoDB session management
- S3 artifact storage

**Quick Start:**
```bash
cd VakServer
npm install
npm run dev
```

### VakInfra
AWS CDK infrastructure definitions for deploying the complete Vak application to AWS.

**Architecture:**
- **VakNetworkStack**: VPC, subnets, ECR repository
- **VakAppStack**: ECS Fargate, API Gateway, DynamoDB, S3, NLB

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
cd ../VakServer
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
2. **Server Development**: Run `VakServer` locally with `npm run dev`
3. **Infrastructure**: Deploy stacks using CDK commands

## Deployment

See individual component READMEs for detailed deployment instructions:
- [VakClient README](./VakClient/README.md)
- [VakServer README](./VakServer/README.md)
- [VakInfra README](./VakInfra/README.md)

## License

ISC

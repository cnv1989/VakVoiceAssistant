# Vak Infrastructure

CDK v2 infrastructure for the Vak Voice Assistant stack.

## Prerequisites

- Node.js 20+
- AWS CLI configured
- AWS CDK CLI installed: `npm install -g aws-cdk`

## Setup

1. Install dependencies:
```bash
npm install
```

2. Bootstrap CDK (if not already done):
```bash
cdk bootstrap aws://ACCOUNT-ID/us-west-2
```

3. Build the TypeScript code:
```bash
npm run build
```

4. Synthesize CloudFormation template:
```bash
npm run synth
```

5. Deploy the stack:
```bash
npm run deploy
```

## Stack Components

- **VPC**: 2 Availability Zones with public and private subnets
- **ECS Fargate**: Node 20 Fastify service on port 8080
- **Network Load Balancer**: Public-facing NLB with health checks on `/health`
- **API Gateway WebSocket**: WebSocket API with VPC Link integration
- **DynamoDB**: Sessions table with TTL
- **S3**: Artifacts bucket for transcripts and audio
- **ECR**: Repository for VakServer Docker image
- **IAM**: Roles with permissions for Bedrock, Transcribe, Polly, S3, DynamoDB

## Outputs

After deployment, the stack outputs:
- `WebSocketUrl`: WebSocket API endpoint URL
- `EcrRepoUri`: ECR repository URI for pushing Docker images
- `NlbDns`: Network Load Balancer DNS name

## Environment Variables

The ECS task receives these environment variables:
- `REGION`: AWS region (us-west-2)
- `BUCKET`: S3 artifacts bucket name
- `DDB_TABLE`: DynamoDB sessions table name
- `MODEL_ID`: Bedrock model ID (default: anthropic.claude-3-haiku-20240307-v1:0)
- `POLLY_VOICE`: Polly voice ID (default: Joanna)

Note: `WS_API_ENDPOINT` must be set manually after deployment. It follows the pattern:
`https://{api-id}.execute-api.{region}.amazonaws.com/prod`

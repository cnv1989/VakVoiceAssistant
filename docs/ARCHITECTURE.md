# Vak Architecture Guide

## Repository Structure

```
vak/
├── VakClient/              # React frontend
├── VakDeepGram/            # Python backend
├── VakInfra/               # AWS CDK infrastructure
├── Twilio/                 # Twilio integration helpers
├── docs/                   # Documentation
└── .github/workflows/      # CI/CD pipelines
```

## Technology Stack

### VakClient

| Component | Technology | Version |
|-----------|------------|---------|
| Framework | React | 18.2.0 |
| Build Tool | Vite | 5.0.0 |
| Language | TypeScript | 5.0.0 |
| Styling | CSS Modules | - |
| WebSocket | Native WS | - |
| Audio | Web Audio API | - |

### VakDeepGram

| Component | Technology | Version |
|-----------|------------|---------|
| Framework | FastAPI | 0.128.0 |
| Language | Python | 3.8+ |
| Runtime | uvicorn | 0.40.0 |
| Agent Framework | Strands Agents | 1.23.0 |
| Voice API | Deepgram SDK | 5.3.1 |
| TTS | ElevenLabs | - |
| LLM | AWS Bedrock (Claude) | - |
| Database | DynamoDB | - |

### VakInfra

| Component | Technology | Version |
|-----------|------------|---------|
| IaC | AWS CDK | v2 |
| Language | TypeScript | - |
| Cloud | AWS | - |

## VakClient Architecture

### Component Structure

```
VakClient/
├── src/
│   ├── main.tsx           # Entry point
│   ├── App.tsx            # Main voice application (7KB)
│   ├── ChatPage.tsx       # REST chat interface
│   ├── Layout.tsx         # Layout wrapper
│   ├── ws-signer.ts       # AWS SigV4 WebSocket signing
│   └── assets/            # Static assets
├── public/
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

### Audio Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                      Browser Audio Pipeline                      │
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐   │
│  │ getUserMedia│────▶│ MediaStream │────▶│ MediaRecorder   │   │
│  │             │     │             │     │ (PCM16 @ 48kHz) │   │
│  └─────────────┘     └─────────────┘     └─────────────────┘   │
│                                                  │               │
│                                                  ▼               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    WebSocket                             │   │
│  │         ws://localhost:8080/ws or wss://alb/ws          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                  Audio Playback                          │   │
│  │  ┌─────────────┐     ┌─────────────┐     ┌───────────┐ │   │
│  │  │ Base64      │────▶│ AudioBuffer │────▶│ AudioCtx  │ │   │
│  │  │ Decode      │     │ Queue       │     │ Play      │ │   │
│  │  └─────────────┘     └─────────────┘     └───────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### State Management

```typescript
// App.tsx state structure
interface AppState {
  // Connection
  isConnected: boolean;
  connectionStatus: 'disconnected' | 'connecting' | 'connected' | 'error';

  // Recording
  isRecording: boolean;
  micPermission: 'unknown' | 'granted' | 'denied';

  // Messages
  messages: Message[];
  currentTranscript: string;

  // Audio
  audioQueue: AudioBuffer[];
  isPlaying: boolean;
}

interface Message {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  timestamp: Date;
  status: 'pending' | 'complete';
}
```

### WebSocket Protocol

```typescript
// Client → Server
interface ClientMessage {
  action: 'start-deepgram' | 'stop-deepgram';
}
// Or binary PCM16 audio data

// Server → Client
interface ServerMessage {
  type:
    | 'deepgram-ready'
    | 'settings-applied'
    | 'welcome'
    | 'transcript'
    | 'llm-token'
    | 'llm-response'
    | 'tts'
    | 'ready-to-listen'
    | 'deepgram-disconnected'
    | 'error';
  connectionId: string;
  data?: any;
}
```

## VakDeepGram Architecture

### Module Structure

```
VakDeepGram/
├── src/vakdeepgram/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app (72KB)
│   ├── config.py                  # Settings (20KB)
│   ├── deepgram_handler.py        # Voice Agent handler (37KB)
│   ├── business_logic.py          # Business operations (77KB)
│   ├── agent_functions.py         # AI agent tools (31KB)
│   ├── connection_store.py        # Session management (56KB)
│   ├── store_tools.py             # Tool definitions (12KB)
│   │
│   ├── api/                       # REST & WebSocket endpoints
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── websocket.py
│   │
│   ├── core/                      # Core utilities
│   │   ├── __init__.py
│   │   ├── exceptions.py
│   │   └── dependencies.py
│   │
│   ├── domain/                    # Domain models
│   │   ├── __init__.py
│   │   ├── appointment.py
│   │   ├── customer.py
│   │   └── service.py
│   │
│   ├── providers/                 # Business platform adapters
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── square/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   └── helpers.py
│   │   ├── setmore/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   └── helpers.py
│   │   └── common/
│   │       └── transformers.py
│   │
│   ├── repositories/              # Data access layer
│   │   ├── __init__.py
│   │   ├── session_repository.py
│   │   └── connection_context_repository.py
│   │
│   ├── services/                  # Business services
│   │   ├── __init__.py
│   │   ├── auth_context_service.py
│   │   └── business_context_service.py
│   │
│   ├── security/                  # Auth & validation
│   │   ├── __init__.py
│   │   └── oauth.py
│   │
│   └── utils/                     # Utilities
│       ├── __init__.py
│       ├── logging.py
│       ├── metrics.py
│       └── case.py
│
├── tests/                         # Test suite
│   ├── conftest.py
│   ├── test_main.py
│   └── test_providers/
│
├── scripts/                       # Deployment scripts
│   └── deploy-to-ecr.sh
│
├── requirements.txt               # Dependencies
├── Dockerfile                     # Container definition
├── docker-run.sh                  # Docker wrapper
└── main.py                        # Entry point
```

### Request Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Middleware Stack                      │    │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────────┐  │    │
│  │  │  CORS   │─▶│ Logging │─▶│  Auth   │─▶│ Rate Limit│  │    │
│  │  └─────────┘  └─────────┘  └─────────┘  └───────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                     Route Handlers                       │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │    │
│  │  │  /ws        │  │  /twilio    │  │  /chat          │ │    │
│  │  │  WebSocket  │  │  WebSocket  │  │  REST           │ │    │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘ │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  Deepgram Handler                        │    │
│  │  ┌───────────────────────────────────────────────────┐  │    │
│  │  │              WebSocket Connection                  │  │    │
│  │  │  wss://agent.deepgram.com/v1/agent/converse       │  │    │
│  │  └───────────────────────────────────────────────────┘  │    │
│  │                          │                               │    │
│  │  ┌───────────────────────┼───────────────────────────┐  │    │
│  │  │                       │                            │  │    │
│  │  ▼                       ▼                            ▼  │    │
│  │  ┌─────────┐      ┌─────────────┐      ┌───────────┐   │    │
│  │  │  STT    │─────▶│    LLM      │─────▶│    TTS    │   │    │
│  │  │ Events  │      │  + Tools    │      │  Audio    │   │    │
│  │  └─────────┘      └─────────────┘      └───────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Agent Configuration

```python
# config.py
class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "debug"

    # Deepgram
    deepgram_api_key: str
    deepgram_project_id: str
    deepgram_agent_id: Optional[str] = None

    # Agent configuration
    deepgram_agent_language: str = "en"
    deepgram_listening_model: str = "flux-general-en"
    deepgram_listening_version: str = "v2"
    deepgram_thinking_provider: str = "google"
    deepgram_thinking_model: str = "gemini-2.5-flash"
    deepgram_speaking_provider: str = "eleven_labs"
    deepgram_speaking_model_id: str = "eleven_multilingual_v2"
    deepgram_speaking_voice_id: str = "cgSgspJ2msm6clMCkdW9"

    # Audio
    deepgram_input_sample_rate: int = 48000
    deepgram_output_sample_rate: int = 24000

    # AWS
    aws_region: str = "us-west-2"
    dynamodb_table: str = "vak-sessions"
    s3_bucket: str = "vak-artifacts"

    # Rate limiting
    rate_limit_connections: int = 10
    rate_limit_messages: int = 100
    rate_limit_window: int = 60
```

### Tool Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Tool Execution Pipeline                       │
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐   │
│  │  LLM        │────▶│   Tool      │────▶│  Tool           │   │
│  │  Decision   │     │   Router    │     │  Executor       │   │
│  └─────────────┘     └─────────────┘     └─────────────────┘   │
│                                                  │               │
│                          ┌───────────────────────┴───────────┐   │
│                          │                                   │   │
│                          ▼                                   ▼   │
│                   ┌─────────────┐                    ┌───────────┐
│                   │   Square    │                    │  Setmore  │
│                   │   Provider  │                    │  Provider │
│                   └─────────────┘                    └───────────┘
│                          │                                   │   │
│                          └───────────────────┬───────────────┘   │
│                                              │                   │
│                                              ▼                   │
│                                       ┌─────────────┐            │
│                                       │  Response   │            │
│                                       │  Transform  │            │
│                                       └─────────────┘            │
│                                              │                   │
│                                              ▼                   │
│                                       ┌─────────────┐            │
│                                       │  LLM        │            │
│                                       │  Synthesis  │            │
│                                       └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

## VakInfra Architecture

### Stack Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                        VakInfra CDK App                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   VakNetworkStack                        │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │    │
│  │  │     VPC     │  │   Subnets   │  │      ECR        │ │    │
│  │  │   2 AZs     │  │  Pub/Priv   │  │   Repository    │ │    │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘ │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    VakAppStack                           │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │                 Compute                          │    │    │
│  │  │  ┌───────────┐  ┌───────────┐  ┌─────────────┐ │    │    │
│  │  │  │   ECS     │  │  Fargate  │  │    ALB      │ │    │    │
│  │  │  │  Cluster  │  │  Service  │  │             │ │    │    │
│  │  │  └───────────┘  └───────────┘  └─────────────┘ │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │                 Security                         │    │    │
│  │  │  ┌───────────┐  ┌───────────┐  ┌─────────────┐ │    │    │
│  │  │  │    WAF    │  │  Cognito  │  │    IAM      │ │    │    │
│  │  │  │  WebACL   │  │ UserPool  │  │   Roles     │ │    │    │
│  │  │  └───────────┘  └───────────┘  └─────────────┘ │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │                 Storage                          │    │    │
│  │  │  ┌───────────┐  ┌───────────┐  ┌─────────────┐ │    │    │
│  │  │  │ DynamoDB  │  │    S3     │  │ CloudWatch  │ │    │    │
│  │  │  │ Sessions  │  │ Artifacts │  │    Logs     │ │    │    │
│  │  │  └───────────┘  └───────────┘  └─────────────┘ │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  VakMonitoringStack                      │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │    │
│  │  │ Dashboards  │  │   Alarms    │  │    Metrics      │ │    │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘ │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Resource Configuration

```typescript
// ECS Task Definition
const taskDefinition = new ecs.FargateTaskDefinition(this, 'TaskDef', {
  memoryLimitMiB: 2048,
  cpu: 1024,
  runtimePlatform: {
    cpuArchitecture: ecs.CpuArchitecture.X86_64,
    operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
  },
});

// Container Definition
taskDefinition.addContainer('VakDeepGram', {
  image: ecs.ContainerImage.fromEcrRepository(ecrRepo, 'latest'),
  portMappings: [{ containerPort: 8080 }],
  environment: {
    REGION: 'us-west-2',
    DDB_TABLE: dynamoTable.tableName,
    BUCKET: s3Bucket.bucketName,
  },
  secrets: {
    DEEPGRAM_API_KEY: ecs.Secret.fromSecretsManager(deepgramSecret),
  },
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'vak',
    logGroup: logGroup,
  }),
});

// ALB Configuration
const alb = new elbv2.ApplicationLoadBalancer(this, 'ALB', {
  vpc,
  internetFacing: true,
});

// HTTPS Listener (if certificate provided)
if (certificateArn) {
  alb.addListener('HTTPS', {
    port: 443,
    certificates: [
      elbv2.ListenerCertificate.fromArn(certificateArn),
    ],
    defaultAction: elbv2.ListenerAction.forward([targetGroup]),
  });
}
```

## Deployment Pipeline

### CI/CD Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    GitHub Actions Pipeline                       │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   Trigger: Push to main                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              │               │               │                  │
│              ▼               ▼               ▼                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │  VakClient    │  │  VakDeepGram  │  │   VakInfra    │       │
│  │  Build & Test │  │  Build & Push │  │  CDK Deploy   │       │
│  └───────────────┘  └───────────────┘  └───────────────┘       │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │  S3 + CDN     │  │     ECR       │  │ CloudFormation│       │
│  │  Deploy       │  │    Push       │  │   Deploy      │       │
│  └───────────────┘  └───────────────┘  └───────────────┘       │
│                              │                                   │
│                              ▼                                   │
│                    ┌───────────────┐                            │
│                    │  ECS Service  │                            │
│                    │    Update     │                            │
│                    └───────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

### Deployment Commands

```bash
# Deploy infrastructure
cd VakInfra
npm install
cdk deploy VakNetworkStack
cdk deploy VakAppStack

# Build and push Docker image
cd ../VakDeepGram
./deploy-to-ecr.sh

# Update ECS service
aws ecs update-service \
  --cluster vak-cluster \
  --service vak-deepgram \
  --force-new-deployment
```

## Configuration Reference

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPGRAM_API_KEY` | Deepgram API key | Yes |
| `DEEPGRAM_PROJECT_ID` | Deepgram project ID | Yes |
| `AWS_REGION` | AWS region | Yes |
| `DDB_TABLE` | DynamoDB table name | Yes |
| `S3_BUCKET` | S3 bucket name | Yes |
| `DEEPGRAM_SPEAKING_PROVIDER` | TTS provider | No |
| `DEEPGRAM_SPEAKING_VOICE_ID` | Voice ID | No |
| `LOG_LEVEL` | Log level | No |
| `CERTIFICATE_ARN` | ACM certificate ARN | No |
| `API_KEY` | WAF API key | No |

### Port Configuration

| Service | Port | Protocol |
|---------|------|----------|
| VakClient (dev) | 5173 | HTTP |
| VakDeepGram | 8080 | HTTP/WS |
| ALB HTTP | 80 | HTTP |
| ALB HTTPS | 443 | HTTPS/WSS |

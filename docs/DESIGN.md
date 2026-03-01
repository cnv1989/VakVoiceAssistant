# Vak (Voice Assistant Kit) Design Document

## Overview

Vak is a comprehensive voice assistant platform that enables businesses to deploy AI-powered voice agents for customer interactions. The system provides real-time voice interaction capabilities, integrating with business platforms like Square and Setmore for appointment booking, customer management, and business operations.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Client Layer                                    │
│  ┌───────────────────────────────┐    ┌───────────────────────────────┐    │
│  │         VakClient             │    │       Phone (Twilio)           │    │
│  │     React + Vite + WS         │    │      PSTN → Media Stream       │    │
│  └───────────────────────────────┘    └───────────────────────────────┘    │
│                │                                     │                       │
│                │ WebSocket                           │ WebSocket             │
│                │ (PCM16 Audio)                       │ (mulaw Audio)         │
│                ▼                                     ▼                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           VakDeepGram Server                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        FastAPI Application                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │   │
│  │  │  /ws        │  │  /twilio    │  │  /chat      │  │  /health   │ │   │
│  │  │  Endpoint   │  │  Endpoint   │  │  Endpoint   │  │  Endpoint  │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Deepgram Handler                                 │   │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐ │   │
│  │  │  Session Mgmt   │    │  Audio Router   │    │  Event Handler  │ │   │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Business Logic Layer                             │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │   │
│  │  │  Strands    │  │  Tool       │  │  Provider   │  │  Context   │ │   │
│  │  │  Agent      │  │  Registry   │  │  Factory    │  │  Store     │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           External Services                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │   Deepgram    │  │  AWS Bedrock  │  │   Square      │  │   Setmore   │  │
│  │   Voice API   │  │   (Claude)    │  │     API       │  │     API     │  │
│  │               │  │               │  │               │  │             │  │
│  │  - STT        │  │  - LLM        │  │  - Bookings   │  │ - Bookings  │  │
│  │  - TTS        │  │  - Reasoning  │  │  - Customers  │  │ - Services  │  │
│  │  - Agent      │  │  - Tools      │  │  - Staff      │  │ - Staff     │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Infrastructure                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │  ECS Fargate  │  │   DynamoDB    │  │      S3       │  │ CloudWatch  │  │
│  │   Cluster     │  │   Sessions    │  │   Artifacts   │  │  Metrics    │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  └─────────────┘  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │     ALB       │  │     WAF       │  │    Cognito    │                   │
│  │  (HTTP/WSS)   │  │  (API Auth)   │  │  (User Auth)  │                   │
│  └───────────────┘  └───────────────┘  └───────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Overview

### VakClient (Frontend)

**Purpose:** Web-based voice interface for direct user interaction

**Technology:**
- React 18.2.0 with Vite 5.0.0
- TypeScript 5.0.0
- WebSocket for real-time communication
- Web Audio API for audio handling

**Key Features:**
- Browser microphone capture (PCM16 @ 48kHz)
- WebSocket audio streaming with AWS SigV4 signing
- Real-time TTS audio playback with barge-in support
- Message pairing (user → agent responses)
- Connection state management

### VakDeepGram (Backend)

**Purpose:** Core voice agent server handling audio processing and business logic

**Technology:**
- FastAPI 0.128.0
- Python 3.8+
- Strands Agents 1.23.0
- Deepgram SDK 5.3.1

**Key Features:**
- WebSocket endpoints for web and Twilio clients
- Deepgram Voice Agent integration
- AI agent with callable business tools
- Session management with DynamoDB
- Rate limiting and authentication

### VakInfra (Infrastructure)

**Purpose:** AWS infrastructure deployment and management

**Technology:**
- AWS CDK v2 (TypeScript)
- CloudFormation

**Key Resources:**
- VPC with public/private subnets
- ECS Fargate cluster
- Application Load Balancer
- DynamoDB tables
- S3 buckets
- WAF WebACL

## Audio Flow

### Web Client Flow
```
┌──────────────┐                    ┌──────────────┐                    ┌──────────────┐
│  Browser     │                    │  VakDeepGram │                    │   Deepgram   │
│  Microphone  │                    │    Server    │                    │  Voice API   │
└──────┬───────┘                    └──────┬───────┘                    └──────┬───────┘
       │                                   │                                   │
       │  PCM16 @ 48kHz (binary)           │                                   │
       │──────────────────────────────────▶│                                   │
       │                                   │  PCM16 @ 48kHz (binary)           │
       │                                   │──────────────────────────────────▶│
       │                                   │                                   │
       │                                   │         STT Processing            │
       │                                   │◀──────────────────────────────────│
       │                                   │                                   │
       │                                   │         LLM + Tools               │
       │                                   │◀─────────────────────────────────▶│
       │                                   │                                   │
       │                                   │         TTS Audio                 │
       │                                   │◀──────────────────────────────────│
       │  PCM16 @ 24kHz (base64)           │                                   │
       │◀──────────────────────────────────│                                   │
       │                                   │                                   │
```

### Twilio Phone Flow
```
┌──────────────┐                    ┌──────────────┐                    ┌──────────────┐
│   Phone      │                    │    Twilio    │                    │  VakDeepGram │
│   (PSTN)     │                    │    Media     │                    │    Server    │
└──────┬───────┘                    └──────┬───────┘                    └──────┬───────┘
       │                                   │                                   │
       │  Analog Voice                     │                                   │
       │──────────────────────────────────▶│                                   │
       │                                   │  mulaw @ 8kHz (base64)            │
       │                                   │──────────────────────────────────▶│
       │                                   │                                   │
       │                                   │         [Processing]              │
       │                                   │                                   │
       │                                   │  mulaw @ 8kHz (base64)            │
       │                                   │◀──────────────────────────────────│
       │  Analog Voice                     │                                   │
       │◀──────────────────────────────────│                                   │
```

## Agent Architecture

### Strands Agent Framework

```
┌─────────────────────────────────────────────────────────────────┐
│                      Strands Agent                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Agent Core                            │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │    │
│  │  │   System    │  │  Reasoning  │  │  Tool           │ │    │
│  │  │   Prompt    │  │   (Claude)  │  │  Execution      │ │    │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘ │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Tool Registry                         │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │    │
│  │  │ Appointments │  │  Customers   │  │    Staff     │  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │    │
│  │  │   Services   │  │ Availability │  │   Booking    │  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Available Tools

| Tool | Description | Provider |
|------|-------------|----------|
| `get_appointments` | Retrieve scheduled appointments | Square/Setmore |
| `get_appointment_details` | Get single appointment info | Square/Setmore |
| `check_availability` | Check open time slots | Square/Setmore |
| `book_appointment` | Create new booking | Square/Setmore |
| `cancel_appointment` | Cancel existing booking | Square/Setmore |
| `get_customers` | List customer records | Square/Setmore |
| `get_customer_info` | Get customer details | Square/Setmore |
| `get_staff` | List staff members | Square/Setmore |
| `get_services` | List available services | Square/Setmore |
| `get_business_info` | Get business details | Square/Setmore |
| `get_business_hours` | Get operating hours | Square/Setmore |

## Session Management

### Session Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Connect   │────▶│   Active    │────▶│   Idle      │────▶│  Cleanup    │
│             │     │             │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │                   │
      │                   │                   │                   │
      ▼                   ▼                   ▼                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Create      │     │ Update      │     │ TTL         │     │ Delete      │
│ DynamoDB    │     │ Context     │     │ Countdown   │     │ Session     │
│ Session     │     │ Store       │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Session Data Structure

```python
{
    "session_id": "uuid",
    "connection_id": "uuid",
    "business_id": "string",
    "provider": "square|setmore",
    "context": {
        "customer": {...},
        "appointments": [...],
        "conversation_history": [...],
    },
    "created_at": "timestamp",
    "updated_at": "timestamp",
    "ttl": "timestamp",  # Auto-cleanup
}
```

## Provider Integration

### Provider Factory Pattern

```python
class ProviderFactory:
    @staticmethod
    def get_provider(provider_type: str, credentials: dict) -> BaseProvider:
        if provider_type == "square":
            return SquareProvider(credentials)
        elif provider_type == "setmore":
            return SetmoreProvider(credentials)
        raise ValueError(f"Unknown provider: {provider_type}")

class BaseProvider(ABC):
    @abstractmethod
    async def get_appointments(self, params: dict) -> list: ...

    @abstractmethod
    async def book_appointment(self, params: dict) -> dict: ...

    @abstractmethod
    async def get_availability(self, params: dict) -> list: ...
```

### Square Provider

```python
class SquareProvider(BaseProvider):
    def __init__(self, credentials: dict):
        self.client = Client(
            access_token=credentials["access_token"],
            environment=Environment.PRODUCTION,
        )

    async def get_appointments(self, params: dict) -> list:
        result = self.client.bookings.list_bookings(
            location_id=params["location_id"],
            start_at_min=params.get("start_date"),
            start_at_max=params.get("end_date"),
        )
        return [self._transform_booking(b) for b in result.bookings]
```

### Setmore Provider

```python
class SetmoreProvider(BaseProvider):
    def __init__(self, credentials: dict):
        self.api_key = credentials["api_key"]
        self.base_url = "https://developer.setmore.com/api/v1"

    async def get_appointments(self, params: dict) -> list:
        response = await self._request(
            "GET",
            "/bookingapi/appointments",
            params=params,
        )
        return [self._transform_appointment(a) for a in response["data"]]
```

## Security Model

### Authentication Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                      Request Flow                                │
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐   │
│  │   Client    │────▶│    ALB      │────▶│   FastAPI       │   │
│  │             │     │             │     │                 │   │
│  └─────────────┘     └─────────────┘     └─────────────────┘   │
│                            │                      │              │
│                            ▼                      ▼              │
│                      ┌─────────────┐     ┌─────────────────┐   │
│                      │    WAF      │     │   Auth          │   │
│                      │  API Key    │     │   Middleware    │   │
│                      │  Check      │     │                 │   │
│                      └─────────────┘     └─────────────────┘   │
│                                                  │              │
│                            ┌─────────────────────┼──────────┐   │
│                            │                     │          │   │
│                            ▼                     ▼          ▼   │
│                      ┌──────────┐         ┌──────────┐ ┌──────┐│
│                      │  OAuth   │         │  API     │ │Twilio││
│                      │  Token   │         │  Key     │ │ Sig  ││
│                      └──────────┘         └──────────┘ └──────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Authentication Methods

| Method | Use Case | Implementation |
|--------|----------|----------------|
| WAF API Key | ALB protection | X-API-Key header checked by WAF |
| OAuth Token | User sessions | Cognito JWT validation |
| API Key | Service accounts | Header-based validation |
| Twilio Signature | Webhook verification | X-Twilio-Signature validation |

### Rate Limiting

```python
# Per-IP limits
limiter = Limiter(key_func=get_remote_address)

@app.websocket("/ws")
@limiter.limit("10/minute")  # Connection limit
async def websocket_endpoint(websocket: WebSocket):
    # Message-level limiting
    message_limiter = MessageLimiter(
        max_messages=100,
        window_seconds=60,
    )
```

## Deployment Architecture

### AWS Resources

```
┌─────────────────────────────────────────────────────────────────┐
│                          VPC                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Public Subnet                         │    │
│  │  ┌─────────────┐              ┌─────────────┐           │    │
│  │  │     ALB     │              │   NAT GW    │           │    │
│  │  └─────────────┘              └─────────────┘           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Private Subnet                        │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │              ECS Fargate Cluster                 │    │    │
│  │  │  ┌─────────────────────────────────────────┐    │    │    │
│  │  │  │         VakDeepGram Service             │    │    │    │
│  │  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐ │    │    │    │
│  │  │  │  │ Task 1  │  │ Task 2  │  │ Task N  │ │    │    │    │
│  │  │  │  └─────────┘  └─────────┘  └─────────┘ │    │    │    │
│  │  │  └─────────────────────────────────────────┘    │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### CDK Stack Structure

```typescript
// VakNetworkStack
- VPC (2 AZs)
- Public/Private Subnets
- NAT Gateway
- ECR Repository

// VakAppStack
- ECS Fargate Cluster
- ECS Service (1 vCPU, 2GB RAM)
- Application Load Balancer
- WAF WebACL (optional)
- DynamoDB Table
- S3 Bucket
- IAM Roles
- CloudWatch Log Groups

// VakMonitoringStack
- CloudWatch Dashboards
- Custom Metrics
- Alarms
```

## Observability

### Logging

```python
# Structured logging
logger.info(
    "Voice agent event",
    extra={
        "connection_id": connection_id,
        "event_type": event_type,
        "session_id": session_id,
        "latency_ms": latency,
    }
)
```

### Metrics

| Metric | Description | Type |
|--------|-------------|------|
| `voice_agent_connections` | Active connections | Gauge |
| `voice_agent_latency` | Response latency | Histogram |
| `voice_agent_tool_calls` | Tool invocations | Counter |
| `voice_agent_errors` | Error count | Counter |
| `audio_bytes_processed` | Audio data volume | Counter |

### Tracing

- OpenTelemetry integration
- Distributed tracing across services
- Request correlation IDs

## Future Considerations

### Scalability
- Horizontal scaling via ECS service auto-scaling
- DynamoDB on-demand capacity
- Connection pooling for external APIs

### Planned Features
- Multi-language support
- Voice authentication (voiceprint)
- Conversation analytics
- Custom agent personalities
- Webhook integrations

### Performance Optimization
- Audio compression
- Response caching
- Connection reuse
- Lazy tool loading

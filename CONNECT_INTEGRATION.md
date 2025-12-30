# Amazon Connect Integration Guide

This guide explains how to integrate the Vak voice assistant service into Amazon Connect contact center.

## Architecture Overview

There are several integration patterns available:

### Pattern 1: Lambda Contact Flow Integration (Recommended)
- **How it works**: Lambda function is invoked during a Contact Flow
- **Audio handling**: Lambda receives/stores audio chunks, processes via Vak service
- **Response**: Lambda streams audio back to Connect or uses text-to-speech
- **Best for**: Real-time voice interactions with full control

### Pattern 2: Lex Bot Integration
- **How it works**: Amazon Lex bot handles natural language understanding
- **Lambda hooks**: Lex can invoke Lambda for custom logic or external services
- **Best for**: Natural language understanding with fallback to agent

### Pattern 3: External Service Bridge (What we'll implement)
- **How it works**: Lambda acts as bridge between Connect and Vak service
- **Audio streaming**: Lambda buffers audio, sends to Vak service in chunks
- **Response streaming**: Lambda receives Vak responses and streams to Connect
- **Best for**: Existing Vak service integration without major changes

## Integration Architecture

### Architecture 1: Direct WebSocket (Chat Contacts)

```
Amazon Connect Chat Contact
         │
         │ (StartChatContact → ParticipantToken)
         ▼
┌─────────────────────┐
│  Vak Service        │  ← Connects directly to Connect WebSocket
│  (ALB/ECS)          │
│  - Connects to      │     via Participant Service API
│    Connect WS       │
│  - Processes chat   │
│  - Sends responses  │
└─────────────────────┘
         │
         │ (WebSocket bidirectional)
         ▼
Amazon Connect Participant Service
```

### Architecture 2: Lambda Bridge (Voice Calls)

```
Amazon Connect Contact Flow (Voice)
         │
         │ (invokes Lambda)
         ▼
┌─────────────────────┐
│  Connect Lambda     │  ← Bridge between Connect and Vak
│  Function           │
│  - Receives audio   │
│  - Calls Vak API    │
│  - Streams response │
└─────────────────────┘
         │
         │ (HTTP/WebSocket to Vak)
         ▼
┌─────────────────────┐
│  Vak Service        │  ← Your existing service
│  (ALB/ECS)          │
│  - Transcribe       │
│  - Bedrock (LLM)    │
│  - Polly (TTS)      │
└─────────────────────┘
```

## Implementation Steps

### Option A: Direct WebSocket Integration (Chat Contacts)

For **chat contacts**, you can use Connect's Participant Service WebSocket directly:

#### Step 1: Connect to Participant Service WebSocket

```typescript
// VakServer/src/routes/connect-participant.ts
import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { ConnectClient, StartChatContactCommand } from '@aws-sdk/client-connect';
import { ConnectParticipantClient, CreateParticipantConnectionCommand, SendMessageCommand } from '@aws-sdk/client-connectparticipant';
import WebSocket from 'ws';

// Store WebSocket connections per contact
const participantConnections = new Map<string, {
  ws: WebSocket;
  participantToken: string;
  connectionToken: string;
}>();

export async function connectParticipantRoute(fastify: FastifyInstance) {
  // Endpoint to initiate Connect chat contact and get WebSocket URL
  fastify.post('/api/connect/start-chat', async (request: FastifyRequest, reply: FastifyReply) => {
    const { instanceId, contactFlowId, participantDetails } = request.body as {
      instanceId: string;
      contactFlowId: string;
      participantDetails: { DisplayName: string };
    };

    try {
      // Step 1: Start chat contact (returns ParticipantToken)
      const connectClient = new ConnectClient({ region: process.env.REGION || 'us-west-2' });
      const startChatResponse = await connectClient.send(new StartChatContactCommand({
        InstanceId: instanceId,
        ContactFlowId: contactFlowId,
        ParticipantDetails: participantDetails,
      }));

      const participantToken = startChatResponse.ParticipantToken!;
      const contactId = startChatResponse.ContactId!;

      // Step 2: Create participant connection (returns WebSocket URL)
      const participantClient = new ConnectParticipantClient({ region: process.env.REGION });
      const connectionResponse = await participantClient.send(new CreateParticipantConnectionCommand({
        Type: ['WEBSOCKET'],
        ParticipantToken: participantToken,
      }));

      const wsUrl = connectionResponse.Websocket?.Url;
      const connectionToken = connectionResponse.ConnectionCredentials?.ConnectionToken;

      if (!wsUrl || !connectionToken) {
        return reply.code(500).send({ error: 'Failed to get WebSocket URL' });
      }

      // Step 3: Connect to Connect's WebSocket
      const ws = new WebSocket(wsUrl);

      // Subscribe to chat events
      ws.on('open', () => {
        const subscribeMessage = {
          topic: 'aws/subscribe',
          content: {
            topics: ['aws/chat'],
          },
        };
        ws.send(JSON.stringify(subscribeMessage));
      });

      // Handle incoming messages from Connect
      ws.on('message', async (data: Buffer) => {
        const message = JSON.parse(data.toString());
        
        if (message.topic === 'aws/chat') {
          const chatMessage = JSON.parse(message.content);
          
          if (chatMessage.Type === 'MESSAGE' && chatMessage.Content) {
            // Forward message to Vak service for processing
            await processConnectMessage(contactId, chatMessage.Content, participantClient, connectionToken);
          }
        }
      });

      // Store connection
      participantConnections.set(contactId, {
        ws,
        participantToken,
        connectionToken: connectionToken!,
      });

      return {
        contactId,
        websocketUrl: wsUrl,
        connectionToken,
      };
    } catch (error) {
      fastify.log.error(`Error starting Connect chat: ${error}`);
      return reply.code(500).send({ error: 'Failed to start chat contact' });
    }
  });
}

async function processConnectMessage(
  contactId: string,
  messageContent: string,
  participantClient: ConnectParticipantClient,
  connectionToken: string
) {
  // Process message through Vak service (your existing logic)
  // For now, let's forward to your existing WebSocket handler logic
  // You can call handleTextMessage or your Bedrock integration
  
  // Generate response using Vak service
  const response = await generateVakResponse(messageContent);
  
  // Send response back to Connect via Participant Service
  await participantClient.send(new SendMessageCommand({
    ConnectionToken: connectionToken,
    Content: response,
    ContentType: 'text/plain',
  }));
}

async function generateVakResponse(message: string): Promise<string> {
  // Use your existing Bedrock integration logic here
  // This is a placeholder - integrate with your actual message handler
  return 'Response from Vak service';
}
```

**Benefits of Direct WebSocket Approach:**
- ✅ No Lambda bridge needed for chat
- ✅ Real-time bidirectional communication
- ✅ Lower latency
- ✅ Direct integration with your Vak WebSocket service

**Limitations:**
- ⚠️ Only works for **chat contacts**, not voice calls
- ⚠️ For voice, you still need Contact Streaming API + Kinesis

### Option B: Lambda Integration (Voice Calls & HTTP-based)

### Step 1: Create Lambda Function for Connect Integration

Create a new Lambda function that acts as a bridge between Connect and Vak:

```typescript
// VakConnect/src/lambda.ts
import { ConnectClient, StartContactStreamingCommand } from '@aws-sdk/client-connect';
import { ConnectContactLensClient, ListRealtimeContactAnalysisSegmentsCommand } from '@aws-sdk/client-connectcontactlens';
import { LambdaClient, InvokeCommand } from '@aws-sdk/client-lambda';

interface ConnectEvent {
  Details: {
    ContactData: {
      Attributes: Record<string, string>;
      Channel: string;
      ContactId: string;
      CustomerEndpoint: {
        Address: string;
        Type: string;
      };
      InitialContactId: string;
      InitiationMethod: string;
      PreviousContactId: string;
      SystemEndpoint: {
        Address: string;
        Type: string;
      };
    };
    Parameters: Record<string, string>;
  };
}

interface ConnectResult {
  statusCode: number;
  [key: string]: any;
}

export const handler = async (event: ConnectEvent): Promise<ConnectResult> => {
  console.log('Connect event:', JSON.stringify(event, null, 2));
  
  const contactId = event.Details.ContactData.ContactId;
  const channel = event.Details.ContactData.Channel;
  
  // Only handle voice calls (not chat)
  if (channel !== 'VOICE') {
    return {
      statusCode: 200,
      message: 'Not a voice contact, skipping Vak integration',
    };
  }
  
  // Initialize Vak service client
  const vakServiceUrl = process.env.VAK_SERVICE_URL || 'http://vak-alb-dns/ws';
  
  try {
    // For voice interactions, we need to:
    // 1. Set up audio streaming from Connect
    // 2. Send audio to Vak service
    // 3. Receive responses and stream back to Connect
    
    // Option A: Use Contact Lens for transcription (recommended)
    // Option B: Use Connect Contact Attributes and Lambda streaming
    // Option C: Call Vak service REST API with transcript
    
    // For now, let's use a simpler approach:
    // Invoke Vak service via HTTP API for text-based interactions
    // Then use Connect's PlayPrompt with SSML for responses
    
    const response = await callVakService({
      contactId,
      message: event.Details.Parameters.message || 'Hello',
    });
    
    return {
      statusCode: 200,
      vakResponse: response.text,
      audioUrl: response.audioUrl, // If Vak provides pre-generated audio
    };
    
  } catch (error) {
    console.error('Error calling Vak service:', error);
    return {
      statusCode: 500,
      error: 'Failed to integrate with Vak service',
    };
  }
};

async function callVakService(params: { contactId: string; message: string }) {
  const vakServiceUrl = process.env.VAK_SERVICE_URL || 'http://vak-alb-dns';
  
  // Call Vak service HTTP endpoint
  const response = await fetch(`${vakServiceUrl}/api/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      contactId: params.contactId,
      message: params.message,
    }),
  });
  
  if (!response.ok) {
    throw new Error(`Vak service returned ${response.status}`);
  }
  
  return await response.json();
}
```

### Step 2: Add HTTP API Endpoint to Vak Server

Add a REST API endpoint that Connect Lambda can call:

```typescript
// VakServer/src/routes/connect-api.ts
import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { handleTextMessage } from './message-handlers';
import { PollyClient, SynthesizeSpeechCommand } from '@aws-sdk/client-polly';

const pollyClient = new PollyClient({ region: process.env.REGION || 'us-west-2' });

export async function connectApiRoute(fastify: FastifyInstance) {
  // REST endpoint for Connect Lambda to call
  fastify.post('/api/connect/message', async (request: FastifyRequest, reply: FastifyReply) => {
    const { contactId, message, audioFormat } = request.body as {
      contactId: string;
      message: string;
      audioFormat?: 'pcm' | 'mp3' | 'ogg_vorbis';
    };
    
    if (!contactId || !message) {
      return reply.code(400).send({ error: 'Missing contactId or message' });
    }
    
    try {
      // Process message through Bedrock (same as text message handler)
      // Generate response text
      const responseText = await processMessage(message);
      
      // Generate audio using Polly (for Connect playback)
      const audioFormatForPolly = audioFormat === 'mp3' ? 'mp3' : 'pcm';
      const pollyCommand = new SynthesizeSpeechCommand({
        Text: responseText,
        OutputFormat: audioFormatForPolly,
        SampleRate: audioFormatForPolly === 'mp3' ? '22050' : '16000',
        VoiceId: 'Joanna', // Can be configurable
        Engine: 'neural',
      });
      
      const pollyResponse = await pollyClient.send(pollyCommand);
      
      // Convert audio stream to base64 or return URL
      if (pollyResponse.AudioStream) {
        const audioBuffer = Buffer.from(await pollyResponse.AudioStream.transformToByteArray());
        const audioBase64 = audioBuffer.toString('base64');
        
        return {
          contactId,
          text: responseText,
          audio: audioBase64,
          audioFormat: audioFormatForPolly,
          contentType: audioFormatForPolly === 'mp3' ? 'audio/mpeg' : 'audio/pcm; rate=16000; channels=1',
        };
      }
      
      return {
        contactId,
        text: responseText,
      };
    } catch (error) {
      fastify.log.error(`Error processing Connect message: ${error}`);
      return reply.code(500).send({ error: 'Failed to process message' });
    }
  });
}

async function processMessage(message: string): Promise<string> {
  // Use existing Bedrock integration logic
  // This is a simplified version - adapt from message-handlers.ts
  // ...
  return 'Response from Vak';
}
```

### Step 3: Contact Flow Configuration

Configure Amazon Connect Contact Flow:

1. **Create Contact Flow in Connect Console**
2. **Add Lambda Invoke Block**:
   - Select your Lambda function
   - Pass contact attributes
   - Store return values in contact attributes

3. **Flow Structure**:
   ```
   Entry Point
   ├─> Get Customer Input (optional)
   ├─> Invoke Lambda Function (Vak Integration)
   ├─> Check Lambda Return Value
   │   ├─> If success: Play Prompt (response)
   │   └─> If error: Transfer to agent
   └─> Loop back or disconnect
   ```

4. **Lambda Parameters** (in Contact Flow):
   ```json
   {
     "message": "$.Attributes.message",
     "contactId": "$.ContactId"
   }
   ```

5. **Store Lambda Response**:
   - Store `vakResponse` in contact attributes
   - Use it in PlayPrompt block

### Step 4: WebSocket Integration (Advanced)

If you want to use WebSocket for real-time streaming, here's how:

#### Option A: Lambda with Persistent WebSocket Connection

```typescript
// VakConnect/src/websocket-lambda.ts
import { WebSocket } from 'ws'; // or use native fetch with WebSocket support
import { ConnectClient, PutMediaCommand } from '@aws-sdk/client-connect';

// Store WebSocket connections per contact (in memory or DynamoDB)
const wsConnections = new Map<string, WebSocket>();

export const websocketHandler = async (event: any) => {
  const contactId = event.Details.ContactData.ContactId;
  const vakWsUrl = process.env.VAK_WS_URL || 'ws://vak-alb-dns/ws';
  
  // Get or create WebSocket connection for this contact
  let ws = wsConnections.get(contactId);
  
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    // Create new WebSocket connection to Vak service
    ws = new WebSocket(vakWsUrl);
    
    // Handle incoming messages from Vak
    ws.on('message', async (data: Buffer) => {
      const message = JSON.parse(data.toString());
      
      if (message.t === 'tts' && message.audio) {
        // Stream audio back to Connect
        // Note: This requires Connect's PutMedia API or similar
        await streamAudioToConnect(contactId, message.audio);
      }
    });
    
    ws.on('error', (error) => {
      console.error(`WebSocket error for ${contactId}:`, error);
      wsConnections.delete(contactId);
    });
    
    ws.on('close', () => {
      console.log(`WebSocket closed for ${contactId}`);
      wsConnections.delete(contactId);
    });
    
    // Wait for connection to open
    await new Promise((resolve, reject) => {
      ws!.on('open', resolve);
      ws!.on('error', reject);
      setTimeout(() => reject(new Error('Connection timeout')), 5000);
    });
    
    wsConnections.set(contactId, ws);
  }
  
  // If we have audio data from Connect, send to Vak
  if (event.Details.Parameters.audioData) {
    const audioBuffer = Buffer.from(event.Details.Parameters.audioData, 'base64');
    ws.send(audioBuffer);
  }
  
  return {
    statusCode: 200,
    connected: true,
  };
};

async function streamAudioToConnect(contactId: string, audioBase64: string) {
  // Use Connect API to play audio
  // This is simplified - actual implementation depends on Connect API used
  // You might need to use Contact Lens streaming or other APIs
}
```

**Challenges with this approach:**
- Lambda containers may be recycled, losing WebSocket connections
- Need to handle reconnection logic
- Connection state management across Lambda invocations
- Consider using Lambda Provisioned Concurrency or containers for persistence

#### Option B: Contact Streaming API + WebSocket Bridge

```typescript
// VakConnect/src/contact-streaming-lambda.ts
import { ConnectClient, StartContactStreamingCommand } from '@aws-sdk/client-connect';
import { KinesisVideoStreamsClient } from '@aws-sdk/client-kinesis-video';
import { WebSocket } from 'ws';

export const contactStreamingHandler = async (event: any) => {
  const contactId = event.contactId;
  const instanceId = process.env.CONNECT_INSTANCE_ID!;
  
  // Start Connect Contact Streaming
  const connectClient = new ConnectClient({ region: process.env.REGION });
  
  // This streams audio to Kinesis Video Streams
  // You then process Kinesis stream and bridge to Vak WebSocket
  const streamingCommand = new StartContactStreamingCommand({
    InstanceId: instanceId,
    ContactId: contactId,
    ChatStreamingConfiguration: {
      StreamingEndpointArn: process.env.KINESIS_STREAM_ARN!,
    },
  });
  
  // Connect to Vak WebSocket
  const vakWs = new WebSocket(process.env.VAK_WS_URL!);
  
  // Bridge Kinesis stream → Vak WebSocket
  // (This requires additional Lambda to process Kinesis stream)
  
  return { statusCode: 200 };
};
```

**This requires:**
1. Kinesis Video Streams setup
2. Lambda function to process Kinesis stream
3. WebSocket connection management
4. Audio format conversion (Connect uses μ-law, Vak uses PCM16)

### Step 5: Infrastructure Updates

Add Lambda function to CDK stack:

```typescript
// VakInfra/lib/vak-connect-stack.ts
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class VakConnectStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    
    // Lambda function for Connect integration
    const connectLambda = new lambda.Function(this, 'VakConnectLambda', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('../VakConnect'),
      environment: {
        VAK_SERVICE_URL: props?.vakServiceUrl || 'http://vak-alb-dns',
        REGION: this.region,
      },
      timeout: cdk.Duration.seconds(30),
    });
    
    // Grant Connect permissions
    connectLambda.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'connect:StartContactStreaming',
          'connect:StopContactStreaming',
        ],
        resources: ['*'],
      })
    );
    
    // Grant VPC access if Vak service is in private subnet
    connectLambda.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'ec2:CreateNetworkInterface',
          'ec2:DescribeNetworkInterfaces',
          'ec2:DeleteNetworkInterface',
        ],
        resources: ['*'],
      })
    );
    
    new cdk.CfnOutput(this, 'ConnectLambdaArn', {
      value: connectLambda.functionArn,
      description: 'Lambda ARN for Connect integration',
      exportName: 'VakConnectLambdaArn',
    });
  }
}
```

## How Amazon Connect Uses WebSocket

You're absolutely right! Amazon Connect DOES use WebSocket, but in specific ways:

### Connect's WebSocket Architecture

1. **Participant Service WebSocket (Chat)**
   - `StartChatContact` → returns `ParticipantToken`
   - `CreateParticipantConnection` → returns WebSocket URL
   - Connect to this WebSocket URL for real-time chat communication
   - **Used for**: Chat interactions between customers and agents

2. **Contact Streaming API (Voice)**
   - Streams audio to **Kinesis Video Streams** (not directly to WebSocket)
   - Requires `StartContactStreaming` API call
   - Audio chunks flow through Kinesis, then can be processed
   - **Used for**: Real-time voice audio streaming

### The Integration Challenge

For **voice calls**, Connect doesn't provide a direct WebSocket endpoint like chat does. Instead:
- Voice audio streams to Kinesis Video Streams
- You need to process Kinesis streams
- Then bridge to your Vak WebSocket service

For **chat contacts**, you CAN use WebSocket directly through Participant Service!

### Direct WebSocket Integration Options

**Option 1: Chat Contact via Participant Service (Direct WebSocket) ✅**
- Use `StartChatContact` → `CreateParticipantConnection` → Get WebSocket URL
- Your service connects directly to Connect's WebSocket
- Bidirectional messaging in real-time
- **Best for**: Chat-based interactions
- **Pros**: Direct WebSocket, official API, real-time
- **Implementation**: Your Vak service acts as a "participant" in the chat

**Option 2: Voice via Contact Streaming API + WebSocket Bridge**
- Use `StartContactStreaming` → Streams to Kinesis Video Streams
- Lambda processes Kinesis stream
- Lambda bridges to Vak WebSocket service
- **Best for**: Real-time voice interactions
- **Pros**: Official streaming API, real-time audio
- **Cons**: Requires Kinesis setup, Lambda bridge layer

**Option 3: Voice via Contact Lens + WebSocket**
- Use Contact Lens for real-time transcription
- Lambda receives transcript events via EventBridge
- Lambda forwards transcripts to Vak via WebSocket
- Vak responds via WebSocket
- Lambda converts response to speech via Connect API
- **Pros**: Real-time transcription, official API
- **Cons**: Transcription-based (not raw audio streaming)

### Recommended Approach by Use Case

**For Chat Contacts: Use WebSocket Directly ✅**
- Connect's Participant Service provides WebSocket URL
- Your Vak service can connect directly as a participant
- Real-time bidirectional communication
- No Lambda bridge needed for chat!

**For Voice Contacts: Multiple Options**

1. **HTTP REST API (Simplest)**
   - ✅ Contact Flows naturally work with Lambda → HTTP calls
   - ✅ No connection lifecycle management needed
   - ✅ Works well with Get Customer Input → Lambda → PlayPrompt pattern
   - ✅ Easier to debug and monitor

2. **WebSocket via Contact Streaming API (Advanced)**
   - ✅ Real-time audio streaming
   - ✅ Lower latency
   - ❌ Requires Kinesis + Lambda bridge setup
   - ❌ More infrastructure complexity

**Use Direct WebSocket when**:
- Chat contacts (Participant Service WebSocket)
- You need sub-second latency for voice
- You're doing real-time audio streaming
- You're comfortable with Kinesis + Lambda bridge architecture

## Integration Patterns

### Pattern A: HTTP REST API (Simpler, Recommended)
1. Connect captures customer input via Get Customer Input (text or transcription)
2. Lambda invokes Vak HTTP API with transcript/text
3. Vak returns text response (and optionally audio)
4. Connect uses PlayPrompt (text-to-speech) to speak response
5. Loop or transfer to agent
6. **Latency**: ~1-3 seconds per turn
7. **Best for**: Most use cases, conversational AI

### Pattern B: WebSocket via Lambda Bridge (Advanced)
1. Lambda function maintains persistent WebSocket connection to Vak
2. Connect streams audio to Lambda via Contact Streaming API
3. Lambda forwards audio chunks to Vak WebSocket in real-time
4. Vak processes and streams audio response back via WebSocket
5. Lambda streams audio response to Connect
6. **Latency**: <500ms per chunk
7. **Best for**: Real-time voice interactions, low latency requirements

### Pattern C: Contact Lens + WebSocket Hybrid
1. Connect Contact Lens provides real-time transcription
2. Lambda receives transcript events via EventBridge
3. Lambda forwards transcripts to Vak via WebSocket
4. Vak streams responses via WebSocket
5. Lambda converts responses to speech and plays via Connect API
6. **Latency**: ~1-2 seconds (transcription delay)
7. **Best for**: Real-time conversations with transcription benefits

## Prerequisites

1. **Amazon Connect Instance**: Create in AWS Console
2. **IAM Permissions**: Lambda needs Connect permissions
3. **Network Access**: Lambda needs access to Vak service (VPC if private)
4. **Audio Format Compatibility**: Ensure audio formats match (Connect uses μ-law/A-law, Vak uses PCM16)

## Testing

1. **Test Lambda locally**:
   ```bash
   aws lambda invoke \
     --function-name VakConnectLambda \
     --payload '{"Details":{"ContactData":{"ContactId":"test-123","Channel":"VOICE"},"Parameters":{"message":"Hello"}}}' \
     output.json
   ```

2. **Test in Connect**:
   - Create test contact flow
   - Invoke Lambda function
   - Call your Connect number
   - Verify Vak responses

## Next Steps

1. Implement Lambda bridge function
2. Add REST API endpoint to Vak server
3. Configure Contact Flow in Connect
4. Test integration
5. Handle errors and fallbacks (transfer to agent)
6. Add logging and monitoring

## References

- [Amazon Connect Lambda Functions](https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html)
- [Connect Contact Streaming API](https://docs.aws.amazon.com/connect/latest/adminguide/contact-lens-streaming.html)
- [Connect Contact Lens](https://docs.aws.amazon.com/connect/latest/adminguide/real-time-contact-lens.html)
- [Lambda Integration with Connect](https://docs.aws.amazon.com/connect/latest/adminguide/lambda-functions.html)


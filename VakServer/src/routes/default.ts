import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { handleTextMessage, handleAudioStream, startTranscriptionSession, stopTranscriptionSession, setConnectionTtsEngine } from './message-handlers';
import { ApiGatewayManagementApiClient, PostToConnectionCommand } from '@aws-sdk/client-apigatewaymanagementapi';
import { validateApiGatewayRequest } from '../middleware/auth';

const region = process.env.REGION || 'us-west-2';
const wsApiEndpoint = process.env.WS_API_ENDPOINT || '';

// Initialize API Gateway client only if endpoint is provided (AWS mode)
let apiGatewayClient: ApiGatewayManagementApiClient | null = null;
if (wsApiEndpoint) {
  apiGatewayClient = new ApiGatewayManagementApiClient({
    region,
    endpoint: wsApiEndpoint,
  });
}

async function sendToClient(connectionId: string, data: any) {
  if (!apiGatewayClient) {
    console.error('API Gateway client not initialized');
    return;
  }
  
  try {
    await apiGatewayClient.send(new PostToConnectionCommand({
      ConnectionId: connectionId,
      Data: JSON.stringify(data),
    }));
  } catch (error: any) {
    if (error.statusCode === 410) {
      // Connection no longer exists
      console.log(`Connection ${connectionId} no longer exists`);
    } else {
      console.error(`Error sending to client: ${error}`);
    }
  }
}

export async function defaultRoute(fastify: FastifyInstance) {
  fastify.post('/default', async (request: FastifyRequest, reply: FastifyReply) => {
    // Validate request comes from API Gateway with IAM authorization
    const isValid = await validateApiGatewayRequest(request, reply);
    if (!isValid) {
      return reply.code(403).send({ 
        error: 'Forbidden',
        message: 'Request must come from API Gateway with valid IAM authorization'
      });
    }

    const connectionId = request.headers['x-amzn-connection-id'] as string;
    
    if (!connectionId) {
      return reply.code(400).send({ error: 'Missing connection ID' });
    }

    const contentType = request.headers['content-type'] || '';

    // Handle binary audio data
    if (contentType.includes('application/octet-stream') || contentType.includes('audio')) {
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of request.raw) {
          chunks.push(Buffer.from(chunk));
        }
        const audioData = Buffer.concat(chunks);
        if (audioData.length > 0) {
          await handleAudioStream(connectionId, audioData, fastify);
          return { status: 'processed', type: 'audio' };
        }
      } catch (error) {
        fastify.log.error(`Error reading audio data: ${error}`);
        return reply.code(500).send({ error: 'Failed to read audio data' });
      }
    }

    // Handle JSON text messages and control messages
    try {
      const body = request.body as any;
      
      if (body && body.action === 'message' && body.text) {
        await handleTextMessage(connectionId, body.text, fastify, sendToClient);
        return { status: 'processed', type: 'text' };
      } else if (body && body.action === 'start-recording') {
        fastify.log.info(`Starting recording for ${connectionId}`);
        await startTranscriptionSession(connectionId, fastify, sendToClient);
        await sendToClient(connectionId, { t: 'recording-started' });
        return { status: 'processed', type: 'start-recording' };
      } else if (body && body.action === 'stop-recording') {
        fastify.log.info(`Stopping recording for ${connectionId}`);
        stopTranscriptionSession(connectionId, fastify);
        await sendToClient(connectionId, { t: 'recording-stopped' });
        return { status: 'processed', type: 'stop-recording' };
      } else if (body && body.action === 'set-tts-engine') {
        const updated = setConnectionTtsEngine(connectionId, body.engine, fastify);
        if (!updated) {
          return reply.code(400).send({ error: 'Invalid TTS engine selection' });
        }
        return { status: 'processed', type: 'set-tts-engine', engine: updated.engine, voice: updated.voice };
      }

      return reply.code(400).send({ error: 'Invalid message format' });
    } catch (error) {
      fastify.log.error(`Error processing default route: ${error}`);
      return reply.code(500).send({ error: 'Failed to process message' });
    }
  });
}

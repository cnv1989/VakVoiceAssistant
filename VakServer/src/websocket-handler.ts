import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import websocket from '@fastify/websocket';
import { handleTextMessage, handleAudioStream, startTranscriptionSession, stopTranscriptionSession, processPauseAndRespond, setConnectionTtsEngine, clearConnectionTtsSettings } from './routes/message-handlers';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, PutCommand, DeleteCommand } from '@aws-sdk/lib-dynamodb';
import { validateWebSocketIamAuth } from './middleware/ws-auth';

const ddbClient = new DynamoDBClient({ region: process.env.REGION || 'us-west-2' });
const docClient = DynamoDBDocumentClient.from(ddbClient);
const tableName = process.env.DDB_TABLE || 'Sessions';

// Store active WebSocket connections
const connections = new Map<string, any>();

function sendToClientLocal(connectionId: string, data: any, fastify?: FastifyInstance): void {
  const connection = connections.get(connectionId);
  if (connection && connection.socket.readyState === 1) { // WebSocket.OPEN
    try {
      const message = JSON.stringify(data);
      connection.socket.send(message);
      
      // Log partial transcripts for debugging (but not every one to avoid spam)
      if (fastify && data.t === 'partial-transcript' && data.text) {
        // Only log if transcript changed significantly or is first one
        if (!connection.lastPartialTranscript || 
            data.text.length - connection.lastPartialTranscript.length > 10 ||
            !data.text.startsWith(connection.lastPartialTranscript)) {
          fastify.log.info(`📤 Sent partial transcript to ${connectionId}: "${data.text}"`);
          connection.lastPartialTranscript = data.text;
        }
      }
    } catch (error) {
      if (fastify) {
        fastify.log.error(`Error sending to client ${connectionId}: ${error}`);
      } else {
        console.error(`Error sending to client ${connectionId}: ${error}`);
      }
    }
  } else {
    const state = connection?.socket.readyState;
    if (fastify) {
      fastify.log.warn(`Cannot send to client ${connectionId}: WebSocket not open (state: ${state})`);
    }
  }
}

export async function registerWebSocketHandler(fastify: FastifyInstance) {
  await fastify.register(websocket);
  
  // WebSocket endpoint - IAM authentication is optional
  // Note: Browser WebSocket API doesn't support custom headers, so IAM auth
  // validation is disabled by default. Enable it by setting REQUIRE_IAM_AUTH=true
  fastify.get('/ws', { 
    websocket: true,
    preHandler: async (request: FastifyRequest, reply: FastifyReply) => {
      // Skip IAM validation for local mode
      const localMode = process.env.LOCAL_MODE === 'true' || !process.env.ALB_DNS;
      if (localMode) {
        return;
      }

      // IAM authentication is optional (disabled by default due to browser limitations)
      const requireIamAuth = process.env.REQUIRE_IAM_AUTH === 'true';
      if (requireIamAuth) {
        // Validate IAM signature for WebSocket upgrade request
        const isValid = await validateWebSocketIamAuth(request);
        if (!isValid) {
          reply.code(403).send({ 
            error: 'Forbidden',
            message: 'WebSocket connection requires valid IAM authentication'
          });
          return;
        }
      } else {
        // Log connection attempt (IAM auth disabled)
        fastify.log.info('WebSocket connection attempt (IAM auth disabled)');
      }
    }
  }, (connection, req) => {
      const connectionId = `ws-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      connections.set(connectionId, connection);

      fastify.log.info(`WebSocket connection established: ${connectionId}`);

      // Handle connection
      handleConnection(connectionId, fastify);

      connection.socket.on('message', async (message: Buffer | string) => {
        try {
          // Handle text messages (JSON)
          if (typeof message === 'string') {
            try {
              const data = JSON.parse(message);
              
              if (data.action === 'message' && data.text) {
                await handleTextMessage(connectionId, data.text, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
              } else if (data.action === 'start-recording') {
                // Start a new transcription session
                fastify.log.info(`Starting recording for ${connectionId}`);
                await startTranscriptionSession(connectionId, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
                sendToClientLocal(connectionId, { t: 'recording-started' }, fastify);
              } else if (data.action === 'pause-detected') {
                // Pause detected - process accumulated audio
                fastify.log.info(`Pause detected for ${connectionId}, processing audio`);
                sendToClientLocal(connectionId, { t: 'processing-audio' }, fastify);
                await processPauseAndRespond(connectionId, fastify, sendToClientLocal);
              } else if (data.action === 'set-tts-engine') {
                const updated = setConnectionTtsEngine(connectionId, data.engine, fastify);
                if (!updated) {
                  sendToClientLocal(connectionId, { t: 'error', message: 'Invalid TTS engine selection' }, fastify);
                }
              } else if (data.t === 'ready-to-listen') {
                // Client finished playing audio, ready for next input
                // Start a new transcription session for continuous conversation
                fastify.log.info(`Client ${connectionId} ready to listen, starting new session`);
                await startTranscriptionSession(connectionId, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
                sendToClientLocal(connectionId, { t: 'ready-to-listen' }, fastify);
              } else if (data.action === 'stop-recording') {
                // Stop the active transcription session
                fastify.log.info(`Stopping recording for ${connectionId}`);
                stopTranscriptionSession(connectionId, fastify);
                sendToClientLocal(connectionId, { t: 'recording-stopped' }, fastify);
              } else {
                fastify.log.warn(`Unknown message format: ${JSON.stringify(data)}`);
              }
            } catch (e) {
              fastify.log.error(`Error parsing JSON message: ${e}`);
            }
          } 
          // Handle binary messages (audio or JSON as binary)
          else if (Buffer.isBuffer(message)) {
            // Check if it's likely JSON by looking at first byte (JSON starts with '{' or '[')
            const firstByte = message[0];
            const isLikelyJson = firstByte === 0x7B || firstByte === 0x5B; // '{' or '['
            
            if (isLikelyJson) {
              // Try to parse as JSON first (client might send JSON as binary)
              try {
                const text = message.toString('utf-8');
                const data = JSON.parse(text);
                
                if (data.action === 'message' && data.text) {
                  await handleTextMessage(connectionId, data.text, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
                } else if (data.action === 'start-recording') {
                  // Server generates message ID, no need to accept from client
                  await startTranscriptionSession(connectionId, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
                  sendToClientLocal(connectionId, { t: 'recording-started' }, fastify);
                } else if (data.action === 'set-tts-engine') {
                  const updated = setConnectionTtsEngine(connectionId, data.engine, fastify);
                  if (!updated) {
                    sendToClientLocal(connectionId, { t: 'error', message: 'Invalid TTS engine selection' }, fastify);
                  }
                } else if (data.t === 'ready-to-listen') {
                  fastify.log.info(`Client ${connectionId} ready to listen, starting new session`);
                  await startTranscriptionSession(connectionId, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
                  sendToClientLocal(connectionId, { t: 'ready-to-listen' }, fastify);
                } else if (data.action === 'stop-recording') {
                  stopTranscriptionSession(connectionId, fastify);
                  sendToClientLocal(connectionId, { t: 'recording-stopped' }, fastify);
                } else {
                  fastify.log.warn(`Unknown message format: ${JSON.stringify(data)}`);
                }
              } catch (e) {
                // Not valid JSON, treat as binary audio (PCM16)
                fastify.log.info(`🎤 Received binary PCM16 audio chunk: ${message.length} bytes for ${connectionId}`);
                await handleAudioStream(connectionId, message, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
              }
            } else {
              // Not JSON (doesn't start with '{' or '['), treat as binary audio (PCM16)
              fastify.log.info(`🎤 Received binary PCM16 audio chunk: ${message.length} bytes for ${connectionId}`);
              await handleAudioStream(connectionId, message, fastify, (id, msg) => sendToClientLocal(id, msg, fastify));
            }
          } else {
            fastify.log.warn(`Unknown message type: ${typeof message}`);
          }
        } catch (error) {
          fastify.log.error(`Error handling WebSocket message: ${error}`);
          sendToClientLocal(connectionId, { t: 'error', message: 'Failed to process message' }, fastify);
        }
      });

      connection.socket.on('close', () => {
        fastify.log.info(`WebSocket connection closed: ${connectionId}`);
        // Clean up any active transcription session
        stopTranscriptionSession(connectionId, fastify);
        clearConnectionTtsSettings(connectionId, fastify);
        handleDisconnection(connectionId, fastify);
        connections.delete(connectionId);
      });

      connection.socket.on('error', (error: Error) => {
        fastify.log.error(`WebSocket error for ${connectionId}: ${error}`);
        // Clean up any active transcription session
        stopTranscriptionSession(connectionId, fastify);
        clearConnectionTtsSettings(connectionId, fastify);
        connections.delete(connectionId);
      });
    });
}

async function handleConnection(connectionId: string, fastify: FastifyInstance) {
  const ttl = Math.floor(Date.now() / 1000) + 3600; // 1 hour TTL
  
  try {
    await docClient.send(new PutCommand({
      TableName: tableName,
      Item: {
        sid: connectionId,
        ttl,
        createdAt: new Date().toISOString(),
      },
    }));
    fastify.log.info(`Session stored: ${connectionId}`);
  } catch (error) {
    fastify.log.error(`Error storing session: ${error}`);
  }
}

async function handleDisconnection(connectionId: string, fastify: FastifyInstance) {
  try {
    await docClient.send(new DeleteCommand({
      TableName: tableName,
      Key: { sid: connectionId },
    }));
    fastify.log.info(`Session removed: ${connectionId}`);
  } catch (error) {
    fastify.log.error(`Error removing session: ${error}`);
  }
}

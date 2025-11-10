import { FastifyInstance } from 'fastify';
import { BedrockRuntimeClient, InvokeModelWithResponseStreamCommand } from '@aws-sdk/client-bedrock-runtime';
import { TranscribeStreamingClient, StartStreamTranscriptionCommand, AudioStream } from '@aws-sdk/client-transcribe-streaming';
import { PollyClient, SynthesizeSpeechCommand } from '@aws-sdk/client-polly';
import { ApiGatewayManagementApiClient, PostToConnectionCommand } from '@aws-sdk/client-apigatewaymanagementapi';
import { Readable } from 'stream';

const region = process.env.REGION || 'us-west-2';
const wsApiEndpoint = process.env.WS_API_ENDPOINT || '';
const modelId = process.env.MODEL_ID || 'anthropic.claude-3-haiku-20240307-v1:0';
// Use generative voice by default (Ruth is a generative voice)
// Other generative voices include: Stephen, Gregory, Danielle, Burcu, Jitka, Sabrina, Jasmine, Jihye
const pollyVoice = process.env.POLLY_VOICE || 'Ruth';
const pollyEngine = process.env.POLLY_ENGINE || 'generative'; // 'standard', 'neural', or 'generative'
const pollyStandardVoice = process.env.POLLY_STANDARD_VOICE || 'Joanna';
const pollyNeuralVoice = process.env.POLLY_NEURAL_VOICE || 'Joanna';

type PollyEngineType = 'standard' | 'neural' | 'generative';

interface TtsSettings {
  engine: PollyEngineType;
  voice: string;
}

const connectionTtsSettings = new Map<string, TtsSettings>();

const DEFAULT_TTS_SETTINGS = resolveTtsSettings(pollyEngine);

function normalizePollyEngineInput(engine?: string | null): PollyEngineType | null {
  if (!engine) {
    return null;
  }
  const value = engine.toLowerCase();
  switch (value) {
    case 'polly-standard':
    case 'standard':
      return 'standard';
    case 'polly-neural':
    case 'neural':
      return 'neural';
    case 'polly-generative':
    case 'generative':
      return 'generative';
    default:
      return null;
  }
}

function toTtsSettings(engine: PollyEngineType): TtsSettings {
  switch (engine) {
    case 'standard':
      return { engine: 'standard', voice: pollyStandardVoice };
    case 'neural':
      return { engine: 'neural', voice: pollyNeuralVoice };
    case 'generative':
    default:
      return { engine: 'generative', voice: pollyVoice };
  }
}

function resolveTtsSettings(engine?: string | null): TtsSettings {
  const normalized = normalizePollyEngineInput(engine);
  if (normalized) {
    return toTtsSettings(normalized);
  }
  return toTtsSettings('generative');
}

export function setConnectionTtsEngine(
  connectionId: string,
  engine: string | null | undefined,
  fastify: FastifyInstance
): TtsSettings | null {
  const normalized = normalizePollyEngineInput(engine);
  if (!normalized) {
    fastify.log.warn(`⚠️ Received unsupported Polly engine "${engine}" for ${connectionId}`);
    return null;
  }

  const settings = toTtsSettings(normalized);
  connectionTtsSettings.set(connectionId, settings);
  fastify.log.info(`🎛️ Set TTS engine for ${connectionId} -> engine=${settings.engine}, voice=${settings.voice}`);
  return settings;
}

export function getConnectionTtsSettings(connectionId: string): TtsSettings {
  return connectionTtsSettings.get(connectionId) ?? DEFAULT_TTS_SETTINGS;
}

export function clearConnectionTtsSettings(connectionId: string, fastify?: FastifyInstance) {
  if (connectionTtsSettings.delete(connectionId) && fastify) {
    fastify.log.info(`🧹 Cleared TTS settings for ${connectionId}`);
  }
}

const bedrockClient = new BedrockRuntimeClient({ region });
const transcribeClient = new TranscribeStreamingClient({ region });
const pollyClient = new PollyClient({ region });

// Stream management: track active transcription sessions per connection
interface TranscriptionSession {
  audioChunks: Buffer[];
  isActive: boolean;
  transcriptionPromise: Promise<void> | null;
  abortController: AbortController;
  lastChunkTime: number;
  pauseDetectionTimer: NodeJS.Timeout | null;
  hasReceivedSpeech: boolean; // Track if we've received any audio chunks
  chunksReceived: number; // Track total chunks received
  chunksProcessed: number; // Track chunks sent to AWS Transcribe
  lastPartialTranscript?: string; // Track last partial transcript to avoid duplicate logs
  messageId?: string; // Track message ID for current utterance (generated on first partial transcript)
  hasGeneratedMessageId: boolean; // Track if we've generated a message ID for the current utterance
}

const transcriptionSessions = new Map<string, TranscriptionSession>();

// Pause detection configuration
const PAUSE_THRESHOLD_MS = 1500; // 1.5 seconds of silence triggers pause

// Initialize API Gateway client only if endpoint is provided (AWS mode)
let apiGatewayClient: ApiGatewayManagementApiClient | null = null;
if (wsApiEndpoint) {
  apiGatewayClient = new ApiGatewayManagementApiClient({
    region,
    endpoint: wsApiEndpoint,
  });
}

export type SendToClientFunction = (connectionId: string, data: any) => Promise<void> | void;

// Default send function for API Gateway mode
async function sendToClientApiGateway(connectionId: string, data: any) {
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

export async function handleTextMessage(
  connectionId: string,
  text: string,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction = sendToClientApiGateway,
  messageId?: string
) {
  try {
    // Send to Bedrock
    const command = new InvokeModelWithResponseStreamCommand({
      modelId,
      contentType: 'application/json',
      accept: 'application/json',
      body: JSON.stringify({
        anthropic_version: 'bedrock-2023-05-31',
        max_tokens: 1024,
        messages: [
          {
            role: 'user',
            content: text,
          },
        ],
      }),
    });

    const response = await bedrockClient.send(command);
    
    if (response.body) {
      let fullResponse = '';
      
      for await (const chunk of response.body) {
        if (chunk.chunk) {
          const chunkData = JSON.parse(new TextDecoder().decode(chunk.chunk.bytes));
          
          if (chunkData.type === 'content_block_delta' && chunkData.delta?.text) {
            const token = chunkData.delta.text;
            fullResponse += token;
            
            // Send streaming token to client with message ID
            await sendToClient(connectionId, { t: 'llm-token', token, messageId });
          }
        }
      }

      const ttsSettings = getConnectionTtsSettings(connectionId);
      const pollyCommand = new SynthesizeSpeechCommand({
        Text: fullResponse,
        OutputFormat: 'pcm',
        SampleRate: '16000',
        VoiceId: ttsSettings.voice as any,
        Engine: ttsSettings.engine as any,
      });
      
      fastify.log.info(`🎤 Synthesizing speech with Polly: voice=${ttsSettings.voice}, engine=${ttsSettings.engine}`);

      const pollyResponse = await pollyClient.send(pollyCommand);
      
      if (pollyResponse.AudioStream) {
        const audioChunks: Buffer[] = [];
        const audioStream = pollyResponse.AudioStream as Readable;
        
        for await (const chunk of audioStream) {
          audioChunks.push(Buffer.from(chunk));
        }

        const audioBuffer = Buffer.concat(audioChunks);
        
        // Send PCM audio chunks to client (chunk size: 3200 bytes = 100ms at 16kHz)
        const chunkSize = 3200;
        for (let i = 0; i < audioBuffer.length; i += chunkSize) {
          const chunk = audioBuffer.slice(i, i + chunkSize);
          await sendToClient(connectionId, {
            t: 'tts',
            audio: chunk.toString('base64'),
            messageId, // Include messageId with each TTS chunk for proper message pairing
          });
        }
        
        // After all audio chunks are sent, signal ready to listen (for telephony mode)
        // The client will send ready-to-listen when audio finishes playing
      }
    }
  } catch (error) {
    fastify.log.error(`Error handling text message: ${error}`);
    await sendToClient(connectionId, { t: 'error', message: 'Failed to process message' });
  }
}

/**
 * Generate a unique message ID
 */
function generateMessageId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

/**
 * Process pause detection - stop transcription and wait for it to complete
 */
export async function processPauseAndRespond(
  connectionId: string,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction = sendToClientApiGateway
) {
  const session = transcriptionSessions.get(connectionId);
  
  if (!session) {
    fastify.log.warn(`No active transcription session for ${connectionId}`);
    // Still send ready-to-listen to continue the conversation
    await sendToClient(connectionId, { t: 'ready-to-listen' });
    return;
  }

  // Don't generate message ID here - it should already be generated when first partial transcript arrives
  // Just use the existing message ID from the session
  const messageId = session.messageId;
  if (messageId) {
    fastify.log.info(`⏸️ Pause detected, using existing message ID: ${messageId} (connection: ${connectionId})`);
  } else {
    fastify.log.warn(`⏸️ Pause detected but no message ID exists yet (connection: ${connectionId})`);
  }

  // Clear pause detection timer
  if (session.pauseDetectionTimer) {
    clearTimeout(session.pauseDetectionTimer);
    session.pauseDetectionTimer = null;
  }

  // Stop the session (it will process remaining chunks)
  session.isActive = false;
  
  // Wait for transcription to complete (with timeout)
  const timeout = 10000; // 10 seconds max
  const startTime = Date.now();
  
  while (transcriptionSessions.has(connectionId) && (Date.now() - startTime) < timeout) {
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  
  // Transcription should have completed and processed the audio
  // The handleTextMessage will have been called automatically
  // Client will send ready-to-listen when audio finishes playing
  fastify.log.info(`Pause processing completed for ${connectionId} (messageId: ${messageId})`);
}

/**
 * Start a new transcription session for a connection
 */
export async function startTranscriptionSession(
  connectionId: string,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction = sendToClientApiGateway
) {
  // Clean up any existing session
  stopTranscriptionSession(connectionId, fastify);

  // Don't generate message ID here - wait for first partial transcript
  // Message ID will be generated when we receive the first partial transcript
  const session: TranscriptionSession = {
    audioChunks: [],
    isActive: true,
    transcriptionPromise: null,
    abortController: new AbortController(),
    lastChunkTime: Date.now(),
    pauseDetectionTimer: null,
    hasReceivedSpeech: false,
    chunksReceived: 0,
    chunksProcessed: 0,
    lastPartialTranscript: undefined,
    messageId: undefined, // Will be generated on first partial transcript
    hasGeneratedMessageId: false, // Track if we've generated a message ID for current utterance
  };

  transcriptionSessions.set(connectionId, session);
  
  fastify.log.info(`🎤 Started new transcription session for ${connectionId} (message ID will be generated on first partial transcript)`);

  // Create async generator for audio stream
  const audioStream = async function* (): AsyncIterable<AudioStream> {
    let consecutiveEmptyChecks = 0;
    const maxEmptyChecks = 1500; // Allow up to 15 seconds of waiting (1500 * 10ms)
    const waitInterval = 10; // Check every 10ms
    
    fastify.log.info(`Audio stream generator started for ${connectionId}`);
    
    // Wait for audio chunks to arrive
    while (true) {
      // Check if aborted first
      if (session.abortController.signal.aborted) {
        fastify.log.info(`Audio stream generator aborted for ${connectionId}`);
        break;
      }
      
      if (session.audioChunks.length > 0) {
        // Send all pending chunks immediately
        const chunks = session.audioChunks.splice(0);
        consecutiveEmptyChecks = 0; // Reset counter when we have chunks
        
        session.chunksProcessed += chunks.length;
        fastify.log.info(`📤 Yielding ${chunks.length} chunks to AWS Transcribe for ${connectionId} (total bytes: ${chunks.reduce((sum, c) => sum + c.length, 0)}, received: ${session.chunksReceived}, processed: ${session.chunksProcessed})`);
        
        for (const chunk of chunks) {
          if (session.abortController.signal.aborted) {
            fastify.log.info(`Audio stream generator aborted during chunk yield for ${connectionId}`);
            return; // Stop if aborted
          }
          
          try {
            yield {
              AudioEvent: {
                AudioChunk: new Uint8Array(chunk),
              },
            };
          } catch (error) {
            fastify.log.error(`Error yielding audio chunk: ${error}`);
            throw error;
          }
        }
        
        // After yielding chunks, continue immediately without waiting
        continue;
      } else {
        // No chunks available - check if session is still active
        if (!session.isActive) {
          consecutiveEmptyChecks++;
          if (consecutiveEmptyChecks >= maxEmptyChecks) {
            fastify.log.info(`Audio stream generator ending: session inactive and no chunks for ${connectionId}`);
            break; // No more chunks and session is inactive
          }
        } else {
          // Session is active but no chunks yet - reset counter to allow waiting
          consecutiveEmptyChecks = 0;
        }
        
        // Wait a bit before checking again (but not too long to avoid timeout)
        await new Promise(resolve => setTimeout(resolve, waitInterval));
      }
    }
    
    fastify.log.info(`Audio stream generator ended for ${connectionId}`);
  };

  // Start transcription command
  // AWS Transcribe Streaming supports PCM encoding with sample rates: 8000, 16000, 24000, 48000 Hz
  // Using PCM16 (16-bit signed integers, little-endian) at 16kHz - simpler than Opus
  const command = new StartStreamTranscriptionCommand({
    LanguageCode: 'en-US',
    MediaSampleRateHertz: 16000, // 16kHz sample rate
    MediaEncoding: 'pcm', // PCM16 format (16-bit signed integers, little-endian)
    AudioStream: audioStream(),
  });
  
  fastify.log.info(`🎙️ Starting AWS Transcribe session for ${connectionId} with format: PCM16 @ 16kHz`);

  // Process transcription asynchronously
  session.transcriptionPromise = (async () => {
    try {
      fastify.log.info(`🎤 Starting transcription stream for ${connectionId} (format: PCM16 @ 16kHz)`);
      const response = await transcribeClient.send(command);
      
      if (response.TranscriptResultStream) {
        let eventCount = 0;
        for await (const event of response.TranscriptResultStream) {
          if (session.abortController.signal.aborted) {
            fastify.log.info(`⏹️ Transcription stream aborted for ${connectionId}`);
            break;
          }

          eventCount++;
          
          // Log errors if present
          if (event.BadRequestException) {
            fastify.log.error(`❌ AWS Transcribe BadRequestException for ${connectionId}: ${JSON.stringify(event.BadRequestException)}`);
            await sendToClient(connectionId, { 
              t: 'error', 
              message: `Transcription error: ${event.BadRequestException.Message || 'Bad request'}` 
            });
            break;
          }
          if (event.LimitExceededException) {
            fastify.log.error(`❌ AWS Transcribe LimitExceededException for ${connectionId}: ${JSON.stringify(event.LimitExceededException)}`);
            await sendToClient(connectionId, { 
              t: 'error', 
              message: `Transcription limit exceeded: ${event.LimitExceededException.Message || 'Rate limit exceeded'}` 
            });
            break;
          }
          if (event.InternalFailureException) {
            fastify.log.error(`❌ AWS Transcribe InternalFailureException for ${connectionId}: ${JSON.stringify(event.InternalFailureException)}`);
            await sendToClient(connectionId, { 
              t: 'error', 
              message: `Transcription service error: ${event.InternalFailureException.Message || 'Internal failure'}` 
            });
            break;
          }
          
          fastify.log.debug(`📝 Received transcription event ${eventCount} for ${connectionId}`);

          if (event.TranscriptEvent?.Transcript?.Results) {
            const results = event.TranscriptEvent.Transcript.Results;
            for (const result of results) {
              if (result.Alternatives && result.Alternatives.length > 0) {
                const transcript = result.Alternatives[0].Transcript;
                if (transcript) {
                  if (result.IsPartial) {
                    // Generate new message ID on first partial transcript (new utterance detected)
                    if (!session.hasGeneratedMessageId) {
                      const newMessageId = generateMessageId();
                      session.messageId = newMessageId;
                      session.hasGeneratedMessageId = true;
                      fastify.log.info(`🆔 Generated new message ID for first partial transcript: ${newMessageId} (connection: ${connectionId})`);
                      
                      // Send message ID to client so it can create a message pair entry
                      await sendToClient(connectionId, { 
                        t: 'message-id', 
                        messageId: newMessageId 
                      });
                    }
                    
                    // Send partial transcript with current message ID
                    const currentMessageId = session.messageId;
                    fastify.log.info(`💬 Partial transcription for ${connectionId}: "${transcript}" (messageId: ${currentMessageId})`);
                    try {
                      await sendToClient(connectionId, { 
                        t: 'partial-transcript', 
                        text: transcript,
                        isPartial: true,
                        messageId: currentMessageId // Use server-generated messageId
                      });
                    } catch (sendError) {
                      fastify.log.error(`Error sending partial transcript: ${sendError}`);
                    }
                  } else {
                    // Final transcript - process it
                    // Ensure we have a message ID (should exist from partial transcript, but handle edge case)
                    if (!session.messageId) {
                      const newMessageId = generateMessageId();
                      session.messageId = newMessageId;
                      session.hasGeneratedMessageId = true;
                      fastify.log.warn(`⚠️ Final transcript received but no message ID exists, generating: ${newMessageId} (connection: ${connectionId})`);
                      
                      // Send message ID to client
                      await sendToClient(connectionId, { 
                        t: 'message-id', 
                        messageId: newMessageId 
                      });
                    }
                    
                    const currentMessageId = session.messageId;
                    fastify.log.info(`✅ Final transcription for ${connectionId}: "${transcript}" (messageId: ${currentMessageId})`);
                    
                    // Clear partial transcript state and reset message ID generation flag for next utterance
                    session.lastPartialTranscript = undefined;
                    session.hasGeneratedMessageId = false; // Reset for next utterance
                    
                    // Send final transcript to client with server-generated message ID
                    try {
                      await sendToClient(connectionId, { 
                        t: 'transcript', 
                        text: transcript,
                        isPartial: false,
                        messageId: currentMessageId // Use server-generated messageId for pairing
                      });
                      
                      // Process transcript as text message with server-generated message ID
                      await handleTextMessage(connectionId, transcript, fastify, sendToClient, currentMessageId);
                    } catch (sendError) {
                      fastify.log.error(`❌ Error sending final transcript to ${connectionId}: ${sendError}`);
                    }
                  }
                }
              }
            }
          } else {
            fastify.log.debug(`Transcription event ${eventCount} for ${connectionId} has no results`);
          }
        }
        fastify.log.info(`Transcription stream ended for ${connectionId} (${eventCount} events processed)`);
      } else {
        fastify.log.warn(`No TranscriptResultStream in response for ${connectionId}`);
      }
    } catch (error: any) {
      if (!session.abortController.signal.aborted) {
        fastify.log.error(`❌ Failed to process audio transcription for ${connectionId}: ${error}`);
        
        // Check for specific AWS Transcribe errors
        if (error.name === 'BadRequestException') {
          fastify.log.error(`❌ AWS Transcribe BadRequestException: ${error.message}`);
          await sendToClient(connectionId, { 
            t: 'error', 
            message: `Transcription error: Invalid audio format or configuration. ${error.message || 'Bad request'}` 
          });
        } else if (error.name === 'LimitExceededException') {
          fastify.log.error(`❌ AWS Transcribe LimitExceededException: ${error.message}`);
          await sendToClient(connectionId, { 
            t: 'error', 
            message: `Transcription limit exceeded: ${error.message || 'Rate limit exceeded'}` 
          });
        } else if (error.message && error.message.includes('timeout')) {
          fastify.log.error(`⏱️ AWS Transcribe timeout: ${error.message}`);
          await sendToClient(connectionId, { 
            t: 'error', 
            message: `Transcription timeout: No audio received for 15 seconds. ${error.message}` 
          });
        } else {
          // Generic error
          try {
            await sendToClient(connectionId, { 
              t: 'error', 
              message: `Failed to process audio transcription: ${error.message || error}` 
            });
          } catch (sendError) {
            fastify.log.error(`Error sending error message to client: ${sendError}`);
          }
        }
      } else {
        fastify.log.info(`Transcription session ${connectionId} was aborted (error ignored)`);
      }
    } finally {
      // Mark session as inactive
      session.isActive = false;
      fastify.log.info(`🔚 Transcription session marked as inactive for ${connectionId}`);
    }
  })();

  fastify.log.info(`Started transcription session for ${connectionId}`);
}

/**
 * Stop an active transcription session
 */
export function stopTranscriptionSession(
  connectionId: string,
  fastify: FastifyInstance
) {
  const session = transcriptionSessions.get(connectionId);
  if (session) {
    session.isActive = false;
    
    // Clear pause detection timer
    if (session.pauseDetectionTimer) {
      clearTimeout(session.pauseDetectionTimer);
      session.pauseDetectionTimer = null;
    }
    
    // Don't abort immediately - let remaining chunks be processed
    // The async generator will stop after processing remaining chunks
    fastify.log.info(`Stopped transcription session for ${connectionId} (processing remaining chunks)`);
    
    // Set a timeout to force abort if session doesn't end naturally
    setTimeout(() => {
      if (transcriptionSessions.has(connectionId)) {
        const s = transcriptionSessions.get(connectionId);
        if (s?.pauseDetectionTimer) {
          clearTimeout(s.pauseDetectionTimer);
        }
        session.abortController.abort();
        transcriptionSessions.delete(connectionId);
        fastify.log.info(`Force cleaned up transcription session for ${connectionId}`);
      }
    }, 2000); // 2 second timeout
  }
}

/**
 * Check for pause and process if detected
 */
async function checkForPause(
  connectionId: string,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction
) {
  const session = transcriptionSessions.get(connectionId);
  if (!session || !session.isActive) {
    return;
  }

  const now = Date.now();
  const timeSinceLastChunk = now - session.lastChunkTime;

  // If we've received speech and silence exceeds threshold, detect pause
  if (session.hasReceivedSpeech && timeSinceLastChunk >= PAUSE_THRESHOLD_MS) {
    fastify.log.info(`Server-side pause detected for ${connectionId} (${timeSinceLastChunk}ms silence)`);
    
    // Clear any existing timer
    if (session.pauseDetectionTimer) {
      clearTimeout(session.pauseDetectionTimer);
      session.pauseDetectionTimer = null;
    }

    // Process the pause
    await sendToClient(connectionId, { t: 'processing-audio' });
    await processPauseAndRespond(connectionId, fastify, sendToClient);
  }
}

/**
 * Append audio chunk to active transcription session and detect pauses
 */
export async function handleAudioStream(
  connectionId: string,
  audioData: Buffer,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction = sendToClientApiGateway
) {
  // Validate audio data
  if (!audioData || audioData.length === 0) {
    fastify.log.warn(`⚠️ Received empty audio chunk for ${connectionId}`);
    return;
  }
  
  // Validate audio chunk size (PCM16 chunks should be reasonable size)
  // PCM16 at 16kHz: 4096 samples = 8192 bytes (typical chunk size)
  // Very small chunks (< 10 bytes) might be invalid, very large (> 1MB) might indicate corruption
  if (audioData.length < 10) {
    fastify.log.warn(`⚠️ Received suspiciously small audio chunk for ${connectionId}: ${audioData.length} bytes`);
    return;
  }
  if (audioData.length > 1024 * 1024) {
    fastify.log.warn(`⚠️ Received suspiciously large audio chunk for ${connectionId}: ${audioData.length} bytes`);
    return;
  }
  
  // Validate PCM16 format (should be even number of bytes, as each sample is 2 bytes)
  if (audioData.length % 2 !== 0) {
    fastify.log.warn(`⚠️ Received odd-sized PCM16 chunk for ${connectionId}: ${audioData.length} bytes (should be even)`);
    return;
  }
  
  // Log chunk info for debugging
  const sampleCount = audioData.length / 2;
  fastify.log.debug(`📦 PCM16 audio chunk for ${connectionId}: ${audioData.length} bytes (${sampleCount} samples)`);
  
  const session = transcriptionSessions.get(connectionId);
  
  if (!session) {
    // No active session, start one (server will generate message ID)
    fastify.log.info(`🆕 No active session for ${connectionId}, starting new session (chunk size: ${audioData.length} bytes)`);
    
    // Start session first (server generates message ID)
    await startTranscriptionSession(connectionId, fastify, sendToClient);
    
    // Add this chunk to the new session
    const newSession = transcriptionSessions.get(connectionId);
    if (newSession) {
      newSession.audioChunks.push(audioData);
      newSession.chunksReceived = 1;
      newSession.chunksProcessed = 0;
      newSession.lastChunkTime = Date.now();
      newSession.hasReceivedSpeech = true;
      
      // Start pause detection timer
      schedulePauseCheck(connectionId, fastify, sendToClient);
      fastify.log.info(`✅ Added initial chunk to session ${connectionId}: ${audioData.length} bytes (queued: ${newSession.audioChunks.length})`);
    } else {
      fastify.log.error(`❌ Failed to create session for ${connectionId} - session not found after creation`);
    }
  } else if (session.isActive) {
    // Append chunk to existing session
    session.audioChunks.push(audioData);
    session.chunksReceived++;
    session.lastChunkTime = Date.now();
    session.hasReceivedSpeech = true;
    
    // Clear existing timer and schedule new check
    if (session.pauseDetectionTimer) {
      clearTimeout(session.pauseDetectionTimer);
    }
    schedulePauseCheck(connectionId, fastify, sendToClient);
    
    const queueLength = session.audioChunks.length;
    if (queueLength > 10) {
      fastify.log.warn(`⚠️ Audio chunk queue is backing up for ${connectionId}: ${queueLength} chunks queued (received: ${session.chunksReceived}, processed: ${session.chunksProcessed})`);
    } else {
      // Log every 50th chunk to avoid spam, but always log first few
      if (session.chunksReceived <= 5 || session.chunksReceived % 50 === 0) {
        fastify.log.info(`📦 Added chunk #${session.chunksReceived} to session ${connectionId}: ${audioData.length} bytes (queued: ${queueLength}, processed: ${session.chunksProcessed})`);
      }
    }
  } else {
    fastify.log.warn(`⚠️ Received audio chunk for inactive session ${connectionId} (${audioData.length} bytes) - dropping chunk`);
  }
}

/**
 * Schedule a pause check after the threshold time
 */
function schedulePauseCheck(
  connectionId: string,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction
) {
  const session = transcriptionSessions.get(connectionId);
  if (!session || !session.isActive) {
    return;
  }

  session.pauseDetectionTimer = setTimeout(() => {
    checkForPause(connectionId, fastify, sendToClient).catch((error) => {
      fastify.log.error(`Error checking for pause: ${error}`);
    });
  }, PAUSE_THRESHOLD_MS);
}

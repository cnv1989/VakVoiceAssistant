/**
 * Message Handlers Module
 * 
 * This module handles all message processing for the Vak voice assistant server:
 * - Text message processing: Receives text, sends to Bedrock LLM, synthesizes TTS with Polly
 * - Audio stream processing: Receives PCM16 audio, transcribes with AWS Transcribe, processes responses
 * - TTS settings management: Per-connection voice engine and voice selection
 * - Session management: Tracks active transcription sessions with pause detection
 * 
 * Flow:
 * 1. Text Messages: Client text → Bedrock LLM → Stream tokens → Polly TTS → Send audio chunks
 * 2. Audio Messages: Client audio → AWS Transcribe → Final transcript → Bedrock LLM → Stream tokens → Polly TTS → Send audio chunks
 * 
 * Key Features:
 * - Real-time partial transcript updates
 * - Pause detection (1.5s silence) before processing final transcript
 * - Message ID tracking for pairing user input with AI responses
 * - Per-connection TTS engine selection (standard/neural/generative)
 */

import { FastifyInstance } from 'fastify';
import { BedrockRuntimeClient, InvokeModelWithResponseStreamCommand } from '@aws-sdk/client-bedrock-runtime';
import { TranscribeStreamingClient, StartStreamTranscriptionCommand, AudioStream } from '@aws-sdk/client-transcribe-streaming';
import { PollyClient, SynthesizeSpeechCommand } from '@aws-sdk/client-polly';
import { ApiGatewayManagementApiClient, PostToConnectionCommand } from '@aws-sdk/client-apigatewaymanagementapi';
import { Readable } from 'stream';

// ============================================================================
// CONFIGURATION - Environment Variables and Defaults
// ============================================================================

const region = process.env.REGION || 'us-west-2';
const wsApiEndpoint = process.env.WS_API_ENDPOINT || '';
const modelId = process.env.MODEL_ID || 'anthropic.claude-3-haiku-20240307-v1:0';

// Polly TTS Configuration
// Use generative voice by default (Ruth is a generative voice)
// Other generative voices include: Stephen, Gregory, Danielle, Burcu, Jitka, Sabrina, Jasmine, Jihye
const pollyVoice = process.env.POLLY_VOICE || 'Ruth';
const pollyEngine = process.env.POLLY_ENGINE || 'generative'; // 'standard', 'neural', or 'generative'
const pollyStandardVoice = process.env.POLLY_STANDARD_VOICE || 'Joanna';
const pollyNeuralVoice = process.env.POLLY_NEURAL_VOICE || 'Joanna';

// ============================================================================
// TTS SETTINGS MANAGEMENT - Per-Connection Voice Engine Selection
// ============================================================================

/**
 * Supported Polly TTS engine types
 * - standard: Traditional TTS voices (lower quality, lower cost)
 * - neural: Neural TTS voices (better quality, moderate cost)
 * - generative: Generative AI voices (best quality, highest cost)
 */
type PollyEngineType = 'standard' | 'neural' | 'generative';

/**
 * TTS settings for a connection
 * Stores the engine type and voice ID to use for text-to-speech synthesis
 */
interface TtsSettings {
  engine: PollyEngineType;
  voice: string;
}

// Per-connection TTS settings storage
// Maps connectionId -> TtsSettings
const connectionTtsSettings = new Map<string, TtsSettings>();

// Default TTS settings used when no per-connection settings exist
const DEFAULT_TTS_SETTINGS = resolveTtsSettings(pollyEngine);

/**
 * Normalize and validate Polly engine input from client
 * Accepts various formats: 'polly-standard', 'standard', 'neural', 'generative', etc.
 * 
 * @param engine - Engine string from client (case-insensitive)
 * @returns Normalized engine type or null if invalid
 */
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

/**
 * Convert engine type to TTS settings with appropriate voice
 * Each engine type has a default voice configured
 * 
 * @param engine - Normalized engine type
 * @returns TTS settings with engine and voice
 */
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

/**
 * Resolve TTS settings from optional engine string
 * If engine is invalid or null, defaults to generative
 * 
 * @param engine - Optional engine string
 * @returns Valid TTS settings
 */
function resolveTtsSettings(engine?: string | null): TtsSettings {
  const normalized = normalizePollyEngineInput(engine);
  if (normalized) {
    return toTtsSettings(normalized);
  }
  return toTtsSettings('generative');
}

/**
 * Set TTS engine preference for a specific connection
 * Allows clients to choose between standard, neural, or generative voices
 * 
 * @param connectionId - WebSocket connection ID
 * @param engine - Engine type string from client
 * @param fastify - Fastify instance for logging
 * @returns TTS settings if valid, null if invalid engine
 */
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

/**
 * Get TTS settings for a connection
 * Returns per-connection settings if set, otherwise default settings
 * 
 * @param connectionId - WebSocket connection ID
 * @returns TTS settings for the connection
 */
export function getConnectionTtsSettings(connectionId: string): TtsSettings {
  return connectionTtsSettings.get(connectionId) ?? DEFAULT_TTS_SETTINGS;
}

/**
 * Clear TTS settings for a connection
 * Removes per-connection settings, connection will use defaults
 * 
 * @param connectionId - WebSocket connection ID
 * @param fastify - Optional Fastify instance for logging
 */
export function clearConnectionTtsSettings(connectionId: string, fastify?: FastifyInstance) {
  if (connectionTtsSettings.delete(connectionId) && fastify) {
    fastify.log.info(`🧹 Cleared TTS settings for ${connectionId}`);
  }
}

// ============================================================================
// AWS CLIENT INITIALIZATION
// ============================================================================

// Initialize AWS SDK clients for Bedrock (LLM), Transcribe (speech-to-text), and Polly (TTS)
const bedrockClient = new BedrockRuntimeClient({ region });
const transcribeClient = new TranscribeStreamingClient({ region });
const pollyClient = new PollyClient({ region });

// ============================================================================
// TRANSCRIPTION SESSION MANAGEMENT
// ============================================================================

/**
 * Transcription session state for a connection
 * Tracks audio chunks, transcription status, pause detection, and message IDs
 */
interface TranscriptionSession {
  audioChunks: Buffer[]; // Queue of PCM16 audio chunks waiting to be sent to AWS Transcribe
  isActive: boolean; // Whether session is actively receiving audio
  transcriptionPromise: Promise<void> | null; // Promise for the async transcription process
  abortController: AbortController; // Used to cancel transcription if needed
  lastChunkTime: number; // Timestamp of last received audio chunk (for pause detection)
  pauseDetectionTimer: NodeJS.Timeout | null; // Timer that triggers pause check after silence
  hasReceivedSpeech: boolean; // Track if we've received any audio chunks (distinguishes silence from no audio)
  chunksReceived: number; // Total audio chunks received from client
  chunksProcessed: number; // Total chunks sent to AWS Transcribe
  lastPartialTranscript?: string; // Last partial transcript text (to avoid duplicate logging)
  messageId?: string; // Unique message ID for current utterance (generated on first partial transcript)
  hasGeneratedMessageId: boolean; // Flag to ensure message ID is only generated once per utterance
}

// Active transcription sessions mapped by connection ID
const transcriptionSessions = new Map<string, TranscriptionSession>();

// Pause detection configuration
// After 1.5 seconds of silence, we assume the user has finished speaking
const PAUSE_THRESHOLD_MS = 1500; // 1.5 seconds of silence triggers pause

// ============================================================================
// API GATEWAY CLIENT (Legacy - Not used with ALB)
// ============================================================================

// Initialize API Gateway client only if endpoint is provided (AWS mode)
// Note: This is legacy code - with ALB, WebSocket connections are handled directly
// and this client is not used. Kept for backward compatibility.
let apiGatewayClient: ApiGatewayManagementApiClient | null = null;
if (wsApiEndpoint) {
  apiGatewayClient = new ApiGatewayManagementApiClient({
    region,
    endpoint: wsApiEndpoint,
  });
}

/**
 * Function type for sending messages to WebSocket clients
 * Used to abstract the sending mechanism (local WebSocket vs API Gateway)
 */
export type SendToClientFunction = (connectionId: string, data: any) => Promise<void> | void;

/**
 * Default send function for API Gateway mode (legacy)
 * Sends messages to clients connected via API Gateway WebSocket API
 * 
 * @param connectionId - API Gateway connection ID
 * @param data - Message data to send
 */
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

// ============================================================================
// TEXT MESSAGE HANDLING
// ============================================================================

/**
 * Handle text message from client
 * 
 * Flow:
 * 1. Send text to AWS Bedrock LLM (Claude) for response generation
 * 2. Stream LLM tokens to client in real-time
 * 3. Collect full response
 * 4. Synthesize speech with Amazon Polly TTS
 * 5. Send PCM16 audio chunks to client for playback
 * 
 * @param connectionId - WebSocket connection ID
 * @param text - User's text message
 * @param fastify - Fastify instance for logging
 * @param sendToClient - Function to send messages to client
 * @param messageId - Optional message ID for pairing with client messages
 */
export async function handleTextMessage(
  connectionId: string,
  text: string,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction = sendToClientApiGateway,
  messageId?: string
) {
  try {
    // Step 1: Send text to Bedrock LLM (Claude) for response generation
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
      
      // Step 2: Stream LLM response tokens to client in real-time
      // This provides immediate feedback as the AI generates its response
      for await (const chunk of response.body) {
        if (chunk.chunk) {
          const chunkData = JSON.parse(new TextDecoder().decode(chunk.chunk.bytes));
          
          if (chunkData.type === 'content_block_delta' && chunkData.delta?.text) {
            const token = chunkData.delta.text;
            fullResponse += token;
            
            // Send each token to client immediately for real-time display
            // Include messageId so client can pair this response with the user's message
            await sendToClient(connectionId, { t: 'llm-token', token, messageId });
          }
        }
      }

      // Step 3: Get TTS settings for this connection (engine type and voice)
      const ttsSettings = getConnectionTtsSettings(connectionId);
      
      // Step 4: Synthesize speech with Amazon Polly
      // Using PCM16 format at 16kHz sample rate for compatibility with Web Audio API
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
        // Step 5: Read complete audio stream from Polly
        const audioChunks: Buffer[] = [];
        const audioStream = pollyResponse.AudioStream as Readable;
        
        for await (const chunk of audioStream) {
          audioChunks.push(Buffer.from(chunk));
        }

        const audioBuffer = Buffer.concat(audioChunks);
        
        // Step 6: Send PCM audio chunks to client in small pieces
        // Chunk size: 3200 bytes = 100ms of audio at 16kHz (16000 samples/sec * 2 bytes/sample * 0.1 sec)
        // This allows for smooth streaming playback on the client
        const chunkSize = 3200;
        for (let i = 0; i < audioBuffer.length; i += chunkSize) {
          const chunk = audioBuffer.slice(i, i + chunkSize);
          await sendToClient(connectionId, {
            t: 'tts',
            audio: chunk.toString('base64'), // Base64 encode for JSON transmission
            messageId, // Include messageId with each TTS chunk for proper message pairing
          });
        }
        
        // Note: After all audio chunks are sent, the client will send 'ready-to-listen'
        // when audio finishes playing, allowing for continuous conversation flow
      }
    }
  } catch (error) {
    fastify.log.error(`Error handling text message: ${error}`);
    await sendToClient(connectionId, { t: 'error', message: 'Failed to process message' });
  }
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Generate a unique message ID for pairing user input with AI responses
 * Format: msg-{timestamp}-{random}
 * Used to track conversation pairs in the client UI
 * 
 * @returns Unique message ID string
 */
function generateMessageId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

// ============================================================================
// PAUSE DETECTION AND RESPONSE PROCESSING
// ============================================================================

/**
 * Process pause detection - stop transcription and wait for it to complete
 * 
 * This function is called when 1.5 seconds of silence is detected.
 * It waits for the transcription to finish processing remaining audio chunks,
 * then processes the final transcript through the LLM and TTS pipeline.
 * 
 * Flow:
 * 1. Mark pause as detected
 * 2. Stop accepting new audio chunks
 * 3. Wait for transcription to complete (up to 10 seconds)
 * 4. Process final transcript through handleTextMessage (LLM + TTS)
 * 
 * @param connectionId - WebSocket connection ID
 * @param fastify - Fastify instance for logging
 * @param sendToClient - Function to send messages to client
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

  // Message ID should already be generated when first partial transcript arrived
  // We use the existing message ID to pair the user's speech with the AI's response
  const messageId = session.messageId;
  if (messageId) {
    fastify.log.info(`⏸️ Pause detected, using existing message ID: ${messageId} (connection: ${connectionId})`);
  } else {
    fastify.log.warn(`⏸️ Pause detected but no message ID exists yet (connection: ${connectionId})`);
  }

  // Clear the pause detection timer since we've already detected the pause
  if (session.pauseDetectionTimer) {
    clearTimeout(session.pauseDetectionTimer);
    session.pauseDetectionTimer = null;
  }

  // Mark session as inactive to stop accepting new audio chunks
  // The transcription process will continue to process remaining queued chunks
  session.isActive = false;
  
  // Wait for transcription to complete processing remaining audio chunks
  // We poll every 100ms and timeout after 10 seconds to avoid infinite waiting
  const timeout = 10000; // 10 seconds max wait time
  const startTime = Date.now();
  
  while (transcriptionSessions.has(connectionId) && (Date.now() - startTime) < timeout) {
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  
  // At this point, transcription should have completed
  // The final transcript will have been processed through handleTextMessage
  // which sends LLM tokens and TTS audio to the client
  // The client will send 'ready-to-listen' when audio finishes playing
  fastify.log.info(`Pause processing completed for ${connectionId} (messageId: ${messageId})`);
}

// ============================================================================
// TRANSCRIPTION SESSION MANAGEMENT
// ============================================================================

/**
 * Start a new transcription session for a connection
 * 
 * Creates a new AWS Transcribe streaming session that will:
 * 1. Accept PCM16 audio chunks via async generator
 * 2. Stream audio to AWS Transcribe in real-time
 * 3. Receive partial and final transcripts
 * 4. Generate message IDs on first partial transcript
 * 5. Process final transcripts through LLM and TTS
 * 
 * The session uses an async generator pattern to yield audio chunks
 * to AWS Transcribe as they arrive, allowing for real-time transcription.
 * 
 * @param connectionId - WebSocket connection ID
 * @param fastify - Fastify instance for logging
 * @param sendToClient - Function to send messages to client
 */
export async function startTranscriptionSession(
  connectionId: string,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction = sendToClientApiGateway
) {
  // Clean up any existing session for this connection
  stopTranscriptionSession(connectionId, fastify);

  // Initialize new session
  // Note: Message ID is NOT generated here - it's generated when the first
  // partial transcript arrives, ensuring we only create IDs for actual speech
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

  /**
   * Async generator function that yields audio chunks to AWS Transcribe
   * 
   * This generator:
   * - Waits for audio chunks to be added to session.audioChunks queue
   * - Yields chunks immediately when available (real-time streaming)
   * - Handles session abortion gracefully
   * - Waits up to 15 seconds for chunks when session is inactive
   * - Stops when session is aborted or inactive for too long
   */
  const audioStream = async function* (): AsyncIterable<AudioStream> {
    let consecutiveEmptyChecks = 0;
    const maxEmptyChecks = 1500; // Allow up to 15 seconds of waiting (1500 * 10ms)
    const waitInterval = 10; // Check every 10ms for new chunks
    
    fastify.log.info(`Audio stream generator started for ${connectionId}`);
    
    // Main loop: continuously check for audio chunks and yield them to AWS Transcribe
    while (true) {
      // Check if session was aborted (e.g., connection closed)
      if (session.abortController.signal.aborted) {
        fastify.log.info(`Audio stream generator aborted for ${connectionId}`);
        break;
      }
      
      if (session.audioChunks.length > 0) {
        // We have chunks! Send all pending chunks immediately for real-time transcription
        const chunks = session.audioChunks.splice(0); // Remove all chunks from queue
        consecutiveEmptyChecks = 0; // Reset empty check counter
        
        session.chunksProcessed += chunks.length;
        fastify.log.info(`📤 Yielding ${chunks.length} chunks to AWS Transcribe for ${connectionId} (total bytes: ${chunks.reduce((sum, c) => sum + c.length, 0)}, received: ${session.chunksReceived}, processed: ${session.chunksProcessed})`);
        
        // Yield each chunk to AWS Transcribe
        for (const chunk of chunks) {
          if (session.abortController.signal.aborted) {
            fastify.log.info(`Audio stream generator aborted during chunk yield for ${connectionId}`);
            return; // Stop immediately if aborted
          }
          
          try {
            // Yield chunk in AWS Transcribe's expected format
            yield {
              AudioEvent: {
                AudioChunk: new Uint8Array(chunk), // Convert Buffer to Uint8Array
              },
            };
          } catch (error) {
            fastify.log.error(`Error yielding audio chunk: ${error}`);
            throw error;
          }
        }
        
        // After yielding chunks, continue immediately to check for more (no delay)
        continue;
      } else {
        // No chunks available - decide whether to wait or exit
        if (!session.isActive) {
          // Session is inactive (pause detected), but we might have more chunks coming
          consecutiveEmptyChecks++;
          if (consecutiveEmptyChecks >= maxEmptyChecks) {
            // Waited 15 seconds with no chunks and session is inactive - time to exit
            fastify.log.info(`Audio stream generator ending: session inactive and no chunks for ${connectionId}`);
            break;
          }
        } else {
          // Session is active but no chunks yet - reset counter to allow more waiting
          consecutiveEmptyChecks = 0;
        }
        
        // Wait a bit before checking again (10ms) to avoid busy-waiting
        await new Promise(resolve => setTimeout(resolve, waitInterval));
      }
    }
    
    fastify.log.info(`Audio stream generator ended for ${connectionId}`);
  };

  // Configure AWS Transcribe streaming command
  // AWS Transcribe Streaming supports PCM encoding with sample rates: 8000, 16000, 24000, 48000 Hz
  // We use PCM16 (16-bit signed integers, little-endian) at 16kHz
  // This matches the client's audio format and is simpler than Opus encoding
  const command = new StartStreamTranscriptionCommand({
    LanguageCode: 'en-US',
    MediaSampleRateHertz: 16000, // 16kHz sample rate
    MediaEncoding: 'pcm', // PCM16 format (16-bit signed integers, little-endian)
    AudioStream: audioStream(), // Pass the async generator that yields audio chunks
  });
  
  fastify.log.info(`🎙️ Starting AWS Transcribe session for ${connectionId} with format: PCM16 @ 16kHz`);

  /**
   * Process transcription asynchronously
   * 
   * This promise:
   * 1. Sends the transcription command to AWS Transcribe
   * 2. Processes transcription events (partial and final transcripts)
   * 3. Generates message IDs on first partial transcript
   * 4. Sends partial transcripts to client in real-time
   * 5. Processes final transcripts through LLM and TTS pipeline
   * 6. Handles errors gracefully
   */
  session.transcriptionPromise = (async () => {
    try {
      fastify.log.info(`🎤 Starting transcription stream for ${connectionId} (format: PCM16 @ 16kHz)`);
      const response = await transcribeClient.send(command);
      
      if (response.TranscriptResultStream) {
        let eventCount = 0;
        
        // Process each transcription event from AWS Transcribe
        // Events can be: partial transcripts, final transcripts, or errors
        for await (const event of response.TranscriptResultStream) {
          if (session.abortController.signal.aborted) {
            fastify.log.info(`⏹️ Transcription stream aborted for ${connectionId}`);
            break;
          }

          eventCount++;
          
          // Handle AWS Transcribe errors
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

          // Process transcript results from the event
          if (event.TranscriptEvent?.Transcript?.Results) {
            const results = event.TranscriptEvent.Transcript.Results;
            for (const result of results) {
              if (result.Alternatives && result.Alternatives.length > 0) {
                const transcript = result.Alternatives[0].Transcript;
                if (transcript) {
                  if (result.IsPartial) {
                    // PARTIAL TRANSCRIPT: Real-time transcription update as user speaks
                    // Generate message ID on first partial transcript to identify this utterance
                    // This allows the client to create a message pair entry immediately
                    if (!session.hasGeneratedMessageId) {
                      const newMessageId = generateMessageId();
                      session.messageId = newMessageId;
                      session.hasGeneratedMessageId = true;
                      fastify.log.info(`🆔 Generated new message ID for first partial transcript: ${newMessageId} (connection: ${connectionId})`);
                      
                      // Send message ID to client immediately so it can create a message pair entry
                      // This allows the UI to show the user's message being transcribed
                      await sendToClient(connectionId, { 
                        t: 'message-id', 
                        messageId: newMessageId 
                      });
                    }
                    
                    // Send partial transcript update to client for real-time display
                    // Client can show this as the user is speaking
                    const currentMessageId = session.messageId;
                    fastify.log.info(`💬 Partial transcription for ${connectionId}: "${transcript}" (messageId: ${currentMessageId})`);
                    try {
                      await sendToClient(connectionId, { 
                        t: 'partial-transcript', 
                        text: transcript,
                        isPartial: true,
                        messageId: currentMessageId // Use server-generated messageId for pairing
                      });
                    } catch (sendError) {
                      fastify.log.error(`Error sending partial transcript: ${sendError}`);
                    }
                  } else {
                    // FINAL TRANSCRIPT: User has finished speaking, transcription is complete
                    // This is the complete, final text of what the user said
                    // 
                    // Ensure we have a message ID (should exist from partial transcript)
                    // Handle edge case where final transcript arrives before any partial
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
                    
                    // Clear partial transcript state and reset message ID generation flag
                    // This prepares the session for the next utterance
                    session.lastPartialTranscript = undefined;
                    session.hasGeneratedMessageId = false; // Reset for next utterance
                    
                    // Send final transcript to client
                    // Then process it through the LLM and TTS pipeline (same as text messages)
                    try {
                      await sendToClient(connectionId, { 
                        t: 'transcript', 
                        text: transcript,
                        isPartial: false,
                        messageId: currentMessageId // Use server-generated messageId for pairing
                      });
                      
                      // Process final transcript through the same pipeline as text messages:
                      // 1. Send to Bedrock LLM for response generation
                      // 2. Stream LLM tokens to client
                      // 3. Synthesize TTS with Polly
                      // 4. Send audio chunks to client
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
 * 
 * Gracefully stops a transcription session by:
 * 1. Marking session as inactive (stops accepting new chunks)
 * 2. Clearing pause detection timer
 * 3. Allowing remaining queued chunks to be processed
 * 4. Force aborting after 2 seconds if session doesn't end naturally
 * 
 * @param connectionId - WebSocket connection ID
 * @param fastify - Fastify instance for logging
 */
export function stopTranscriptionSession(
  connectionId: string,
  fastify: FastifyInstance
) {
  const session = transcriptionSessions.get(connectionId);
  if (session) {
    session.isActive = false;
    
    // Clear pause detection timer since we're stopping the session
    if (session.pauseDetectionTimer) {
      clearTimeout(session.pauseDetectionTimer);
      session.pauseDetectionTimer = null;
    }
    
    // Don't abort immediately - let remaining chunks be processed
    // The async generator will stop after processing remaining chunks
    // This ensures we don't lose any audio data
    fastify.log.info(`Stopped transcription session for ${connectionId} (processing remaining chunks)`);
    
    // Safety timeout: Force abort if session doesn't end naturally within 2 seconds
    // This prevents sessions from hanging indefinitely
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

// ============================================================================
// PAUSE DETECTION
// ============================================================================

/**
 * Check for pause in audio stream and process if detected
 * 
 * A pause is detected when:
 * - We've received at least one audio chunk (hasReceivedSpeech = true)
 * - No new chunks have arrived for PAUSE_THRESHOLD_MS (1.5 seconds)
 * 
 * When pause is detected:
 * 1. Send 'processing-audio' message to client
 * 2. Call processPauseAndRespond to handle the final transcript
 * 
 * @param connectionId - WebSocket connection ID
 * @param fastify - Fastify instance for logging
 * @param sendToClient - Function to send messages to client
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

  // Detect pause: user has stopped speaking (silence >= 1.5 seconds)
  // Only trigger if we've actually received speech (not just initial silence)
  if (session.hasReceivedSpeech && timeSinceLastChunk >= PAUSE_THRESHOLD_MS) {
    fastify.log.info(`Server-side pause detected for ${connectionId} (${timeSinceLastChunk}ms silence)`);
    
    // Clear the timer since we've detected the pause
    if (session.pauseDetectionTimer) {
      clearTimeout(session.pauseDetectionTimer);
      session.pauseDetectionTimer = null;
    }

    // Notify client that we're processing the audio
    await sendToClient(connectionId, { t: 'processing-audio' });
    
    // Process the pause: wait for transcription to complete, then respond
    await processPauseAndRespond(connectionId, fastify, sendToClient);
  }
}

// ============================================================================
// AUDIO STREAM HANDLING
// ============================================================================

/**
 * Handle incoming audio stream chunk
 * 
 * This is the main entry point for audio processing. It:
 * 1. Validates the audio chunk (size, format)
 * 2. Creates a new session if none exists
 * 3. Queues chunks for transcription
 * 4. Schedules pause detection
 * 
 * Audio Format: PCM16 (16-bit signed integers, little-endian) at 16kHz
 * 
 * @param connectionId - WebSocket connection ID
 * @param audioData - PCM16 audio chunk buffer
 * @param fastify - Fastify instance for logging
 * @param sendToClient - Function to send messages to client
 */
export async function handleAudioStream(
  connectionId: string,
  audioData: Buffer,
  fastify: FastifyInstance,
  sendToClient: SendToClientFunction = sendToClientApiGateway
) {
  // ===== VALIDATION =====
  
  // Check for empty chunks
  if (!audioData || audioData.length === 0) {
    fastify.log.warn(`⚠️ Received empty audio chunk for ${connectionId}`);
    return;
  }
  
  // Validate chunk size
  // PCM16 at 16kHz: 4096 samples = 8192 bytes (typical chunk size)
  // Very small chunks (< 10 bytes) might be invalid
  // Very large chunks (> 1MB) might indicate corruption
  if (audioData.length < 10) {
    fastify.log.warn(`⚠️ Received suspiciously small audio chunk for ${connectionId}: ${audioData.length} bytes`);
    return;
  }
  if (audioData.length > 1024 * 1024) {
    fastify.log.warn(`⚠️ Received suspiciously large audio chunk for ${connectionId}: ${audioData.length} bytes`);
    return;
  }
  
  // Validate PCM16 format
  // PCM16 uses 2 bytes per sample, so chunk size must be even
  if (audioData.length % 2 !== 0) {
    fastify.log.warn(`⚠️ Received odd-sized PCM16 chunk for ${connectionId}: ${audioData.length} bytes (should be even)`);
    return;
  }
  
  // Log chunk info for debugging
  const sampleCount = audioData.length / 2; // 2 bytes per sample
  fastify.log.debug(`📦 PCM16 audio chunk for ${connectionId}: ${audioData.length} bytes (${sampleCount} samples)`);
  
  // ===== SESSION MANAGEMENT =====
  
  const session = transcriptionSessions.get(connectionId);
  
  if (!session) {
    // No active session - create a new one
    fastify.log.info(`🆕 No active session for ${connectionId}, starting new session (chunk size: ${audioData.length} bytes)`);
    
    // Start new transcription session (this creates the AWS Transcribe connection)
    await startTranscriptionSession(connectionId, fastify, sendToClient);
    
    // Add this chunk to the newly created session
    const newSession = transcriptionSessions.get(connectionId);
    if (newSession) {
      newSession.audioChunks.push(audioData);
      newSession.chunksReceived = 1;
      newSession.chunksProcessed = 0;
      newSession.lastChunkTime = Date.now();
      newSession.hasReceivedSpeech = true;
      
      // Start pause detection timer
      // After 1.5 seconds of silence, we'll process the transcription
      schedulePauseCheck(connectionId, fastify, sendToClient);
      fastify.log.info(`✅ Added initial chunk to session ${connectionId}: ${audioData.length} bytes (queued: ${newSession.audioChunks.length})`);
    } else {
      fastify.log.error(`❌ Failed to create session for ${connectionId} - session not found after creation`);
    }
  } else if (session.isActive) {
    // Active session exists - append chunk to queue
    session.audioChunks.push(audioData);
    session.chunksReceived++;
    session.lastChunkTime = Date.now(); // Update timestamp for pause detection
    session.hasReceivedSpeech = true;
    
    // Reset pause detection timer
    // Each new chunk resets the 1.5 second silence timer
    if (session.pauseDetectionTimer) {
      clearTimeout(session.pauseDetectionTimer);
    }
    schedulePauseCheck(connectionId, fastify, sendToClient);
    
    // Monitor queue health
    const queueLength = session.audioChunks.length;
    if (queueLength > 10) {
      // Queue is backing up - chunks arriving faster than we can process
      fastify.log.warn(`⚠️ Audio chunk queue is backing up for ${connectionId}: ${queueLength} chunks queued (received: ${session.chunksReceived}, processed: ${session.chunksProcessed})`);
    } else {
      // Log periodically to avoid spam (every 50th chunk, or first 5 chunks)
      if (session.chunksReceived <= 5 || session.chunksReceived % 50 === 0) {
        fastify.log.info(`📦 Added chunk #${session.chunksReceived} to session ${connectionId}: ${audioData.length} bytes (queued: ${queueLength}, processed: ${session.chunksProcessed})`);
      }
    }
  } else {
    // Session exists but is inactive (pause was detected, waiting for transcription to complete)
    // Drop the chunk - we're already processing the previous utterance
    fastify.log.warn(`⚠️ Received audio chunk for inactive session ${connectionId} (${audioData.length} bytes) - dropping chunk`);
  }
}

/**
 * Schedule a pause check after the threshold time
 * 
 * Sets a timer that will check for pause (silence) after PAUSE_THRESHOLD_MS.
 * Each new audio chunk resets this timer, so pause is only detected after
 * continuous silence for 1.5 seconds.
 * 
 * @param connectionId - WebSocket connection ID
 * @param fastify - Fastify instance for logging
 * @param sendToClient - Function to send messages to client
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

  // Set timer to check for pause after 1.5 seconds of silence
  // If a new chunk arrives before this fires, the timer will be cleared and reset
  session.pauseDetectionTimer = setTimeout(() => {
    checkForPause(connectionId, fastify, sendToClient).catch((error) => {
      fastify.log.error(`Error checking for pause: ${error}`);
    });
  }, PAUSE_THRESHOLD_MS);
}

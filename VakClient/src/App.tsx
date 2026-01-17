import { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

interface Message {
  t: 'llm-token' | 'llm-response' | 'tts' | 'transcript' | 'partial-transcript' | 'error' | 'recording-started' | 'recording-stopped' | 'processing-audio' | 'ready-to-listen' | 'message-id' | 'welcome' | 'settings-applied' | 'deepgram-ready' | 'deepgram-disconnected' | 'user-started-speaking' | 'agent-started-speaking';
  token?: string;
  audio?: string;
  text?: string;
  message?: string;
  isPartial?: boolean;
  messageId?: string; // Server-generated message ID for pairing client messages with AI replies
  connectionId?: string;
}

interface MessagePair {
  id: string;
  clientMessage: string;
  aiReply: string;
  status: 'listening' | 'transcribing' | 'processing' | 'speaking' | 'complete';
}

interface SystemMessageEntry {
  id: string;
  text: string;
  timestamp: string;
}

const STATUS_META: Record<MessagePair['status'], { icon: string; label: string; variant: string }> = {
  listening: { icon: '🎤', label: 'Listening...', variant: 'listening' },
  transcribing: { icon: '📝', label: 'Transcribing...', variant: 'transcribing' },
  processing: { icon: '🤔', label: 'Processing...', variant: 'processing' },
  speaking: { icon: '🔊', label: 'Speaking...', variant: 'speaking' },
  complete: { icon: '✅', label: 'Complete', variant: 'complete' },
};

type EndpointType = 'local' | 'alb';

function App() {
  // Default to Deepgram server WebSocket for local development
  // For ALB, use: wss://vak.tutzi.ai/ws
  const defaultWsUrl = import.meta.env.VITE_WS_URL || `ws://localhost:8080/ws`;
  const [wsUrl, setWsUrl] = useState<string>(defaultWsUrl);
  const [endpointType, setEndpointType] = useState<EndpointType>(
    defaultWsUrl.includes('localhost') ? 'local' : 'alb'
  );
  const [connected, setConnected] = useState(false);
  const [systemMessages, setSystemMessages] = useState<SystemMessageEntry[]>([]);
  const [textInput, setTextInput] = useState('');
  const [businessNumber, setBusinessNumber] = useState('+15104054454');
  const [isRecording, setIsRecording] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>('Disconnected');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isAgentSpeaking, setIsAgentSpeaking] = useState(false);
  const [currentTranscript, setCurrentTranscript] = useState<string>('');
  const [audioLevel, setAudioLevel] = useState<number>(0); // 0-100 for visualization
  const [recordedAudioUrl, setRecordedAudioUrl] = useState<string | null>(null); // URL for recorded audio playback
  const [isPlayingRecording, setIsPlayingRecording] = useState<boolean>(false);
  const [messagePairs, setMessagePairs] = useState<MessagePair[]>([]); // Track message pairs (client + AI)

  const wsRef = useRef<WebSocket | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const isRecordingRef = useRef<boolean>(false);
  const audioQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingAudioRef = useRef<boolean>(false);
  const nextScheduledTimeRef = useRef<number>(0);
  const ttsQueueRef = useRef<Array<{ messageId: string; audioChunks: ArrayBuffer[] }>>([]); // Queue TTS audio by message ID
  const currentPlayingMessageIdRef = useRef<string | null>(null); // Track which message is currently playing
  const messageIdRef = useRef<string | null>(null); // Current message ID being recorded
  const audioChunkQueueRef = useRef<ArrayBuffer[]>([]); // Queue for PCM audio chunks waiting to be sent
  const isSendingChunksRef = useRef<boolean>(false);
  const lastChunkSentTimeRef = useRef<number>(0);
  const chunkSendIntervalRef = useRef<number | null>(null);
  const recordedChunksRef = useRef<ArrayBuffer[]>([]); // Store all recorded PCM chunks for local playback
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null); // Audio element for playback
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null); // For PCM audio capture
  const recordingSourceRef = useRef<MediaStreamAudioSourceNode | null>(null); // Audio source for recording
  const activeAudioSourcesRef = useRef<AudioBufferSourceNode[]>([]); // Track active TTS sources for barge-in
  const ttsPlaybackSessionRef = useRef<number>(0); // Invalidate in-flight playback on barge-in

  const addSystemMessage = useCallback((content: string) => {
    const now = new Date();
    const entry: SystemMessageEntry = {
      id: `${now.getTime()}-${Math.random().toString(36).slice(2, 8)}`,
      text: content,
      timestamp: now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    };
    setSystemMessages(prev => [...prev, entry]);
  }, []);

  useEffect(() => {
    // Initialize audio context on user interaction (required for autoplay policies)
    const initAudioContext = async () => {
      if (!audioContextRef.current) {
        // Use 48kHz sample rate for Deepgram Voice Agents input
        audioContextRef.current = new AudioContext({ sampleRate: 48000 });
        console.log('🔊 [INIT] Created AudioContext, state:', audioContextRef.current.state);
        // Resume if suspended (browser autoplay policy)
        if (audioContextRef.current.state === 'suspended') {
          await audioContextRef.current.resume();
          console.log('🔊 [INIT] Resumed AudioContext, state:', audioContextRef.current.state);
        }
      }
    };

    // Try to initialize on any user interaction
    const handleUserInteraction = () => {
      initAudioContext().catch(err => console.error('Error initializing audio context:', err));
      document.removeEventListener('click', handleUserInteraction);
      document.removeEventListener('touchstart', handleUserInteraction);
    };

    document.addEventListener('click', handleUserInteraction);
    document.addEventListener('touchstart', handleUserInteraction);

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
      isRecordingRef.current = false;
      stopAudioLevelMonitoring();
      stopStreamingMonitor();
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
      document.removeEventListener('click', handleUserInteraction);
      document.removeEventListener('touchstart', handleUserInteraction);
    };
  }, []);


    const buildWebSocketUrl = useCallback((baseUrl: string) => {
      try {
        const scheme = baseUrl.startsWith('wss:') ? 'wss:' : 'ws:';
        const url = new URL(baseUrl.replace(/^wss:/, 'https:').replace(/^ws:/, 'http:'));
        if (businessNumber.trim()) {
          url.searchParams.set('businessNumber', businessNumber.trim());
          console.log('📞 Using businessNumber:', businessNumber.trim());
        }
        url.protocol = scheme;
        return url.toString();
    } catch (error) {
      console.error('Invalid WebSocket URL:', error);
      return baseUrl;
    }
  }, [businessNumber]);

  const connectWebSocket = async () => {
    if (!wsUrl) {
      alert('Please enter WebSocket URL');
      return;
    }

    try {
      addSystemMessage('🟡 Connecting to assistant...');
      
      // Connect directly to ALB WebSocket endpoint
      // Note: For IAM authentication, the server will validate signatures
      // Browser WebSocket API doesn't support custom headers, so IAM auth
      // would need to be handled via query parameters or a proxy
      const ws = new WebSocket(buildWebSocketUrl(wsUrl));
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setConnectionStatus('Connected');
        console.log('WebSocket connected successfully');
        addSystemMessage('✅ Connected to assistant');
        // Send initial message to start recording
        try {
          ws.send(JSON.stringify({ action: 'start-recording' }));
        } catch (error) {
          console.error('Error sending start-recording:', error);
        }
      };

      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          // Handle binary data if needed
          return;
        }

        try {
          const data: any = JSON.parse(event.data);
          // Server sends {type: "...", ...} but client expects {t: "...", ...}
          // Normalize the message format
          const normalizedData: Message = {
            ...data,
            t: data.type || data.t || 'error',
          };
          
          // Use messageId from data, don't fallback to current recording ID
          // This ensures each message pair is updated independently
          const messageId = normalizedData.messageId;
          
          // Handle message-id type separately (TypeScript type narrowing)
          if (normalizedData.t === 'message-id') {
            // Server sent a new message ID - create or update message pair
            if (data.messageId) {
              const newMessageId = data.messageId;
              const previousMessageId = messageIdRef.current;
              messageIdRef.current = newMessageId;
              
              console.log(`📨 [MESSAGE-ID] ==========================================`);
              console.log(`📨 [MESSAGE-ID] Received new message ID from server: ${newMessageId}`);
              console.log(`📨 [MESSAGE-ID] Previous message ID was: ${previousMessageId || 'null'}`);
              
              // Always create a new message pair entry when server sends a new message-id
              // This ensures each conversation turn gets its own pair
              setMessagePairs(prev => {
                console.log(`📨 [MESSAGE-ID] Current message pairs count: ${prev.length}`);
                console.log(`📨 [MESSAGE-ID] Existing message IDs:`, prev.map(p => p.id));
                
                const pairExists = prev.some(pair => pair.id === newMessageId);
                console.log(`📨 [MESSAGE-ID] Pair with ID ${newMessageId} exists: ${pairExists}`);
                
                if (pairExists) {
                  console.warn(`⚠️ [MESSAGE-ID] WARNING: Message ID ${newMessageId} already exists! This should not happen. Server should generate unique IDs.`);
                  // Still create a new pair with a suffix to avoid overwriting
                  const uniqueId = `${newMessageId}-${Date.now()}`;
                  console.log(`📨 [MESSAGE-ID] Creating pair with unique ID: ${uniqueId}`);
                  const newPairs: MessagePair[] = [...prev, {
                    id: uniqueId,
                    clientMessage: '',
                    aiReply: '',
                    status: 'listening' as const
                  }];
                  console.log(`📨 [MESSAGE-ID] New message pairs count: ${newPairs.length}`);
                  console.log(`📨 [MESSAGE-ID] New message pair IDs:`, newPairs.map(p => p.id));
                  console.log(`📨 [MESSAGE-ID] ==========================================`);
                  return newPairs;
                }
                
                console.log(`📨 [MESSAGE-ID] Creating new message pair with ID: ${newMessageId}`);
                const newPairs: MessagePair[] = [...prev, {
                  id: newMessageId,
                  clientMessage: '',
                  aiReply: '',
                  status: 'listening' as const
                }];
                console.log(`📨 [MESSAGE-ID] New message pairs count: ${newPairs.length}`);
                console.log(`📨 [MESSAGE-ID] New message pair IDs:`, newPairs.map(p => p.id));
                console.log(`📨 [MESSAGE-ID] ==========================================`);
                return newPairs;
              });
            } else {
              console.warn('⚠️ Received message-id message without messageId');
            }
            return; // Early return for message-id type
          }

          if (normalizedData.t === 'llm-token' && normalizedData.token) {
            // Update AI reply for this message ID
            if (messageId) {
              console.log(`💬 [LLM-TOKEN] Received token for messageId: ${messageId}`);
              
              setMessagePairs(prev => {
                console.log(`💬 [LLM-TOKEN] Current message pairs:`, prev.map(p => ({ id: p.id, hasReply: !!p.aiReply, clientMsg: p.clientMessage.substring(0, 20) })));
                
                const pairExists = prev.some(pair => pair.id === messageId);
                console.log(`💬 [LLM-TOKEN] Pair with ID ${messageId} exists: ${pairExists}`);
                
                if (!pairExists) {
                  // Create new pair if it doesn't exist (shouldn't happen, but handle gracefully)
                  console.warn(`⚠️ [LLM-TOKEN] Received llm-token for unknown messageId: ${messageId}, creating new pair`);
                  return [...prev, {
                    id: messageId,
                    clientMessage: '',
                    aiReply: normalizedData.token || '',
                    status: 'processing'
                  }];
                }
                return prev.map(pair => {
                  if (pair.id === messageId) {
                    console.log(`💬 [LLM-TOKEN] Updating pair ${messageId}, current reply length: ${pair.aiReply.length}, adding token`);
                    return { ...pair, aiReply: pair.aiReply + normalizedData.token, status: 'processing' };
                  }
                  return pair;
                });
              });
            } else {
              console.warn('⚠️ Received llm-token without messageId');
            }
          } else if (normalizedData.t === 'tts' && normalizedData.audio) {
            // Queue TTS audio by message ID - must have messageId
            console.log(`🔊 [WS] Received TTS audio, messageId: ${messageId}, audio length: ${normalizedData.audio?.length || 0}`);
            if (messageId) {
              await queueTTSAudio(messageId, normalizedData.audio);
            } else {
              console.warn('⚠️ Received TTS audio without messageId, cannot queue properly');
              // Fallback: play immediately if no message ID (shouldn't happen)
              await playAudioChunk(normalizedData.audio);
            }
          } else if (normalizedData.t === 'partial-transcript' && normalizedData.text) {
            // Update live transcription display
            setCurrentTranscript(normalizedData.text);
            // Use server-generated messageId (required - no fallback)
            if (normalizedData.messageId) {
              console.log(`📝 [PARTIAL-TRANSCRIPT] Received for messageId: ${normalizedData.messageId}, text: "${normalizedData.text}"`);
              
              setMessagePairs(prev => {
                console.log(`📝 [PARTIAL-TRANSCRIPT] Current message pairs:`, prev.map(p => ({ id: p.id, clientMsg: p.clientMessage.substring(0, 20) })));
                
                const pairExists = prev.some(pair => pair.id === normalizedData.messageId);
                console.log(`📝 [PARTIAL-TRANSCRIPT] Pair with ID ${normalizedData.messageId} exists: ${pairExists}`);
                
                if (!pairExists) {
                  // Create new pair if it doesn't exist (shouldn't happen, but handle gracefully)
                  console.warn(`⚠️ [PARTIAL-TRANSCRIPT] Received partial-transcript for unknown messageId: ${normalizedData.messageId}, creating new pair`);
                  return [...prev, {
                    id: normalizedData.messageId!,
                    clientMessage: normalizedData.text || '',
                    aiReply: '',
                    status: 'transcribing'
                  }];
                }
                return prev.map(pair => {
                  if (pair.id === normalizedData.messageId) {
                    console.log(`📝 [PARTIAL-TRANSCRIPT] Updating pair ${normalizedData.messageId} with text: "${normalizedData.text}"`);
                    return { ...pair, clientMessage: normalizedData.text || '', status: 'transcribing' };
                  }
                  return pair;
                });
              });
            } else {
              console.warn('⚠️ Received partial-transcript without messageId from server');
            }
          } else if (normalizedData.t === 'transcript' && normalizedData.text) {
            // Final transcript received - use server-generated messageId for pairing
            const transcriptText = normalizedData.text;
            setCurrentTranscript(''); // Clear partial transcript
            addSystemMessage(`📝 Transcript: ${transcriptText}`);
            
            // Use server-generated messageId (required - no fallback)
            if (normalizedData.messageId) {
              console.log(`✅ [TRANSCRIPT] Received final transcript for messageId: ${normalizedData.messageId}, text: "${transcriptText}"`);
              
              setMessagePairs(prev => {
                console.log(`✅ [TRANSCRIPT] Current message pairs:`, prev.map(p => ({ id: p.id, clientMsg: p.clientMessage.substring(0, 30) })));
                
                const pairExists = prev.some(pair => pair.id === normalizedData.messageId);
                console.log(`✅ [TRANSCRIPT] Pair with ID ${normalizedData.messageId} exists: ${pairExists}`);
                
                if (!pairExists) {
                  // Create new pair if it doesn't exist (shouldn't happen, but handle gracefully)
                  console.warn(`⚠️ [TRANSCRIPT] Received transcript for unknown messageId: ${normalizedData.messageId}, creating new pair`);
                  return [...prev, {
                    id: normalizedData.messageId!,
                    clientMessage: transcriptText,
                    aiReply: '',
                    status: 'processing'
                  }];
                }
                return prev.map(pair => {
                  if (pair.id === normalizedData.messageId) {
                    console.log(`✅ [TRANSCRIPT] Updating pair ${normalizedData.messageId} with final text: "${transcriptText}"`);
                    return { ...pair, clientMessage: transcriptText, status: 'processing' };
                  }
                  return pair;
                });
              });
            } else {
              console.warn('⚠️ Received transcript without messageId from server');
            }
          } else if (normalizedData.t === 'error') {
            addSystemMessage(`⚠️ Error: ${normalizedData.message ?? 'Unknown error'}`);
            // Update message pair status on error
            if (messageId) {
              setMessagePairs(prev => prev.map(pair => 
                pair.id === messageId 
                  ? { ...pair, status: 'complete' }
                  : pair
              ));
            }
          } else if (normalizedData.t === 'recording-started') {
            console.log('Recording session started on server');
          } else if (normalizedData.t === 'recording-stopped') {
            console.log('Recording session stopped on server');
            messageIdRef.current = null;
          } else if (normalizedData.t === 'processing-audio') {
            setIsProcessing(true);
            addSystemMessage('🤖 Processing audio...');
            // Use server-generated messageId if provided, otherwise use current ref
            const processingMessageId = normalizedData.messageId || messageIdRef.current;
            if (processingMessageId) {
              setMessagePairs(prev => prev.map(pair => 
                pair.id === processingMessageId 
                  ? { ...pair, status: 'processing' }
                  : pair
              ));
            }
          } else if (normalizedData.t === 'ready-to-listen') {
            setIsProcessing(false);
            setCurrentTranscript(''); // Clear any partial transcript
            addSystemMessage('👂 Ready to listen');
            // Use server-generated messageId if provided, otherwise use current ref
            const readyMessageId = normalizedData.messageId || messageIdRef.current;
            if (readyMessageId) {
              setMessagePairs(prev => prev.map(pair => 
                pair.id === readyMessageId 
                  ? { ...pair, status: 'complete' }
                  : pair
              ));
            }
            // Don't clear messageIdRef here - server will send new message-id when new session starts
          } else if (normalizedData.t === 'welcome') {
            addSystemMessage(`👋 ${normalizedData.message || 'Welcome to Deepgram Voice Agent'}`);
          } else if (normalizedData.t === 'settings-applied') {
            addSystemMessage('⚙️ Settings applied');
          } else if (normalizedData.t === 'deepgram-ready') {
            addSystemMessage('✅ Deepgram Voice Agent ready');
          } else if (normalizedData.t === 'deepgram-disconnected') {
            addSystemMessage('🔌 Deepgram disconnected');
            setIsProcessing(false);
            setIsAgentSpeaking(false);
          } else if (normalizedData.t === 'user-started-speaking') {
            stopTtsPlayback('barge-in');
            addSystemMessage('👤 User started speaking');
          } else if (normalizedData.t === 'agent-started-speaking') {
            setIsAgentSpeaking(true);
            addSystemMessage('🔊 Agent started speaking');
          } else if (normalizedData.t === 'llm-response') {
            // Handle complete LLM response (already handled by llm-token, but keep for completeness)
            if (normalizedData.messageId && normalizedData.text) {
              setMessagePairs(prev => prev.map(pair => 
                pair.id === normalizedData.messageId 
                  ? { ...pair, aiReply: normalizedData.text || '', status: 'processing' }
                  : pair
              ));
            }
          }
        } catch (error) {
          console.error('Error parsing message:', error);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setConnectionStatus('Error');
        const errorMsg = `⚠️ WebSocket error: ${error.type || 'Connection failed'}`;
        addSystemMessage(errorMsg);
        console.error('WebSocket error details:', {
          type: error.type,
          target: error.target,
          url: wsUrl
        });
      };

      ws.onclose = (event) => {
        setConnected(false);
        setConnectionStatus('Disconnected');
        console.log('WebSocket disconnected', {
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean
        });
        
        // Provide specific error messages for common close codes
        let closeMessage = '🔌 Connection closed';
        if (event.code === 1006) {
          closeMessage = '🔌 Connection closed abnormally (code: 1006) - Server may have rejected the connection or network issue';
        } else if (event.code === 1002) {
          closeMessage = '🔌 Connection closed (code: 1002) - Protocol error';
        } else if (event.code === 1008) {
          closeMessage = `🔌 Connection closed (code: 1008) - Policy violation${event.reason ? `: ${event.reason}` : ''}`;
        } else if (event.code === 1011) {
          closeMessage = `🔌 Connection closed (code: 1011) - Server error${event.reason ? `: ${event.reason}` : ''}`;
        } else if (event.code !== 1000 && event.code !== 1001) {
          closeMessage = `🔌 Connection closed (code: ${event.code}${event.reason ? `, reason: ${event.reason}` : ''})`;
        }
        
        addSystemMessage(closeMessage);
      };
    } catch (error) {
      console.error('Failed to connect:', error);
      alert('Failed to connect to WebSocket');
      addSystemMessage('⚠️ Failed to connect to WebSocket');
    }
  };

  const disconnectWebSocket = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
    setConnectionStatus('Disconnected');
  };

  const getAuthUrl = useCallback(() => {
    if (!wsUrl.startsWith('wss://')) {
      return null;
    }
    try {
      const httpsUrl = wsUrl.replace(/^wss:/, 'https:');
      const url = new URL(httpsUrl);
      return `${url.origin}${url.pathname}`;
    } catch (error) {
      console.error('Invalid WebSocket URL for auth:', error);
      return null;
    }
  }, [wsUrl]);

  const startCognitoAuth = () => {
    const authUrl = getAuthUrl();
    if (!authUrl) {
      alert('Cognito auth requires a WSS URL (wss://host/ws).');
      return;
    }
    window.open(authUrl, '_blank', 'noopener');
    addSystemMessage(`🔐 Opened auth URL: ${authUrl}`);
  };


  const sendTextMessage = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      alert('Not connected to WebSocket');
      return;
    }

    if (!textInput.trim()) {
      return;
    }

    wsRef.current.send(JSON.stringify({
      action: 'message',
      text: textInput,
    }));

    setTextInput('');
    addSystemMessage(`🗣️ You: ${textInput}`);
  };


  const startRecording = async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      alert('Not connected to WebSocket');
      return;
    }

    try {
      // Server will generate message ID, just send start-recording signal
      wsRef.current.send(JSON.stringify({ action: 'start-recording' }));

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // Initialize audio context for recording and playback
      // Use 48kHz sample rate for Deepgram Voice Agents input
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext({ sampleRate: 48000 });
        console.log('Created new AudioContext, state:', audioContextRef.current.state, 'sampleRate:', audioContextRef.current.sampleRate);
      }

      // Resume audio context if suspended (required for audio processing)
      if (audioContextRef.current.state === 'suspended') {
        console.log('Resuming suspended AudioContext...');
        await audioContextRef.current.resume();
        console.log('AudioContext resumed, new state:', audioContextRef.current.state);
      }

      // Verify stream has audio tracks
      const audioTracks = stream.getAudioTracks();
      console.log('Audio tracks:', audioTracks.length, audioTracks.map(t => ({ 
        id: t.id, 
        label: t.label, 
        enabled: t.enabled, 
        muted: t.muted,
        readyState: t.readyState 
      })));

      // Create analyser node for audio level visualization
      const analyser = audioContextRef.current.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.3; // Lower smoothing for more responsive visualization
      analyserRef.current = analyser;
      console.log('Created analyser node, fftSize:', analyser.fftSize, 'frequencyBinCount:', analyser.frequencyBinCount);

      // Connect microphone stream to analyser for visualization
      const source = audioContextRef.current.createMediaStreamSource(stream);
      source.connect(analyser);
      console.log('Connected MediaStreamSource to analyser, AudioContext state:', audioContextRef.current.state);

      // Set recording state first (both ref and state)
      isRecordingRef.current = true;
      setIsRecording(true);
      
      // Start audio level monitoring after state is set
      startAudioLevelMonitoring();

      // Use Web Audio API to capture PCM16 audio (simpler than Opus)
      // Create audio source from stream
      const recordingSource = audioContextRef.current.createMediaStreamSource(stream);
      recordingSourceRef.current = recordingSource;
      
      // Create ScriptProcessorNode to capture raw PCM audio
      // Buffer size: 4096 samples (gives us ~85ms chunks at 48kHz)
      const bufferSize = 4096;
      const scriptProcessor = audioContextRef.current.createScriptProcessor(bufferSize, 1, 1);
      scriptProcessorRef.current = scriptProcessor;
      
      // Initialize chunk queue and sending state
      audioChunkQueueRef.current = [];
      isSendingChunksRef.current = false;
      lastChunkSentTimeRef.current = Date.now();
      
      // Initialize recorded chunks array for local storage
      recordedChunksRef.current = [];
      
      // Clear previous recording URL if exists
      if (recordedAudioUrl) {
        URL.revokeObjectURL(recordedAudioUrl);
        setRecordedAudioUrl(null);
      }

      // Process audio data and convert to PCM16 (16-bit signed integers, little-endian)
      scriptProcessor.onaudioprocess = (event) => {
        if (!isRecordingRef.current) {
          return;
        }

        const inputBuffer = event.inputBuffer;
        const inputData = inputBuffer.getChannelData(0); // Mono channel
        const sampleCount = inputData.length;
        
        // Convert Float32 samples (-1.0 to 1.0) to PCM16 (16-bit signed integers)
        const pcm16Buffer = new ArrayBuffer(sampleCount * 2); // 2 bytes per sample
        const pcm16View = new Int16Array(pcm16Buffer);
        
        for (let i = 0; i < sampleCount; i++) {
          // Clamp to [-1, 1] and convert to 16-bit integer
          const sample = Math.max(-1, Math.min(1, inputData[i]));
          pcm16View[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }
        
        // Store chunk for local recording
        recordedChunksRef.current.push(pcm16Buffer);
        
        // Add chunk to queue for reliable sending to server
        audioChunkQueueRef.current.push(pcm16Buffer);
        console.debug(`📦 Queued PCM16 audio chunk: ${pcm16Buffer.byteLength} bytes (${sampleCount} samples, queue size: ${audioChunkQueueRef.current.length})`);
        
        // Start processing queue if not already processing
        if (!isSendingChunksRef.current) {
          processAudioChunkQueue();
        }
      };

      // Connect audio source to script processor
      recordingSource.connect(scriptProcessor);
      scriptProcessor.connect(audioContextRef.current.destination); // Connect to output to avoid errors
      
      console.log('✅ PCM16 audio capture started (48kHz, 16-bit signed integers, will be resampled to 24kHz by server)');
      
      // Start periodic monitoring to ensure continuous streaming
      startStreamingMonitor();
      
      addSystemMessage('🎙️ Listening...');
    } catch (error) {
      console.error('Error starting recording:', error);
      alert('Failed to start recording. Please check microphone permissions.');
      addSystemMessage('⚠️ Failed to start recording. Please check microphone permissions.');
      // Send stop signal on error
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ action: 'stop-recording' }));
      }
    }
  };

  // Monitor audio levels for visualization
  const startAudioLevelMonitoring = () => {
    if (!analyserRef.current) {
      console.warn('Analyser node not available for audio level monitoring');
      return;
    }

    // Stop any existing monitoring first
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }

    const updateLevel = () => {
      if (!analyserRef.current) {
        return;
      }

      // Check if audio context is running
      if (audioContextRef.current && audioContextRef.current.state !== 'running') {
        console.warn('AudioContext not running, state:', audioContextRef.current.state);
        // Try to resume if suspended
        if (audioContextRef.current.state === 'suspended') {
          audioContextRef.current.resume().catch(err => {
            console.error('Failed to resume AudioContext:', err);
          });
        }
      }

      const bufferLength = analyserRef.current.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      analyserRef.current.getByteTimeDomainData(dataArray);

      // Calculate RMS (Root Mean Square) for volume level
      let sum = 0;
      let maxSample = 0;
      let nonZeroSamples = 0;
      for (let i = 0; i < bufferLength; i++) {
        const normalized = (dataArray[i] - 128) / 128;
        const absValue = Math.abs(normalized);
        sum += normalized * normalized;
        maxSample = Math.max(maxSample, absValue);
        if (absValue > 0.01) nonZeroSamples++;
      }
      const rms = Math.sqrt(sum / bufferLength);
      
      // Use both RMS and peak for better visualization
      // Convert to 0-100 scale - using a combination of RMS and peak
      const level = Math.min(100, Math.max(0, (rms * 300) + (maxSample * 200)));
      setAudioLevel(level);

      // Debug logging (only log occasionally to avoid spam)
      if (Math.random() < 0.01) { // Log ~1% of the time
        console.debug('Audio level:', level.toFixed(2), 'RMS:', rms.toFixed(4), 'Peak:', maxSample.toFixed(4), 
                     'Non-zero samples:', nonZeroSamples, '/', bufferLength,
                     'AudioContext state:', audioContextRef.current?.state);
      }

      // Continue monitoring if still recording (use ref for reliable check)
      if (isRecordingRef.current && analyserRef.current) {
        animationFrameRef.current = requestAnimationFrame(updateLevel);
      } else {
        console.log('Stopping audio level monitoring - recording stopped or analyser removed');
      }
    };

    console.log('Starting audio level monitoring');
    animationFrameRef.current = requestAnimationFrame(updateLevel);
  };

  const stopAudioLevelMonitoring = () => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    setAudioLevel(0);
  };

  // Process audio chunk queue to ensure continuous streaming
  const processAudioChunkQueue = async () => {
    if (isSendingChunksRef.current) {
      return; // Already processing
    }

    isSendingChunksRef.current = true;

    while (audioChunkQueueRef.current.length > 0 && isRecordingRef.current) {
      const chunk = audioChunkQueueRef.current.shift();
      if (!chunk) break;

      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(chunk); // Send ArrayBuffer directly
          lastChunkSentTimeRef.current = Date.now();
          console.debug(`📤 Sent PCM16 audio chunk: ${chunk.byteLength} bytes (queue remaining: ${audioChunkQueueRef.current.length})`);
        } catch (error) {
          console.error('Error sending audio chunk:', error);
          // Put chunk back at front of queue to retry
          audioChunkQueueRef.current.unshift(chunk);
          // Wait a bit before retrying
          await new Promise(resolve => setTimeout(resolve, 10));
        }
      } else {
        // WebSocket not ready - put chunk back and wait
        audioChunkQueueRef.current.unshift(chunk);
        const state = wsRef.current?.readyState;
        console.warn(`⚠️ WebSocket not ready (state: ${state}), waiting...`);
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }

    isSendingChunksRef.current = false;

    // If there are still chunks in queue, schedule another processing round
    if (audioChunkQueueRef.current.length > 0 && isRecordingRef.current) {
      setTimeout(() => processAudioChunkQueue(), 5);
    }
  };

  // Monitor streaming to ensure continuous chunk delivery
  const startStreamingMonitor = () => {
    // Clear any existing interval
    if (chunkSendIntervalRef.current) {
      clearInterval(chunkSendIntervalRef.current);
    }

    chunkSendIntervalRef.current = window.setInterval(() => {
      if (!isRecordingRef.current) {
        if (chunkSendIntervalRef.current) {
          clearInterval(chunkSendIntervalRef.current);
          chunkSendIntervalRef.current = null;
        }
        return;
      }

      // Check if script processor is still connected
      if (!scriptProcessorRef.current) {
        console.warn(`⚠️ ScriptProcessorNode is not connected`);
      }

      // Check if chunks are being sent regularly
      const timeSinceLastChunk = Date.now() - lastChunkSentTimeRef.current;
      if (timeSinceLastChunk > 1000 && isRecordingRef.current) {
        console.warn(`⚠️ No chunks sent for ${timeSinceLastChunk}ms - queue size: ${audioChunkQueueRef.current.length}`);
        
        // Check if queue has chunks waiting
        if (audioChunkQueueRef.current.length > 0) {
          console.log('Processing queued chunks...');
          processAudioChunkQueue();
        }
      }

      // Log queue status periodically
      if (audioChunkQueueRef.current.length > 10) {
        console.warn(`⚠️ Audio chunk queue backing up: ${audioChunkQueueRef.current.length} chunks waiting`);
      }
    }, 500); // Check every 500ms
  };

  const stopStreamingMonitor = () => {
    if (chunkSendIntervalRef.current) {
      clearInterval(chunkSendIntervalRef.current);
      chunkSendIntervalRef.current = null;
    }
    // Clear any remaining chunks
    audioChunkQueueRef.current = [];
    isSendingChunksRef.current = false;
  };

  const stopRecording = () => {
    // Stop audio level monitoring
    isRecordingRef.current = false;
    stopAudioLevelMonitoring();
    stopStreamingMonitor();
    
    // Disconnect script processor and recording source
    if (scriptProcessorRef.current) {
      scriptProcessorRef.current.disconnect();
      scriptProcessorRef.current = null;
    }
    if (recordingSourceRef.current) {
      recordingSourceRef.current.disconnect();
      recordingSourceRef.current = null;
    }
    
    // Send stop-recording signal to server
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify({ action: 'stop-recording' }));
      } catch (error) {
        console.error('Error sending stop-recording signal:', error);
      }
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    setIsRecording(false);
    setIsProcessing(false);
    setCurrentTranscript('');
    
    // Combine recorded PCM16 chunks into a single buffer for playback
    // Note: For playback, we'd need to convert PCM16 back to Float32, but for now just store the raw PCM
    if (recordedChunksRef.current.length > 0) {
      const totalLength = recordedChunksRef.current.reduce((sum, chunk) => sum + chunk.byteLength, 0);
      const combinedBuffer = new Uint8Array(totalLength);
      let offset = 0;
      for (const chunk of recordedChunksRef.current) {
        combinedBuffer.set(new Uint8Array(chunk), offset);
        offset += chunk.byteLength;
      }
      
      // Create a WAV file for playback (PCM16 in WAV container)
      // Use 48kHz sample rate to match recording
      const sampleRate = 48000;
      const numChannels = 1;
      const bitsPerSample = 16;
      const wavHeader = createWavHeader(totalLength, sampleRate, numChannels, bitsPerSample);
      const wavFile = new Uint8Array(wavHeader.length + totalLength);
      wavFile.set(wavHeader, 0);
      wavFile.set(combinedBuffer, wavHeader.length);
      
      const blob = new Blob([wavFile], { type: 'audio/wav' });
      const url = URL.createObjectURL(blob);
      setRecordedAudioUrl(url);
      console.log(`✅ Recording saved: ${blob.size} bytes, ${(blob.size / 1024).toFixed(2)} KB`);
    }
    
    // Clear chunks for next recording
    recordedChunksRef.current = [];
    
    addSystemMessage('⏹️ Recording stopped');
  };

  const stopTtsPlayback = (reason: 'barge-in' | 'stop') => {
    ttsPlaybackSessionRef.current += 1;
    if (activeAudioSourcesRef.current.length > 0) {
      activeAudioSourcesRef.current.forEach(source => {
        try {
          source.onended = null;
          source.stop(0);
        } catch (error) {
          console.warn('Error stopping TTS source:', error);
        }
        try {
          source.disconnect();
        } catch (error) {
          console.warn('Error disconnecting TTS source:', error);
        }
      });
      activeAudioSourcesRef.current = [];
    }

    audioQueueRef.current = [];
    ttsQueueRef.current = [];
    nextScheduledTimeRef.current = 0;
    isPlayingAudioRef.current = false;
    setIsAgentSpeaking(false);

    const interruptedMessageId = currentPlayingMessageIdRef.current;
    currentPlayingMessageIdRef.current = null;
    if (interruptedMessageId) {
      setMessagePairs(prev => prev.map(pair => 
        pair.id === interruptedMessageId 
          ? { ...pair, status: 'complete' }
          : pair
      ));
    }

    if (reason === 'barge-in') {
      addSystemMessage('⛔ Barge-in: stopping agent speech');
    }
  };

  // Helper function to create WAV file header
  const createWavHeader = (dataLength: number, sampleRate: number, numChannels: number, bitsPerSample: number): Uint8Array => {
    const header = new ArrayBuffer(44);
    const view = new DataView(header);
    
    // RIFF header
    const writeString = (offset: number, string: string) => {
      for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
      }
    };
    
    writeString(0, 'RIFF');
    view.setUint32(4, 36 + dataLength, true); // File size - 8
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true); // fmt chunk size
    view.setUint16(20, 1, true); // audio format (1 = PCM)
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * bitsPerSample / 8, true); // byte rate
    view.setUint16(32, numChannels * bitsPerSample / 8, true); // block align
    view.setUint16(34, bitsPerSample, true);
    writeString(36, 'data');
    view.setUint32(40, dataLength, true);
    
    return new Uint8Array(header);
  };

  // Queue TTS audio by message ID for sequential playback
  const queueTTSAudio = async (messageId: string, audioBase64: string) => {
    try {
      console.log(`🔊 [TTS] Queueing audio for messageId: ${messageId}, base64 length: ${audioBase64.length}`);
      
      // Decode base64 audio
      const binaryString = atob(audioBase64);
      const audioData = new ArrayBuffer(binaryString.length);
      const view = new Uint8Array(audioData);
      for (let i = 0; i < binaryString.length; i++) {
        view[i] = binaryString.charCodeAt(i);
      }

      console.log(`🔊 [TTS] Decoded audio: ${audioData.byteLength} bytes`);

      // Find or create queue entry for this message ID
      let queueEntry = ttsQueueRef.current.find(entry => entry.messageId === messageId);
      if (!queueEntry) {
        queueEntry = { messageId, audioChunks: [] };
        ttsQueueRef.current.push(queueEntry);
        console.log(`🔊 [TTS] Created new queue entry for messageId: ${messageId}`);
      }
      
      queueEntry.audioChunks.push(audioData);
      console.log(`🔊 [TTS] Added chunk to queue. Total chunks for ${messageId}: ${queueEntry.audioChunks.length}`);
      
      // Update message pair status to speaking
      setMessagePairs(prev => prev.map(pair => 
        pair.id === messageId 
          ? { ...pair, status: 'speaking' }
          : pair
      ));
      
      // Start processing queue if not already playing
      if (!isPlayingAudioRef.current && currentPlayingMessageIdRef.current === null) {
        console.log(`🔊 [TTS] Starting TTS queue processing`);
        processTTSQueue().catch(err => console.error('Error in processTTSQueue:', err));
      } else {
        console.log(`🔊 [TTS] Queue already processing (isPlaying: ${isPlayingAudioRef.current}, currentMessageId: ${currentPlayingMessageIdRef.current})`);
      }
    } catch (error) {
      console.error('Error queueing TTS audio:', error);
    }
  };

  // Process TTS queue - play one message at a time
  const processTTSQueue = async () => {
    // Prevent concurrent processing
    if (isPlayingAudioRef.current || currentPlayingMessageIdRef.current !== null) {
      console.log(`🔊 [TTS-QUEUE] Already processing, skipping (isPlaying: ${isPlayingAudioRef.current}, currentMessageId: ${currentPlayingMessageIdRef.current})`);
      return;
    }

    // Get next message in queue
    if (ttsQueueRef.current.length === 0) {
      console.log(`🔊 [TTS-QUEUE] No messages in queue`);
      return;
    }

    const queueEntry = ttsQueueRef.current[0];
    const messageId = queueEntry.messageId;
    console.log(`🔊 [TTS-QUEUE] Processing messageId: ${messageId}, chunks: ${queueEntry.audioChunks.length}`);
    
    // Move all chunks for this message to audioQueueRef
    audioQueueRef.current.push(...queueEntry.audioChunks);
    ttsQueueRef.current.shift(); // Remove from queue
    currentPlayingMessageIdRef.current = messageId;
    
    console.log(`🔊 [TTS-QUEUE] Moved ${queueEntry.audioChunks.length} chunks to audio queue, total in queue: ${audioQueueRef.current.length}`);
    
    // Process audio queue
    await processAudioQueue();
  };

  const processAudioQueue = async () => {
    // Prevent concurrent processing
    if (isPlayingAudioRef.current) {
      console.log(`🔊 [AUDIO-QUEUE] Already playing, skipping`);
      return;
    }

    if (audioQueueRef.current.length === 0) {
      console.log(`🔊 [AUDIO-QUEUE] No chunks in queue`);
      // No more chunks for current message, move to next message
      currentPlayingMessageIdRef.current = null;
      if (ttsQueueRef.current.length > 0) {
        processTTSQueue().catch(err => console.error('Error in processTTSQueue:', err));
      } else {
        // All messages played, update status
        console.log(`🔊 [AUDIO-QUEUE] All messages played, stopping agent speaking`);
        setIsAgentSpeaking(false);
        if (isRecording && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ t: 'ready-to-listen' }));
        }
      }
      return;
    }

    if (!audioContextRef.current) {
      // TTS audio from Deepgram is 24kHz, but we'll use 48kHz context for compatibility
      audioContextRef.current = new AudioContext({ sampleRate: 48000 });
      console.log(`🔊 [AUDIO-QUEUE] Created new AudioContext, state: ${audioContextRef.current.state}`);
    }

    // Resume audio context if suspended (required for browser autoplay policies)
    if (audioContextRef.current.state === 'suspended') {
      console.log(`🔊 [AUDIO-QUEUE] Resuming suspended AudioContext`);
      try {
        await audioContextRef.current.resume();
        console.log(`🔊 [AUDIO-QUEUE] AudioContext resumed, state: ${audioContextRef.current.state}`);
      } catch (error) {
        console.error(`🔊 [AUDIO-QUEUE] Failed to resume AudioContext:`, error);
        // Try to create a new context if resume fails
        try {
          audioContextRef.current.close();
        } catch (e) {
          // Ignore close errors
        }
        audioContextRef.current = new AudioContext({ sampleRate: 48000 });
        console.log(`🔊 [AUDIO-QUEUE] Created new AudioContext after resume failure, state: ${audioContextRef.current.state}`);
      }
    }
    
    // Ensure context is running before processing
    if (audioContextRef.current.state !== 'running') {
      console.warn(`🔊 [AUDIO-QUEUE] AudioContext state is ${audioContextRef.current.state}, attempting to resume...`);
      try {
        await audioContextRef.current.resume();
        console.log(`🔊 [AUDIO-QUEUE] AudioContext state after resume: ${audioContextRef.current.state}`);
      } catch (error) {
        console.error(`🔊 [AUDIO-QUEUE] Failed to resume AudioContext:`, error);
        return; // Don't process audio if context can't be resumed
      }
    }
    
    console.log(`🔊 [AUDIO-QUEUE] Processing ${audioQueueRef.current.length} audio chunks, AudioContext state: ${audioContextRef.current.state}`);

    isPlayingAudioRef.current = true;
    const playbackSessionId = (ttsPlaybackSessionRef.current += 1);
    setIsAgentSpeaking(true);
    // Deepgram TTS outputs at 24kHz, but AudioContext is 48kHz
    // We'll resample by adjusting the buffer sample rate
    const ttsSampleRate = 24000; // Deepgram TTS output sample rate
    const currentTime = audioContextRef.current.currentTime;

    // If no chunks are scheduled yet, start from current time
    if (nextScheduledTimeRef.current === 0) {
      nextScheduledTimeRef.current = currentTime;
    }

    // Schedule all queued chunks to play back-to-back
    let chunkIndex = 0;
    while (audioQueueRef.current.length > 0) {
      if (ttsPlaybackSessionRef.current !== playbackSessionId) {
        console.log('🔊 [AUDIO-QUEUE] Playback session invalidated, stopping scheduling');
        break;
      }
      const audioData = audioQueueRef.current.shift()!;
      chunkIndex++;
      
      try {
        // Convert ArrayBuffer to Uint8Array
        const uint8Array = new Uint8Array(audioData);
        
        // Validate data length (must be even for 16-bit samples)
        if (uint8Array.length % 2 !== 0) {
          console.warn(`🔊 [AUDIO-QUEUE] Audio data length is not even (${uint8Array.length}), skipping chunk`);
          continue;
        }
        
        // PCM16 is 16-bit signed integers, little-endian
        // Deepgram TTS outputs at 24kHz, so calculate sample count based on that
        const sampleCount = uint8Array.length / 2;
        console.log(`🔊 [AUDIO-QUEUE] Processing chunk ${chunkIndex}: ${uint8Array.length} bytes, ${sampleCount} samples at ${ttsSampleRate}Hz`);
        
        // Create buffer at TTS sample rate (24kHz), AudioContext will handle resampling
        const audioBuffer = audioContextRef.current.createBuffer(
          1,
          sampleCount,
          ttsSampleRate
        );

        // Convert PCM16 (little-endian) to Float32
        const channelData = audioBuffer.getChannelData(0);
        const dataView = new DataView(uint8Array.buffer, uint8Array.byteOffset, uint8Array.byteLength);
        
        for (let i = 0; i < sampleCount; i++) {
          // Read little-endian 16-bit signed integer
          const sample = dataView.getInt16(i * 2, true); // true = little-endian
          // Normalize to [-1, 1]
          channelData[i] = sample / 32768.0;
        }

        // Calculate duration of this chunk
        const duration = audioBuffer.duration;
        console.log(`🔊 [AUDIO-QUEUE] Chunk ${chunkIndex} duration: ${duration.toFixed(3)}s`);
        
        // Schedule this chunk to start when the previous one ends (seamless playback)
        // Ensure startTime is at least slightly in the future to avoid scheduling issues
        const now = audioContextRef.current.currentTime;
        const minStartTime = now + 0.01; // At least 10ms in the future
        const startTime = Math.max(minStartTime, nextScheduledTimeRef.current);
        
        if (startTime < now) {
          console.warn(`🔊 [AUDIO-QUEUE] Start time ${startTime.toFixed(3)}s is in the past (now: ${now.toFixed(3)}s), adjusting to ${minStartTime.toFixed(3)}s`);
        }
        
        const source = audioContextRef.current.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContextRef.current.destination);
        activeAudioSourcesRef.current.push(source);
        
        // Track when audio finishes playing
        const endTime = startTime + duration;
        const isLastChunk = audioQueueRef.current.length === 0;
        
        source.onended = () => {
          console.log(`🔊 [AUDIO-QUEUE] Chunk ${chunkIndex} finished playing (last: ${isLastChunk})`);
          activeAudioSourcesRef.current = activeAudioSourcesRef.current.filter(active => active !== source);
          // Track the messageId for this chunk before it's cleared
          const chunkMessageId = currentPlayingMessageIdRef.current;
          
          // Check if this was the last chunk of current message
          if (isLastChunk && endTime >= nextScheduledTimeRef.current - 0.1) {
            // Current message finished, process next message or finish
            setTimeout(() => {
              // Update message pair status to complete for the message that just finished
              if (chunkMessageId) {
                setMessagePairs(prev => prev.map(pair => 
                  pair.id === chunkMessageId 
                    ? { ...pair, status: 'complete' }
                    : pair
                ));
              }
              currentPlayingMessageIdRef.current = null;
              // Process next message in queue
              processTTSQueue().catch(err => console.error('Error in processTTSQueue:', err));
            }, 100);
          }
        };
        
        // Schedule the chunk to play at the calculated start time
        console.log(`🔊 [AUDIO-QUEUE] Scheduling chunk ${chunkIndex} to start at ${startTime.toFixed(3)}s`);
        source.start(startTime);
        
        // Update next scheduled time for seamless concatenation
        nextScheduledTimeRef.current = startTime + duration;
      } catch (error) {
        console.error(`🔊 [AUDIO-QUEUE] Error playing audio chunk ${chunkIndex}:`, error);
        // Continue with next chunk even if this one failed
      }
    }

    isPlayingAudioRef.current = false;
    
    // If there are more chunks queued while we were processing, schedule them too
    if (audioQueueRef.current.length > 0) {
      // Process remaining chunks with updated timing
      processAudioQueue().catch(console.error);
    } else {
      // Reset scheduled time when queue is empty (allows new audio streams to start fresh)
      // Use a small delay to ensure all scheduled chunks have started
      setTimeout(() => {
        if (audioQueueRef.current.length === 0 && !isPlayingAudioRef.current) {
          nextScheduledTimeRef.current = 0;
          setIsAgentSpeaking(false);
        }
      }, 200);
    }
  };

  // Playback recorded audio
  const playRecordedAudio = () => {
    if (!recordedAudioUrl) {
      alert('No recording available to play');
      return;
    }

    if (!audioPlayerRef.current) {
      const audio = new Audio(recordedAudioUrl);
      audioPlayerRef.current = audio;
      
      audio.onplay = () => {
        setIsPlayingRecording(true);
      };
      
      audio.onended = () => {
        setIsPlayingRecording(false);
      };
      
      audio.onerror = () => {
        setIsPlayingRecording(false);
        alert('Error playing recording');
      };
    }

    if (audioPlayerRef.current.paused) {
      audioPlayerRef.current.play().catch(err => {
        console.error('Error playing audio:', err);
        alert('Failed to play recording');
      });
    } else {
      audioPlayerRef.current.pause();
      audioPlayerRef.current.currentTime = 0;
      setIsPlayingRecording(false);
    }
  };

  // Stop playback
  const stopRecordedAudio = () => {
    if (audioPlayerRef.current) {
      audioPlayerRef.current.pause();
      audioPlayerRef.current.currentTime = 0;
      setIsPlayingRecording(false);
    }
  };

  // Download recorded audio
  const downloadRecordedAudio = () => {
    if (!recordedAudioUrl) {
      alert('No recording available to download');
      return;
    }

    const a = document.createElement('a');
    a.href = recordedAudioUrl;
    a.download = `recording-${new Date().toISOString().replace(/[:.]/g, '-')}.ogg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  // Cleanup audio URL when component unmounts
  useEffect(() => {
    return () => {
      if (recordedAudioUrl) {
        URL.revokeObjectURL(recordedAudioUrl);
      }
      if (audioPlayerRef.current) {
        audioPlayerRef.current.pause();
        audioPlayerRef.current.src = '';
      }
    };
  }, [recordedAudioUrl]);

  const playAudioChunk = async (base64Audio: string) => {
    try {
      // Decode base64 to ArrayBuffer
      const binaryString = atob(base64Audio);
      const audioData = new ArrayBuffer(binaryString.length);
      const view = new Uint8Array(audioData);
      for (let i = 0; i < binaryString.length; i++) {
        view[i] = binaryString.charCodeAt(i);
      }

      // Add to queue
      audioQueueRef.current.push(audioData);

      // Process queue (non-blocking)
      processAudioQueue().catch(console.error);
    } catch (error) {
      console.error('Error queuing audio chunk:', error);
    }
  };

  return (
    <div className="app">
      <div className="container">
        <h1>🗣️ Vak Voice Assistant</h1>

        <div className="connection-section">
          {/* Endpoint Type Selection */}
          <div style={{ 
            marginBottom: '15px',
            display: 'flex',
            gap: '10px',
            flexWrap: 'wrap',
            alignItems: 'center'
          }}>
            <label style={{ fontSize: '14px', fontWeight: '500', color: '#374151' }}>
              Endpoint:
            </label>
            <button
              onClick={() => {
                setEndpointType('local');
                setWsUrl('ws://localhost:8080/ws');
              }}
              disabled={connected}
              style={{
                padding: '8px 16px',
                fontSize: '14px',
                borderRadius: '6px',
                border: '1px solid #d1d5db',
                backgroundColor: endpointType === 'local' ? '#3b82f6' : '#ffffff',
                color: endpointType === 'local' ? '#ffffff' : '#374151',
                cursor: connected ? 'not-allowed' : 'pointer',
                opacity: connected ? 0.6 : 1,
                transition: 'all 0.2s'
              }}
            >
              🏠 Local Deepgram (localhost:8080)
            </button>
            <button
              onClick={() => {
                setEndpointType('alb');
                setWsUrl('wss://vak.tutzi.ai/ws');
              }}
              disabled={connected}
              style={{
                padding: '8px 16px',
                fontSize: '14px',
                borderRadius: '6px',
                border: '1px solid #d1d5db',
                backgroundColor: endpointType === 'alb' ? '#3b82f6' : '#ffffff',
                color: endpointType === 'alb' ? '#ffffff' : '#374151',
                cursor: connected ? 'not-allowed' : 'pointer',
                opacity: connected ? 0.6 : 1,
                transition: 'all 0.2s'
              }}
            >
              ☁️ vak.tutzi.ai
            </button>
          </div>

          {/* Local Endpoint Info */}
          {endpointType === 'local' && (
            <div style={{ 
              marginBottom: '15px',
              fontSize: '12px',
              color: '#6b7280',
              fontFamily: 'monospace',
              padding: '6px',
              backgroundColor: '#f9fafb',
              borderRadius: '4px',
              border: '1px solid #e5e7eb'
            }}>
              📡 Will connect to: {wsUrl}
            </div>
          )}

          {endpointType === 'alb' && (
            <div style={{ 
              marginBottom: '15px',
              fontSize: '12px',
              color: '#6b7280',
              fontFamily: 'monospace',
              padding: '6px',
              backgroundColor: '#f9fafb',
              borderRadius: '4px',
              border: '1px solid #e5e7eb'
            }}>
              📡 Will connect to: wss://vak.tutzi.ai/ws
            </div>
          )}

          {/* Connection Button */}
          <div className="input-group">
            {!connected ? (
              <button 
                onClick={connectWebSocket} 
                className="btn btn-primary"
                style={{
                  opacity: 1,
                  cursor: 'pointer'
                }}
              >
                🔌 Connect
              </button>
            ) : (
              <button onClick={disconnectWebSocket} className="btn btn-danger">
                🚫 Disconnect
              </button>
            )}
            <button
              onClick={startCognitoAuth}
              className="btn btn-secondary"
              disabled={!getAuthUrl()}
              style={{
                marginLeft: '10px',
                opacity: getAuthUrl() ? 1 : 0.5,
                cursor: getAuthUrl() ? 'pointer' : 'not-allowed'
              }}
            >
              🔐 Authenticate
            </button>
          </div>
          <div style={{ marginTop: '12px' }}>
            <label style={{ 
              display: 'block', 
              fontSize: '14px', 
              fontWeight: '500', 
              color: '#374151',
              marginBottom: '5px'
            }}>
              Business Number (for testing):
            </label>
            <input
              type="text"
              placeholder="+15551234567"
              value={businessNumber}
              onChange={(e) => setBusinessNumber(e.target.value)}
              disabled={connected}
              style={{
                width: '100%',
                padding: '10px',
                fontSize: '14px',
                borderRadius: '6px',
                border: '1px solid #d1d5db',
                backgroundColor: connected ? '#f3f4f6' : '#ffffff'
              }}
            />
          </div>
          <div className="status">
            Status:{' '}
            <span className={connected ? 'status-connected' : 'status-disconnected'}>
              {connectionStatus === 'Connected'
                ? '🟢 Connected'
                : connectionStatus === 'Error'
                ? '⚠️ Error'
                : '🔴 Disconnected'}
            </span>
          </div>
          {/* TTS Engine selection removed - Deepgram Voice Agents handles TTS automatically */}
        </div>

        <div className="conversation-section">
          <div className="conversation-header">
            <div className="conversation-title">
              <span className="conversation-icon" aria-hidden="true">💬</span>
              Conversation
            </div>
            <div className={`conversation-pill ${connected ? 'is-live' : 'is-idle'}`}>
              {connectionStatus === 'Error' ? 'Error' : connected ? 'Live' : 'Idle'}
            </div>
          </div>
          <div className="conversation-content">
            {messagePairs.length === 0 && systemMessages.length === 0 && (
              <div className="conversation-placeholder">
                <span role="img" aria-hidden="true">👋</span>
                <p>Connect and start a conversation to see messages here.</p>
              </div>
            )}

            {messagePairs.map((pair) => {
              const meta = STATUS_META[pair.status];
              return (
                <div key={pair.id} className={`message-pair-card status-${meta.variant}`}>
                  <div className="message-pair-top">
                    <span className="message-pair-status">
                      <span className="status-icon" aria-hidden="true">{meta.icon}</span>
                      {meta.label}
                    </span>
                    <span className="message-pair-id">{pair.id}</span>
                  </div>

                  {pair.clientMessage && (
                    <div className="message-bubble user">
                      <div className="bubble-label">You</div>
                      <p>{pair.clientMessage}</p>
                    </div>
                  )}

                  {pair.aiReply && (
                    <div className="message-bubble ai">
                      <div className="bubble-label">Vak</div>
                      <p>{pair.aiReply}</p>
                    </div>
                  )}

                  {!pair.clientMessage && (
                    <div className="message-bubble placeholder">
                      <p>Waiting for input...</p>
                    </div>
                  )}
                </div>
              );
            })}

            {systemMessages.length > 0 && (
              <div className="system-log">
                <div className="system-log-title">Activity</div>
                {systemMessages.map((entry) => (
                  <div key={entry.id} className="system-log-item">
                    <span className="system-log-time">{entry.timestamp}</span>
                    <span className="system-log-text">{entry.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Live Transcription (for current recording) */}
        {isRecording && currentTranscript && (
          <div className="transcription-section" style={{ 
            marginTop: '20px', 
            padding: '15px', 
            backgroundColor: '#fff3cd', 
            borderRadius: '8px',
            border: '1px solid #ddd'
          }}>
            <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '10px', color: '#856404' }}>
              🎙️ Live Transcription
            </div>
            <div style={{ 
              padding: '8px', 
              backgroundColor: '#ffffff', 
              borderRadius: '4px',
              fontSize: '14px',
              color: '#856404',
              fontStyle: 'italic'
            }}>
              {currentTranscript}
            </div>
          </div>
        )}

        <div className="input-section">
          <div className="input-group">
            <input
              type="text"
              placeholder="Type a message..."
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && sendTextMessage()}
              disabled={!connected}
              className="text-input"
            />
            <button
              onClick={sendTextMessage}
              disabled={!connected || !textInput.trim()}
              className="btn btn-primary"
            >
              📤 Send
            </button>
          </div>
        </div>

        <div className="audio-section">
          {!isRecording ? (
            <button
              onClick={startRecording}
              disabled={!connected || isAgentSpeaking}
              className="btn btn-record"
            >
              🎙️ Start Conversation
            </button>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '15px', width: '100%' }}>
              <button
                onClick={stopRecording}
                className="btn btn-stop"
              >
                ⏹️ End Conversation
              </button>
              
              {/* Audio Level Visualizer */}
              <div style={{ 
                width: '100%', 
                maxWidth: '400px',
                padding: '15px',
                backgroundColor: '#f9fafb',
                borderRadius: '8px',
                border: '1px solid #e5e7eb'
              }}>
                <div style={{ 
                  fontSize: '12px', 
                  fontWeight: '600', 
                  color: '#666', 
                  marginBottom: '8px',
                  textAlign: 'center'
                }}>
                  🎤 Audio Level
                </div>
                
                {/* Audio Level Bar */}
                <div style={{
                  width: '100%',
                  height: '30px',
                  backgroundColor: '#e5e7eb',
                  borderRadius: '15px',
                  overflow: 'hidden',
                  position: 'relative',
                  border: '2px solid #d1d5db'
                }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${audioLevel}%`,
                      background: audioLevel > 70 
                        ? 'linear-gradient(90deg, #10b981 0%, #059669 50%, #dc2626 100%)'
                        : audioLevel > 30
                        ? 'linear-gradient(90deg, #10b981 0%, #059669 100%)'
                        : 'linear-gradient(90deg, #6b7280 0%, #9ca3af 100%)',
                      transition: 'width 0.1s ease-out, background 0.2s',
                      borderRadius: '15px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      paddingRight: '8px',
                      boxShadow: audioLevel > 10 ? '0 0 10px rgba(16, 185, 129, 0.3)' : 'none'
                    }}
                  >
                    {audioLevel > 5 && (
                      <span style={{ 
                        color: 'white', 
                        fontSize: '10px', 
                        fontWeight: 'bold',
                        textShadow: '0 1px 2px rgba(0,0,0,0.3)'
                      }}>
                        {Math.round(audioLevel)}%
                      </span>
                    )}
                  </div>
                </div>
                
                {/* Waveform Visualization */}
                <div style={{
                  marginTop: '10px',
                  height: '40px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '2px'
                }}>
                  {Array.from({ length: 20 }).map((_, i) => {
                    const barHeight = Math.max(4, (audioLevel / 100) * 40 * (1 - Math.abs(i - 10) / 10));
                    return (
                      <div
                        key={i}
                        style={{
                          width: '4px',
                          height: `${barHeight}px`,
                          backgroundColor: audioLevel > 5 
                            ? (i < 10 ? '#10b981' : '#059669')
                            : '#d1d5db',
                          borderRadius: '2px',
                          transition: 'height 0.1s ease-out, background-color 0.2s',
                          boxShadow: audioLevel > 5 ? '0 0 4px rgba(16, 185, 129, 0.4)' : 'none'
                        }}
                      />
                    );
                  })}
                </div>
                
                {/* Status Indicator */}
                <div style={{ 
                  fontSize: '12px', 
                  color: '#666', 
                  marginTop: '8px',
                  textAlign: 'center'
                }}>
                  {audioLevel < 1 && <span style={{ color: '#9ca3af' }}>🔇 No audio detected</span>}
                  {audioLevel >= 1 && audioLevel < 10 && <span style={{ color: '#6b7280' }}>🔉 Low audio</span>}
                  {audioLevel >= 10 && audioLevel < 30 && <span style={{ color: '#10b981' }}>🔊 Good audio</span>}
                  {audioLevel >= 30 && <span style={{ color: '#059669' }}>🔊 Strong audio</span>}
                </div>
              </div>
              
              <div style={{ fontSize: '14px', color: '#666' }}>
                {isAgentSpeaking && <span style={{ color: '#4CAF50' }}>🔊 Agent Speaking...</span>}
                {isProcessing && !isAgentSpeaking && <span style={{ color: '#FF9800' }}>⏳ Processing...</span>}
                {!isProcessing && !isAgentSpeaking && <span style={{ color: '#2196F3' }}>👂 Listening...</span>}
              </div>
            </div>
          )}

          {/* Recording Playback Controls */}
          {recordedAudioUrl && !isRecording && (
            <div style={{
              marginTop: '20px',
              padding: '15px',
              backgroundColor: '#f9fafb',
              borderRadius: '8px',
              border: '1px solid #e5e7eb',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
              alignItems: 'center'
            }}>
              <div style={{
                fontSize: '14px',
                fontWeight: '600',
                color: '#666',
                marginBottom: '5px'
              }}>
                🎙️ Recording Available
              </div>
              <div style={{
                display: 'flex',
                gap: '10px',
                flexWrap: 'wrap',
                justifyContent: 'center'
              }}>
                <button
                  onClick={playRecordedAudio}
                  className="btn"
                  style={{
                    backgroundColor: isPlayingRecording ? '#ef4444' : '#10b981',
                    color: 'white',
                    padding: '10px 20px',
                    fontSize: '14px'
                  }}
                >
                  {isPlayingRecording ? '⏸️ Pause' : '▶️ Play Recording'}
                </button>
                {isPlayingRecording && (
                  <button
                    onClick={stopRecordedAudio}
                    className="btn"
                    style={{
                      backgroundColor: '#6b7280',
                      color: 'white',
                      padding: '10px 20px',
                      fontSize: '14px'
                    }}
                  >
                    ⏹️ Stop
                  </button>
                )}
                <button
                  onClick={downloadRecordedAudio}
                  className="btn"
                  style={{
                    backgroundColor: '#3b82f6',
                    color: 'white',
                    padding: '10px 20px',
                    fontSize: '14px'
                  }}
                >
                  💾 Download
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;

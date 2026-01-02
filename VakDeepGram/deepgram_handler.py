"""
Deepgram Voice Agents Handler using STS (Secure Token Service)
Handles WebSocket connections and audio streaming to/from Deepgram Voice Agents
Uses direct WebSocket connection with STS authentication (like sts-twilio)
"""
import asyncio
import logging
import json
import base64
import uuid
from typing import Dict, Optional, Callable
import websockets
import config

logger = logging.getLogger(__name__)


class DeepgramSession:
    """Represents an active Deepgram Voice Agent session"""
    
    def __init__(self, connection_id: str, sts_ws, event_loop):
        self.connection_id = connection_id
        self.sts_ws = sts_ws  # The STS WebSocket connection
        self.event_loop = event_loop
        self.is_active = True
        self.is_ready = False  # Track if settings have been applied and session is ready
        self.message_id: Optional[str] = None
        self.send_to_client: Optional[Callable] = None
        self.audio_buffer: list = []  # Buffer audio until session is ready
        
    def set_send_callback(self, callback: Callable):
        """Set the callback function to send messages to the client"""
        self.send_to_client = callback
    
    async def send_to_client_safe(self, data: dict):
        """Safely send data to client if callback is set"""
        if self.send_to_client:
            try:
                await self.send_to_client(data)
            except Exception as e:
                logger.error(f"Error sending to client {self.connection_id}: {e}")


class DeepgramManager:
    """Manages Deepgram Voice Agent sessions using STS WebSocket"""
    
    def __init__(self):
        self.sessions: Dict[str, DeepgramSession] = {}
        self.api_key = config.settings.deepgram_api_key
    
    def _build_settings(self) -> dict:
        """Build the Settings message as JSON dict"""
        # Build listen provider
        listen_provider = {
            "type": "deepgram",
            "model": config.settings.deepgram_listening_model or "nova-3",
        }
        if config.settings.deepgram_listening_version:
            listen_provider["version"] = config.settings.deepgram_listening_version
        
        # Build think provider
        if config.settings.deepgram_thinking_provider == "open_ai":
            think_provider = {
                "type": "open_ai",
                "model": config.settings.deepgram_thinking_model or "gpt-4o-mini",
            }
        elif config.settings.deepgram_thinking_provider == "google":
            think_provider = {
                "type": "google",
                "model": config.settings.deepgram_thinking_model or "gemini-2.5-flash",
            }
        else:
            logger.warning(
                f"Unknown thinking provider '{config.settings.deepgram_thinking_provider}', "
                "defaulting to OpenAI"
            )
            think_provider = {
                "type": "open_ai",
                "model": config.settings.deepgram_thinking_model or "gpt-4o-mini",
            }
        
        think_config = {"provider": think_provider}
        if config.settings.deepgram_agent_prompt:
            think_config["prompt"] = config.settings.deepgram_agent_prompt
        
        # Build speak provider
        if config.settings.deepgram_speaking_provider == "eleven_labs":
            speak_provider = {
                "type": "eleven_labs",
                "model_id": config.settings.deepgram_speaking_model_id or "eleven_multilingual_v2",
                "voice_id": config.settings.deepgram_speaking_voice_id or "cgSgspJ2msm6clMCkdW9",
            }
        else:
            speak_provider = {
                "type": "deepgram",
                "model": config.settings.deepgram_speaking_model or "aura-2-thalia-en",
            }
        
        # Build agent config
        agent_config = {
            "language": config.settings.deepgram_agent_language or "en",
            "listen": {"provider": listen_provider},
            "think": think_config,
            "speak": {"provider": speak_provider},
        }
        if config.settings.deepgram_agent_greeting:
            agent_config["greeting"] = config.settings.deepgram_agent_greeting
        
        # Build settings message
        settings = {
            "type": "Settings",
            "audio": {
                "input": {
                    "encoding": "linear16",
                    "sample_rate": config.settings.deepgram_input_sample_rate or 16000,
                },
                "output": {
                    "encoding": "linear16",
                    "sample_rate": config.settings.deepgram_output_sample_rate or 16000,
                    "container": "none",  # Use "none" for raw PCM
                },
            },
            "agent": agent_config,
        }
        
        return settings
    
    async def _sts_connect(self):
        """Create STS WebSocket connection"""
        if not self.api_key:
            raise ValueError("DEEPGRAM_API_KEY must be set")
        
        try:
            sts_ws = await websockets.connect(
                "wss://agent.deepgram.com/v1/agent/converse",
                subprotocols=["token", self.api_key]
            )
            return sts_ws
        except Exception as e:
            logger.error(f"Failed to connect to Deepgram STS: {e}")
            raise
    
    async def create_session(self, connection_id: str) -> DeepgramSession:
        """Create a new Deepgram Voice Agent session using STS"""
        # Clean up any existing session
        await self.close_session(connection_id)
        
        logger.info(f"Creating Deepgram Voice Agent session for {connection_id}")
        
        # Create STS WebSocket connection
        sts_ws = await self._sts_connect()
        
        # Get the current event loop
        try:
            event_loop = asyncio.get_running_loop()
        except RuntimeError:
            event_loop = asyncio.get_event_loop()
        
        # Create session
        session = DeepgramSession(connection_id, sts_ws, event_loop)
        self.sessions[connection_id] = session
        
        # Build and send settings
        settings = self._build_settings()
        await sts_ws.send(json.dumps(settings))
        logger.info(f"Sent settings to Deepgram Voice Agent for {connection_id}")
        
        # Start receiver task
        asyncio.create_task(self._sts_receiver(session))
        
        logger.info(
            f"Created Deepgram session for {connection_id}: "
            f"listening={config.settings.deepgram_listening_model} "
            f"thinking={config.settings.deepgram_thinking_provider}/{config.settings.deepgram_thinking_model} "
            f"speaking={'ElevenLabs' if config.settings.deepgram_speaking_provider == 'eleven_labs' else 'Deepgram'}"
        )
        
        return session
    
    async def _sts_receiver(self, session: DeepgramSession):
        """Handle messages from Deepgram STS WebSocket"""
        try:
            async for message in session.sts_ws:
                if isinstance(message, str):
                    # Handle JSON messages
                    try:
                        data = json.loads(message)
                        await self._handle_json_message(session, data)
                    except json.JSONDecodeError as e:
                        logger.error(f"Error parsing JSON message: {e}")
                        logger.debug(f"Raw message: {message}")
                else:
                    # Handle binary audio data (TTS)
                    await self._handle_audio_message(session, message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"STS WebSocket closed for {session.connection_id}")
            if session.is_active:
                await session.send_to_client_safe({"type": "deepgram-disconnected"})
        except Exception as e:
            logger.error(f"Error in STS receiver for {session.connection_id}: {e}")
            if session.is_active:
                await session.send_to_client_safe({
                    "type": "error",
                    "message": f"Deepgram error: {str(e)}",
                })
        finally:
            self.sessions.pop(session.connection_id, None)
    
    async def _handle_json_message(self, session: DeepgramSession, data: dict):
        """Handle JSON messages from Deepgram"""
        if not session.is_active:
            return
        
        msg_type = data.get("type", "Unknown")
        
        if msg_type == "Welcome":
            welcome_text = data.get("message") or data.get("content")
            logger.info(f"Welcome message received for {session.connection_id}: {welcome_text}")
            if welcome_text:
                await session.send_to_client_safe({
                    "type": "welcome",
                    "message": welcome_text,
                    "connectionId": session.connection_id
                })
        
        elif msg_type == "SettingsApplied":
            logger.info(f"Settings applied for {session.connection_id}")
            session.is_ready = True
            await self._on_settings_applied(session)
        
        elif msg_type == "ConversationText":
            role = data.get("role", "")
            content = data.get("content", "")
            
            if role == "user" and content:
                await session.send_to_client_safe({
                    "type": "transcript",
                    "text": content,
                    "role": "user",
                    "isPartial": False,
                    "messageId": session.message_id,
                    "connectionId": session.connection_id,
                })
            elif role == "agent" and content:
                # Send as LLM tokens for streaming effect
                tokens = content.split(" ")
                for i, token in enumerate(tokens):
                    await session.send_to_client_safe({
                        "type": "llm-token",
                        "token": token + (" " if i < len(tokens) - 1 else ""),
                        "messageId": session.message_id,
                        "connectionId": session.connection_id,
                    })
                # Also send complete message
                await session.send_to_client_safe({
                    "type": "llm-response",
                    "text": content,
                    "role": "agent",
                    "messageId": session.message_id,
                    "connectionId": session.connection_id,
                })
        
        elif msg_type == "UserStartedSpeaking":
            logger.info(f"👤 User started speaking for {session.connection_id}")
            # Generate a new message ID for this conversation turn
            session.message_id = f"msg-{uuid.uuid4().hex[:12]}"
            await session.send_to_client_safe({
                "type": "message-id",
                "messageId": session.message_id,
                "connectionId": session.connection_id
            })
            await session.send_to_client_safe({
                "type": "user-started-speaking",
                "messageId": session.message_id,
                "connectionId": session.connection_id
            })
        
        elif msg_type == "AgentThinking":
            content = data.get("content", "")
            logger.info(f"🤔 Agent thinking for {session.connection_id}: {content}")
            await session.send_to_client_safe({
                "type": "processing-audio",
                "messageId": session.message_id,
                "connectionId": session.connection_id
            })
        
        elif msg_type == "AgentStartedSpeaking":
            logger.info(f"🎤 Agent started speaking for {session.connection_id}")
            await session.send_to_client_safe({
                "type": "agent-started-speaking",
                "connectionId": session.connection_id
            })
        
        elif msg_type == "AgentAudioDone":
            logger.info(f"✅ Agent audio done for {session.connection_id}")
            await session.send_to_client_safe({
                "type": "ready-to-listen",
                "connectionId": session.connection_id
            })
        
        elif msg_type == "Error":
            error_msg = data.get("message", str(data))
            logger.error(f"❌ Deepgram error event: {error_msg}")
            await session.send_to_client_safe({
                "type": "error",
                "message": error_msg,
            })
    
    async def _handle_audio_message(self, session: DeepgramSession, audio_data: bytes):
        """Handle binary audio messages (TTS) from Deepgram Voice Agent"""
        if len(audio_data) > 0:
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            logger.debug(
                f"🔊 Forwarding {len(audio_data)} bytes of TTS audio "
                f"to client {session.connection_id}"
            )
            await session.send_to_client_safe({
                "type": "tts",
                "audio": audio_base64,
                "messageId": session.message_id,
                "connectionId": session.connection_id,
                "size": len(audio_data),
            })
    
    async def _on_settings_applied(self, session: DeepgramSession):
        """Handle SettingsApplied event - flush buffered audio"""
        await session.send_to_client_safe({
            "type": "settings-applied",
            "connectionId": session.connection_id
        })
        await session.send_to_client_safe({"type": "deepgram-ready"})
        
        # Flush any buffered audio now that session is ready
        if session.audio_buffer:
            logger.info(f"Flushing {len(session.audio_buffer)} buffered audio chunks for {session.connection_id}")
            for audio_data in session.audio_buffer:
                await self._send_audio_to_deepgram(session, audio_data)
            session.audio_buffer.clear()
    
    def get_session(self, connection_id: str) -> Optional[DeepgramSession]:
        """Get an existing session by connection ID"""
        return self.sessions.get(connection_id)
    
    async def close_session(self, connection_id: str):
        """Close and clean up a session"""
        session = self.sessions.get(connection_id)
        if session:
            session.is_active = False
            session.is_ready = False
            session.audio_buffer.clear()
            
            try:
                if session.sts_ws:
                    await session.sts_ws.close()
            except Exception as e:
                logger.error(f"Error closing STS connection: {e}")
            finally:
                self.sessions.pop(connection_id, None)
                logger.info(f"🛑 Stopped Deepgram session for {connection_id}")
    
    async def _send_audio_to_deepgram(self, session: DeepgramSession, audio_data: bytes):
        """Send audio data to Deepgram Voice Agent"""
        try:
            if session.sts_ws and session.is_active:
                await session.sts_ws.send(audio_data)
            else:
                logger.warn(f"⚠️ Connection not ready for {session.connection_id}")
        except Exception as e:
            logger.error(f"Error sending audio to Deepgram: {e}")
            await self.close_session(session.connection_id)
    
    async def send_audio(self, connection_id: str, audio_data: bytes):
        """Send audio data to Deepgram Voice Agent
        
        Audio data should be PCM16 format at the configured sample rate.
        The Voice Agent will process this audio for speech recognition.
        
        If the session is not ready yet, audio will be buffered and sent
        once the SettingsApplied event is received.
        """
        session = self.get_session(connection_id)
        if not session or not session.is_active:
            logger.warn(f"⚠️ No active Deepgram session for {connection_id}, ignoring audio")
            return
        
        # If session is not ready yet, buffer the audio
        if not session.is_ready:
            session.audio_buffer.append(audio_data)
            if len(session.audio_buffer) == 1:  # Log only on first buffered chunk
                logger.debug(f"📦 Buffering audio for {connection_id} (session not ready yet, {len(audio_data)} bytes)")
            return
        
        # Session is ready, send audio immediately
        await self._send_audio_to_deepgram(session, audio_data)


# Global manager instance
deepgram_manager = DeepgramManager()

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
from websockets.protocol import State
from vakdeepgram import config
from providers import get_voice_prompt_for_provider
from vakdeepgram.agent_functions import FUNCTION_DEFINITIONS, FUNCTION_MAP, get_function_definitions_for_provider
from vakdeepgram.connection_store import get_localized_datetime_for_connection, get_connection_context, update_connection_context
from vakdeepgram.business_logic import forward_call_to_location
from utils.metrics import (
    emit_deepgram_session_start,
    emit_deepgram_session_error,
)

logger = logging.getLogger(__name__)


def _endpoint_from_connection_id(connection_id: Optional[str]) -> str:
    if not connection_id:
        return "unknown"
    if connection_id.startswith("twilio-"):
        return "twilio_ws"
    if connection_id.startswith("ws-"):
        return "ws"
    return "unknown"


class DeepgramSession:
    """Represents an active Deepgram Voice Agent session"""
    
    def __init__(self, connection_id: str, sts_ws, event_loop, use_mulaw: bool = False):
        logger.debug("DeepgramSession.__init__ called (connection_id=%s use_mulaw=%s)", connection_id, use_mulaw)
        self.connection_id = connection_id
        self.sts_ws = sts_ws  # The STS WebSocket connection
        self.event_loop = event_loop
        self.is_active = True
        self.is_ready = False  # Track if settings have been applied and session is ready
        self.message_id: Optional[str] = None
        self.send_to_client: Optional[Callable] = None
        self.on_fatal_error: Optional[Callable] = None  # Called on unrecoverable errors (e.g. Twilio fallback)
        self.audio_buffer: list = []  # Buffer audio until session is ready
        self.max_audio_buffer_size = config.settings.max_audio_buffer_size
        self.use_mulaw = use_mulaw  # Track if using mulaw encoding (for Twilio)
        self.pending_disconnect: bool = False
        self.pending_disconnect_reason: str = ""
        self.consecutive_failures: int = 0  # Track consecutive function failures for auto-transfer
        
    def set_send_callback(self, callback: Callable):
        """Set the callback function to send messages to the client"""
        logger.debug("DeepgramSession.set_send_callback called (connection_id=%s)", self.connection_id)
        self.send_to_client = callback
    
    async def send_to_client_safe(self, data: dict):
        """Safely send data to client if callback is set"""
        logger.debug("DeepgramSession.send_to_client_safe called (connection_id=%s type=%s)", self.connection_id, data.get("type"))
        if self.send_to_client:
            try:
                await self.send_to_client(data)
            except Exception as e:
                logger.error(f"Error sending to client {self.connection_id}: {e}")


class DeepgramManager:
    """Manages Deepgram Voice Agent sessions using STS WebSocket"""
    
    def __init__(self):
        logger.debug("DeepgramManager.__init__ called")
        self.sessions: Dict[str, DeepgramSession] = {}
        self.api_key = config.settings.deepgram_api_key
    
    def _resolve_provider(self, connection_id: Optional[str]) -> str:
        """Resolve the booking provider from the connection context."""
        if not connection_id:
            return "square"
        context = get_connection_context(connection_id)
        return (context.get("provider") or "square").lower() if context else "square"

    def _build_settings(self, use_mulaw: bool = False, connection_id: Optional[str] = None) -> dict:
        """Build the Settings message as JSON dict

        Args:
            use_mulaw: If True, configure for mulaw (8kHz) - used for Twilio
                      If False, configure for linear16 (48kHz) - used for browser
        """
        provider = self._resolve_provider(connection_id)
        logger.debug("DeepgramManager._build_settings called (connection_id=%s use_mulaw=%s provider=%s)", connection_id, use_mulaw, provider)

        # Get voice config from connection context (for per-business voice settings)
        voice_config = {}
        if connection_id:
            context = get_connection_context(connection_id)
            if context:
                # Context keys are snake_case after to_snake_case() in connection_store
                voice_config = context.get("voice_config") or {}

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

        # Build think config with provider-specific functions and prompt
        function_definitions = get_function_definitions_for_provider(provider)
        think_config = {
            "provider": think_provider,
            "functions": function_definitions,
        }
        prompt = get_voice_prompt_for_provider(provider)
        if connection_id:
            localized_datetime = get_localized_datetime_for_connection(connection_id)
            prompt = f"Current date and time is {localized_datetime} (local time).\n{prompt}"
        if prompt:
            think_config["prompt"] = prompt

        # Build speak provider - use voice config from business context or fall back to defaults
        # Keys are snake_case: voice_provider, voice_id, voice_model_id
        voice_provider = voice_config.get("voice_provider") or config.settings.deepgram_speaking_provider

        if voice_provider == "eleven_labs":
            speak_provider = {
                "type": "eleven_labs",
                "model_id": voice_config.get("voice_model_id") or config.settings.deepgram_speaking_model_id or "eleven_multilingual_v2",
                "voice_id": voice_config.get("voice_id") or config.settings.deepgram_speaking_voice_id or "0mevMNFMwHxBOUTpeMGN",
            }
        else:
            speak_provider = {
                "type": "deepgram",
                "model": voice_config.get("voice_id") or config.settings.deepgram_speaking_model or "aura-2-thalia-en",
            }

        # Log voice config usage
        if voice_config:
            logger.info(
                "Using business voice config for %s: provider=%s voice_id=%s",
                connection_id,
                voice_provider,
                voice_config.get("voice_id") or "(default)",
            )
        
        # Build agent config
        agent_config = {
            "language": config.settings.deepgram_agent_language or "en",
            "listen": {"provider": listen_provider},
            "think": think_config,
            "speak": {"provider": speak_provider},
        }

        # Build greeting with business name and caller name if available
        greeting = config.settings.deepgram_agent_greeting or ""
        if connection_id:
            context = get_connection_context(connection_id)
            business_name = None
            if context:
                location = context.get("location") or {}
                business_name = location.get("business_name") or location.get("name") or context.get("business_name")
                customer = context.get("customer")
                if customer and hasattr(customer, "model_dump"):
                    customer = customer.model_dump()
                first_name = None
                if isinstance(customer, dict):
                    first_name = customer.get("given_name") or customer.get("givenName")
                if first_name and business_name:
                    greeting = f"Hi {first_name}, welcome to {business_name}. How can I help you today?"
                elif first_name:
                    greeting = f"Hi {first_name}, how can I help you today?"
                elif business_name:
                    greeting = f"Hi, welcome to {business_name}. How can I help you today?"
        # Avoid stale hardcoded business names when context is not ready yet.
        if not greeting or "barber shop" in greeting.lower():
            greeting = "Hi, how can I help you today?"
        if greeting:
            agent_config["greeting"] = greeting
        
        # Build settings message - use mulaw for Twilio, linear16 for browser
        if use_mulaw:
            # Twilio configuration: mulaw at 8kHz (matches sts-twilio)
            settings = {
                "type": "Settings",
                "audio": {
                    "input": {
                        "encoding": "mulaw",
                        "sample_rate": 8000,
                    },
                    "output": {
                        "encoding": "mulaw",
                        "sample_rate": 8000,
                        "container": "none",
                    },
                },
                "agent": agent_config,
            }
        else:
            # Browser configuration: linear16 at 48kHz
            settings = {
                "type": "Settings",
                "audio": {
                    "input": {
                        "encoding": "linear16",
                        "sample_rate": config.settings.deepgram_input_sample_rate or 48000,
                    },
                    "output": {
                        "encoding": "linear16",
                        "sample_rate": config.settings.deepgram_output_sample_rate or 24000,
                        "container": "none",
                    },
                },
                "agent": agent_config,
            }
        
        logger.debug(
            "DeepgramManager._build_settings payload (connection_id=%s settings=%s)",
            connection_id,
            json.dumps(settings, indent=2, default=str),
        )
        return settings

    async def _wait_for_location_timezone(
        self,
        connection_id: str,
        timeout_seconds: float = 2.0,
        poll_interval: float = 0.05,
    ) -> None:
        """Wait briefly for location timezone to arrive in the connection context."""
        context = get_connection_context(connection_id)
        if not context:
            return
        timezone_name = (context.get("location") or {}).get("timezone") or context.get("timezone")
        if timezone_name:
            return
        if not (context.get("businessNumber") or context.get("locationId")):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            await asyncio.sleep(poll_interval)
            context = get_connection_context(connection_id)
            timezone_name = (context.get("location") or {}).get("timezone") or context.get("timezone")
            if timezone_name:
                return
    
    async def _sts_connect(self):
        """Create STS WebSocket connection"""
        logger.debug("DeepgramManager._sts_connect called")
        if not self.api_key:
            raise ValueError("DEEPGRAM_API_KEY must be set")

        try:
            timeout_seconds = config.settings.deepgram_sts_timeout_seconds
            sts_ws = await websockets.connect(
                "wss://agent.deepgram.com/v1/agent/converse",
                subprotocols=["token", self.api_key],
                open_timeout=timeout_seconds,
                close_timeout=timeout_seconds,
            )
            return sts_ws
        except Exception as e:
            logger.error(f"Failed to connect to Deepgram STS: {e}")
            raise
    
    async def create_session(self, connection_id: str, use_mulaw: bool = False) -> DeepgramSession:
        """Create a new Deepgram Voice Agent session using STS"""
        logger.debug("DeepgramManager.create_session called (connection_id=%s use_mulaw=%s)", connection_id, use_mulaw)
        # Clean up any existing session
        await self.close_session(connection_id)
        
        logger.info(f"Creating Deepgram Voice Agent session for {connection_id}")
        
        # Create STS WebSocket connection
        try:
            sts_ws = await self._sts_connect()
        except Exception as exc:
            emit_deepgram_session_error(_endpoint_from_connection_id(connection_id), type(exc).__name__)
            raise
        
        # Get the current event loop
        try:
            event_loop = asyncio.get_running_loop()
        except RuntimeError:
            event_loop = asyncio.get_event_loop()
        
        # Create session
        session = DeepgramSession(connection_id, sts_ws, event_loop, use_mulaw=use_mulaw)
        self.sessions[connection_id] = session
        
        # Build and send settings
        settings = self._build_settings(use_mulaw=use_mulaw, connection_id=connection_id)
        await sts_ws.send(json.dumps(settings))
        logger.info(f"Sent settings to Deepgram Voice Agent for {connection_id}")
        
        # Start receiver task
        asyncio.create_task(self._sts_receiver(session))
        emit_deepgram_session_start(_endpoint_from_connection_id(connection_id))
        
        provider = self._resolve_provider(connection_id)
        logger.info(
            f"Created Deepgram session for {connection_id}: "
            f"provider={provider} "
            f"listening={config.settings.deepgram_listening_model} "
            f"thinking={config.settings.deepgram_thinking_provider}/{config.settings.deepgram_thinking_model} "
            f"speaking={'ElevenLabs' if config.settings.deepgram_speaking_provider == 'eleven_labs' else 'Deepgram'}"
        )
        
        return session
    
    async def _sts_receiver(self, session: DeepgramSession):
        """Handle messages from Deepgram STS WebSocket"""
        logger.debug("DeepgramManager._sts_receiver called (connection_id=%s)", session.connection_id)
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
        except websockets.exceptions.ConnectionClosed as e:
            # Connection closed - could be timeout, error, or normal closure
            close_code = e.code if hasattr(e, 'code') else None
            close_reason = e.reason if hasattr(e, 'reason') else None
            
            # 1000 = normal closure, 1001 = going away, 1005 = no status (internal)
            # These are usually expected (timeout, client disconnect, etc.)
            if close_code in (1000, 1001, 1005):
                logger.info(f"🔌 STS WebSocket closed for {session.connection_id} (code: {close_code})")
            else:
                logger.warning(f"🔌 STS WebSocket closed unexpectedly for {session.connection_id} (code: {close_code}, reason: {close_reason})")
            
            if session.is_active:
                await session.send_to_client_safe({"type": "deepgram-disconnected"})
        except Exception as e:
            logger.error(f"Error in STS receiver for {session.connection_id}: {e}", exc_info=True)
            if session.is_active:
                await session.send_to_client_safe({
                    "type": "error",
                    "message": f"Deepgram error: {str(e)}",
                })
        finally:
            self.sessions.pop(session.connection_id, None)
            logger.debug(f"🧹 Cleaned up session {session.connection_id}")
    
    async def _handle_json_message(self, session: DeepgramSession, data: dict):
        """Handle JSON messages from Deepgram"""
        logger.debug("DeepgramManager._handle_json_message called (connection_id=%s type=%s)", session.connection_id, data.get("type"))
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
            if session.pending_disconnect:
                await session.send_to_client_safe({
                    "type": "disconnect",
                    "reason": session.pending_disconnect_reason or "end_call",
                    "connectionId": session.connection_id,
                })
                await self.close_session(session.connection_id)
        
        elif msg_type == "Error":
            error_code = data.get("code", "")
            error_msg = data.get("description") or data.get("message", str(data))
            
            # CLIENT_MESSAGE_TIMEOUT is expected when user doesn't speak for a while
            # It's not really an error, just Deepgram closing due to inactivity
            if error_code == "CLIENT_MESSAGE_TIMEOUT":
                logger.info(f"⏱️ Deepgram timeout (no user speech): {error_msg}")
                emit_deepgram_session_error(
                    _endpoint_from_connection_id(session.connection_id),
                    error_code or "CLIENT_MESSAGE_TIMEOUT",
                )
                await session.send_to_client_safe({
                    "type": "disconnect",
                    "reason": "timeout",
                    "connectionId": session.connection_id,
                })
                await self.close_session(session.connection_id)
            else:
                logger.error(f"❌ Deepgram error event: {error_msg} (code: {error_code})")
                emit_deepgram_session_error(
                    _endpoint_from_connection_id(session.connection_id),
                    error_code or "DeepgramError",
                )
                await session.send_to_client_safe({
                    "type": "error",
                    "message": error_msg,
                })
                if session.on_fatal_error:
                    logger.info("Triggering fatal error fallback for %s (code=%s)", session.connection_id, error_code)
                    await session.on_fatal_error(error_msg)
        
        elif msg_type in ("FunctionCall", "FunctionCallRequest"):
            # Handle function call request from Deepgram
            function_call = data.get("function_call") or data.get("function") or {}
            tool_call = {}
            if isinstance(data.get("tool_call"), dict):
                tool_call = data.get("tool_call", {})
            elif isinstance(data.get("tool_calls"), list) and data.get("tool_calls"):
                if isinstance(data["tool_calls"][0], dict):
                    tool_call = data["tool_calls"][0]
            if isinstance(data.get("functions"), list):
                logger.info("🔧 Function call batch received")
                for call in data["functions"]:
                    if not isinstance(call, dict):
                        continue
                    call_name = call.get("name") or call.get("function_name") or ""
                    call_args = call.get("arguments") or call.get("args") or {}
                    response_id_key = "call_id"
                    call_id = call.get("call_id") or call.get("callId")
                    if call.get("function_call_id"):
                        response_id_key = "function_call_id"
                        call_id = call.get("function_call_id")
                    elif call.get("tool_call_id"):
                        response_id_key = "tool_call_id"
                        call_id = call.get("tool_call_id")
                    elif call.get("id"):
                        call_id = call.get("id")
                    if not call_name or not call_id:
                        logger.warning(
                            "⚠️ Function call entry missing name or call_id; "
                            f"entry_keys={list(call.keys())}"
                        )
                        continue
                    await self._execute_function_call(
                        session=session,
                        function_name=call_name,
                        function_args=call_args,
                        call_id=call_id,
                        raw_args=call_args,
                        response_id_key=response_id_key,
                    )
                return
            function_name = (
                function_call.get("name")
                or tool_call.get("name")
                or tool_call.get("tool_name")
                or data.get("name")
                or data.get("function_name")
                or data.get("tool_name")
                or ""
            )
            raw_args = (
                function_call.get("arguments")
                if "arguments" in function_call
                else data.get("arguments")
            )
            if raw_args is None:
                raw_args = function_call.get("args", {})
            if raw_args is None:
                raw_args = tool_call.get("arguments")
            function_args = raw_args if raw_args is not None else {}
            response_id_key = "call_id"
            call_id = data.get("call_id")
            if data.get("function_call_id"):
                response_id_key = "function_call_id"
                call_id = data.get("function_call_id")
            elif data.get("tool_call_id"):
                response_id_key = "tool_call_id"
                call_id = data.get("tool_call_id")
            elif function_call.get("call_id"):
                call_id = function_call.get("call_id")
            elif function_call.get("id"):
                call_id = function_call.get("id")
            elif tool_call.get("id"):
                call_id = tool_call.get("id")
            elif data.get("id"):
                call_id = data.get("id")
            
            logger.info(f"🔧 Function call received: {function_name} (call_id: {call_id})")
            if not function_name or not call_id:
                logger.warning(
                    "⚠️ Function call missing name or call_id; "
                    f"keys={list(data.keys())}"
                )
            logger.debug(f"🔧 Function call details: {json.dumps(data, indent=2)}")
            
            await self._execute_function_call(
                session=session,
                function_name=function_name,
                function_args=function_args,
                call_id=call_id,
                raw_args=raw_args,
                response_id_key=response_id_key,
            )
        
        else:
            # Log unhandled message types for debugging
            logger.debug(f"📨 Unhandled message type: {msg_type} for {session.connection_id}")
            # logger.debug(f"📨 Message data: {json.dumps(data, indent=2, default=str)}")

    async def _execute_function_call(
        self,
        session: DeepgramSession,
        function_name: str,
        function_args,
        call_id: str,
        raw_args,
        response_id_key: str,
    ):
        """Execute a function call and return results to Deepgram."""
        logger.debug(
            "DeepgramManager._execute_function_call called (connection_id=%s name=%s call_id=%s)",
            session.connection_id,
            function_name,
            call_id,
        )
        if not function_name or not call_id:
            return

        try:
            if isinstance(function_args, str):
                try:
                    function_args = json.loads(function_args)
                except json.JSONDecodeError:
                    logger.warning(
                        "⚠️ Function arguments were not valid JSON; "
                        "passing through as raw string"
                    )
                    function_args = {"raw": function_args}
            if isinstance(function_args, dict):
                function_args.setdefault("connection_id", session.connection_id)

            logger.debug(
                f"🔧 Executing function '{function_name}' with args: "
                f"{json.dumps(function_args, indent=2)}"
            )
            function_impl = FUNCTION_MAP.get(function_name)
            if not function_impl:
                result = {
                    "success": False,
                    "function": function_name,
                    "error": f"Unknown function: {function_name}",
                }
            else:
                if function_name in ("agent_filler", "end_call"):
                    result = await function_impl(session.sts_ws, function_args)
                else:
                    result = await function_impl(function_args)

            logger.info(f"✅ Function '{function_name}' completed: success={result.get('success')}")
            logger.debug(
                "🔧 Function result (name=%s): %s",
                function_name,
                json.dumps(result, indent=2, default=str),
            )

            # Accumulate tool call metrics in connection context for call analytics
            ctx = get_connection_context(session.connection_id) or {}
            tool_count = (ctx.get("toolCallCount") or ctx.get("tool_call_count") or 0) + 1
            tool_error_count = (ctx.get("toolCallErrorCount") or ctx.get("tool_call_error_count") or 0) + (0 if result.get("success") else 1)
            update_connection_context(session.connection_id, {
                "toolCallCount": tool_count,
                "toolCallErrorCount": tool_error_count,
            })

            # Track consecutive failures for auto-transfer
            if result.get("success"):
                session.consecutive_failures = 0
            else:
                session.consecutive_failures += 1
                # Check for auto-transfer on consecutive failures
                context = get_connection_context(session.connection_id)
                voice_config = (context.get("voice_config") or {}) if context else {}
                enable_auto_transfer = voice_config.get("enable_auto_transfer", True)
                max_failures = voice_config.get("max_failures_before_transfer", 2)

                if enable_auto_transfer and session.consecutive_failures >= max_failures:
                    logger.warning(
                        "Auto-transfer triggered for %s after %d consecutive failures",
                        session.connection_id,
                        session.consecutive_failures,
                    )
                    transfer_result = await forward_call_to_location(session.connection_id)
                    if transfer_result.get("success"):
                        session.pending_disconnect = True
                        session.pending_disconnect_reason = "auto_transfer_on_failure"
                        # Reset failure count after transfer
                        session.consecutive_failures = 0

            result_payload = result
            if isinstance(raw_args, str):
                result_payload = json.dumps(result, default=str)

            function_result_message = {
                "type": "FunctionCallResponse",
                "id": call_id,
                "name": function_name,
                "content": result_payload,
            }

            logger.debug(
                "Deepgram function response payload (call_id=%s): %s",
                call_id,
                json.dumps(function_result_message, indent=2, default=str),
            )
            await session.sts_ws.send(json.dumps(function_result_message, default=str))
            logger.info(f"✅ Sent function result to Deepgram for call_id: {call_id}")

            if function_name == "end_call":
                session.pending_disconnect = True
                session.pending_disconnect_reason = "end_call"
            elif function_name in ("transfer_to_staff", "talk_to_owner"):
                if result.get("success"):
                    session.pending_disconnect = True
                    session.pending_disconnect_reason = function_name

        except Exception as e:
            logger.error(f"❌ Error executing function '{function_name}': {str(e)}", exc_info=True)
            error_result = {
                "success": False,
                "function": function_name,
                "error": str(e),
            }
            if isinstance(raw_args, str):
                error_result = json.dumps(error_result, default=str)

            function_result_message = {
                "type": "FunctionCallResponse",
                "id": call_id,
                "name": function_name,
                "content": error_result,
            }

            await session.sts_ws.send(json.dumps(function_result_message, default=str))
    
    async def _handle_audio_message(self, session: DeepgramSession, audio_data: bytes):
        """Handle binary audio messages (TTS) from Deepgram Voice Agent"""
        logger.debug("DeepgramManager._handle_audio_message called (connection_id=%s bytes=%d)", session.connection_id, len(audio_data))
        if len(audio_data) > 0:
            # Always encode as base64 for the callback (JSON-compatible)
            # The callback will decode and handle appropriately
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            encoding = "mulaw" if session.use_mulaw else "linear16"
            sample_rate = 8000 if session.use_mulaw else (config.settings.deepgram_output_sample_rate or 24000)
            logger.debug(
                f"🔊 Forwarding {len(audio_data)} bytes of {encoding} TTS audio "
                f"to client {session.connection_id}"
            )
            await session.send_to_client_safe({
                "type": "tts",
                "audio": audio_base64,
                "messageId": session.message_id,
                "connectionId": session.connection_id,
                "size": len(audio_data),
                "encoding": encoding,
                "sample_rate": sample_rate,
            })
    
    async def _on_settings_applied(self, session: DeepgramSession):
        """Handle SettingsApplied event - flush buffered audio"""
        logger.debug("DeepgramManager._on_settings_applied called (connection_id=%s)", session.connection_id)
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
        logger.debug("DeepgramManager.get_session called (connection_id=%s)", connection_id)
        return self.sessions.get(connection_id)
    
    async def close_session(self, connection_id: str):
        """Close and clean up a session"""
        logger.debug("DeepgramManager.close_session called (connection_id=%s)", connection_id)
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
        """Send audio data to Deepgram Voice Agent.
        Per-chunk metrics are not emitted here to avoid blocking the voice hot path (was causing noise)."""
        try:
            if session.sts_ws and session.is_active:
                # Check WebSocket state (websockets 16.0+ uses state instead of closed property)
                if session.sts_ws.state != State.OPEN:
                    logger.warning(
                        "STS WebSocket not open for %s (state=%s), marking session inactive",
                        session.connection_id,
                        session.sts_ws.state.name,
                    )
                    session.is_active = False
                    return
                await session.sts_ws.send(audio_data)
            else:
                logger.warning(
                    "Connection not ready for %s (ws=%s, active=%s)",
                    session.connection_id,
                    session.sts_ws is not None,
                    session.is_active,
                )
        except websockets.exceptions.ConnectionClosed as e:
            # Connection was closed (timeout, error, etc.) - this is expected
            logger.info(f"🔌 Deepgram connection closed for {session.connection_id}: {e.code} - {e.reason or 'no reason'}")
            session.is_active = False
            # Don't call close_session here - let the receiver handle cleanup
        except Exception as e:
            logger.error(f"Error sending audio to Deepgram for {session.connection_id}: {e}", exc_info=True)
            session.is_active = False
            # Don't call close_session here - let the receiver handle cleanup
    
    async def send_audio(self, connection_id: str, audio_data: bytes, force_send: bool = False):
        """Send audio data to Deepgram Voice Agent
        
        Audio data should be PCM16 format (or mulaw for Twilio) at the configured sample rate.
        The Voice Agent will process this audio for speech recognition.
        
        Args:
            connection_id: Session connection ID
            audio_data: Audio bytes to send
            force_send: If True, send immediately even if session not ready (for Twilio/mulaw mode)
        
        If the session is not ready yet and force_send=False, audio will be buffered and sent
        once the SettingsApplied event is received.
        """
        session = self.get_session(connection_id)
        if not session or not session.is_active:
            logger.warning(f"⚠️ No active Deepgram session for {connection_id}, ignoring audio")
            return
        
        # For mulaw mode (Twilio), send immediately - Deepgram accepts audio right after settings
        # For linear16 mode (browser), buffer if not ready to ensure proper initialization
        if not session.is_ready and not force_send:
            # Enforce max buffer size - drop oldest chunks if full
            if len(session.audio_buffer) >= session.max_audio_buffer_size:
                dropped = session.audio_buffer.pop(0)
                logger.warning(
                    "Audio buffer full for %s, dropping oldest chunk (%d bytes)",
                    connection_id,
                    len(dropped),
                )
            session.audio_buffer.append(audio_data)
            return
        
        # Session is ready or force_send=True, send audio immediately
        await self._send_audio_to_deepgram(session, audio_data)


# Global manager instance
deepgram_manager = DeepgramManager()

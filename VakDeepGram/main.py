"""
VakDeepGram - FastAPI WebSocket server for Deepgram Voice Agents
"""
import json
import logging
import uuid
import base64
import asyncio
from typing import Optional

from twilio.rest import Client as TwilioClient
from urllib.parse import urlencode, parse_qs
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from twilio.request_validator import RequestValidator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn
import config
from strands import Agent
from strands.models import BedrockModel
from strands.session.file_session_manager import FileSessionManager
try:
    from strands.event_loop._recover_message_on_max_tokens_reached import MaxTokensReachedException
except ImportError:
    MaxTokensReachedException = None
from deepgram_handler import deepgram_manager
from strands_tools import ALL_STRANDS_TOOLS
import json


def _make_json_serializable(obj):
    """Convert an object to JSON-serializable format."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    # For Square SDK objects and other classes, try to convert to dict
    if hasattr(obj, '__dict__'):
        return _make_json_serializable(vars(obj))
    if hasattr(obj, 'to_dict'):
        return _make_json_serializable(obj.to_dict())
    # Fallback to string representation
    return str(obj)
from connection_store import (
    get_connection_context,
    resolve_business_context,
    set_connection_context,
    clear_connection_context,
    normalize_phone_number,
    get_localized_datetime_from_context,
)

# Configure logging with PII redaction
from utils.logging import configure_pii_safe_logging
configure_pii_safe_logging(level=config.settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="VakDeepGram", version="1.0.0")

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# HTTP Bearer auth for /chat endpoint
security = HTTPBearer(auto_error=False)

# Track WebSocket connections per IP for rate limiting
_websocket_connections: dict[str, int] = {}


def verify_twilio_signature(request_url: str, params: dict, signature: str) -> bool:
    """
    Verify Twilio signature for WebSocket connection using official Twilio RequestValidator
    
    Args:
        request_url: The full URL of the request (without query string)
        params: Dictionary of query parameters
        signature: The X-Twilio-Signature header value
    
    Returns:
        True if signature is valid, False otherwise
    """
    logger.info("verify_twilio_signature called (url=%s)", request_url)
    logger.debug(f"=== Twilio Signature Verification Debug ===")
    logger.debug(f"Request URL: {request_url}")
    logger.debug(f"Query params received: {params}")
    logger.debug(f"Signature header received: {signature}")
    logger.debug(f"Auth token configured: {bool(config.settings.twilio_auth_token)}")
    logger.debug(f"Auth token length: {len(config.settings.twilio_auth_token) if config.settings.twilio_auth_token else 0}")
    
    if not config.settings.twilio_auth_token:
        logger.warning("Twilio auth token not configured, skipping signature verification")
        return True  # Allow connection if token not configured (for development)
    
    if not signature:
        logger.error("Missing X-Twilio-Signature header")
        return False
    
    try:
        # Initialize the Twilio RequestValidator with auth token
        validator = RequestValidator(config.settings.twilio_auth_token)
        
        # Validate the signature using Twilio's official validator
        # The validator.validate() method handles all the HMAC-SHA1 computation internally
        is_valid = validator.validate(request_url, params, signature)
        
        logger.info(f"Twilio RequestValidator result: {is_valid}")
        logger.info(f"=== Verification result: {is_valid} ===")
        
        return is_valid
    except Exception as e:
        logger.error(f"Error during Twilio signature verification: {e}", exc_info=True)
        return False


async def _resolve_and_set_context(
    connection_id: str,
    business_number: str,
    extra_context: Optional[dict] = None,
) -> None:
    logger.debug(
        "_resolve_and_set_context called (connection_id=%s business_number=%s)",
        connection_id,
        business_number,
    )
    try:
        caller_number = extra_context.get("caller") if extra_context else None
        context = await resolve_business_context(business_number, caller_number=caller_number)
    except Exception as exc:
        logger.error(
            "Failed to resolve business context for %s: %s",
            connection_id,
            exc,
            exc_info=True,
        )
        context = {"success": False, "error": str(exc)}

    existing_context = get_connection_context(connection_id)
    merged_context = {**existing_context, **context}
    if extra_context:
        merged_context.update(extra_context)

    set_connection_context(connection_id, merged_context)
    if not merged_context.get("success"):
        logger.warning("Failed to resolve business context: %s", merged_context.get("error"))


async def _end_twilio_call(
    connection_id: str,
    account_sid: Optional[str],
    call_sid: Optional[str],
) -> None:
    logger.debug(
        "_end_twilio_call called (connection_id=%s account_sid=%s call_sid=%s)",
        connection_id,
        bool(account_sid),
        bool(call_sid),
    )
    if not account_sid or not call_sid:
        logger.warning(
            "Missing Twilio identifiers for %s (accountSid=%s callSid=%s)",
            connection_id,
            bool(account_sid),
            bool(call_sid),
        )
        return
    if not config.settings.twilio_auth_token:
        logger.warning("Twilio auth token missing; cannot end call for %s", connection_id)
        return

    try:
        client = TwilioClient(account_sid, config.settings.twilio_auth_token)
        call = client.calls(call_sid).update(status="completed")
        logger.info("Twilio call ended for %s (callSid=%s)", connection_id, call.sid)
    except Exception as exc:
        logger.error(
            "Failed to end Twilio call for %s: %s",
            connection_id,
            exc,
            exc_info=True,
        )

# CORS middleware - restrict origins in production
_cors_origins = config.settings.cors_allowed_origins
if not _cors_origins and config.settings.environment.value == "development":
    _cors_origins = ["*"]
elif not _cors_origins:
    # Default allowed origins for non-dev environments
    _cors_origins = ["https://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True if _cors_origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with basic info"""
    logger.info("root endpoint called")
    return {
        "service": "VakDeepGram",
        "version": "1.0.0",
        "status": "running",
        "websocket_endpoint": "/ws",
        "twilio_endpoint": "/twilio",
        "chat_endpoint": "/chat",
        "twilio_chat_endpoint": "/twilio-chat",
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    logger.info("health endpoint called")
    return {"status": "ok"}


async def verify_chat_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> bool:
    """Verify API key for /chat endpoint."""
    api_key = config.settings.chat_api_key
    if not api_key:
        # No API key configured - allow access (development mode)
        return True
    if not credentials:
        raise HTTPException(status_code=401, detail="API key required")
    if credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


@app.post("/chat")
@limiter.limit(lambda: f"{config.settings.rate_limit_per_minute}/minute")
async def chat(
    request: Request,
    _auth: bool = Depends(verify_chat_auth),
):
    """Simple chat endpoint for browser testing.

    Accepts business_number to fetch business context (similar to voice assistant).
    Requires API key authentication when chat_api_key is configured.
    """
    logger.info("chat endpoint called")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    message = payload.get("message") or payload.get("text")
    if not message or not isinstance(message, str):
        raise HTTPException(status_code=400, detail="message is required.")

    # Get business number and customer number
    business_number = payload.get("business_number") or payload.get("businessNumber")
    customer_phone = payload.get("customer_number") or payload.get("customerPhone") or payload.get("customer_phone")
    session_id = payload.get("session_id") or payload.get("sessionId")

    if not business_number:
        raise HTTPException(status_code=400, detail="business_number is required")
    
    logger.info("Chat request: businessNumber=%s customerPhone=%s", business_number, customer_phone)
    
    # Resolve business context directly (without connection store)
    business_context = {}
    if business_number:
        try:
            business_context = await resolve_business_context(business_number, caller_number=customer_phone)
            if customer_phone:
                business_context["caller"] = customer_phone
        except Exception as exc:
            logger.error("Failed to resolve business context: %s", exc, exc_info=True)
            business_context = {"success": False, "error": str(exc)}

    system_prompt = payload.get("system_prompt") or config.settings.chat_agent_prompt or ""
    model_id = payload.get("model_id") or config.settings.bedrock_model_id
    max_tokens = payload.get("max_tokens") or config.settings.bedrock_max_tokens
    temperature = payload.get("temperature") or config.settings.bedrock_temperature
    try:
        max_tokens = int(max_tokens)
        temperature = float(temperature)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid max_tokens or temperature.")

    logger.info("Invoking Strands Agent chat (model=%s message_chars=%d max_tokens=%d)",
                model_id, len(message), max_tokens)
    try:
        # Create Bedrock model with Strands
        bedrock_model = BedrockModel(
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            region_name=config.settings.aws_region,
        )

        # Create agent with system prompt and all voice assistant tools
        # Pass business context via state so tools receive it deterministically
        # Add current local time to context for relative date inference
        business_context["current_local_time"] = get_localized_datetime_from_context(business_context)
        # Convert to JSON-serializable format (Square SDK objects aren't serializable)
        serializable_context = _make_json_serializable(business_context)
        normalized_phone = normalize_phone_number(customer_phone) if customer_phone else None
        resolved_session_id = session_id or f"chat:{business_number}:{normalized_phone or uuid.uuid4().hex}"
        session_manager = FileSessionManager(session_id=resolved_session_id)
        agent = Agent(
            model=bedrock_model,
            system_prompt=system_prompt if system_prompt else None,
            tools=ALL_STRANDS_TOOLS,
            state={"business_context": serializable_context},
            session_manager=session_manager,
        )

        # Invoke agent in executor to avoid blocking async event loop
        def invoke_agent():
            return agent(message)

        response = await asyncio.to_thread(invoke_agent)

        # Extract reply from response
        if isinstance(response, str):
            reply = response
        elif hasattr(response, "content"):
            reply = response.content
        elif isinstance(response, dict):
            reply = response.get("content") or response.get("reply") or str(response)
        else:
            reply = str(response)
            
    except Exception as exc:
        error_msg = str(exc)
        logger.error("Strands Agent invoke failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Agent request failed: {error_msg}")

    return {"reply": reply, "model_id": model_id}


def verify_twilio_http_signature(request: Request, body: bytes) -> bool:
    """
    Verify Twilio signature for HTTP POST requests.

    For POST requests, Twilio signs: URL + sorted POST body parameters

    Args:
        request: The FastAPI request object
        body: The raw request body bytes

    Returns:
        True if signature is valid, False otherwise
    """
    logger.info("verify_twilio_http_signature called")

    if not config.settings.twilio_auth_token:
        logger.warning("Twilio auth token not configured, skipping signature verification")
        return True  # Allow in development

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.error("Missing X-Twilio-Signature header")
        return False

    # Build the full URL (Twilio signs the full URL without query string for POST)
    # Use X-Forwarded headers if behind a load balancer
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", request.url.netloc))
    path = request.url.path

    request_url = f"{scheme}://{host}{path}"

    # For POST requests, parse the body as form data
    try:
        # Twilio sends form-encoded data
        body_str = body.decode("utf-8")
        params = dict(parse_qs(body_str, keep_blank_values=True))
        # parse_qs returns lists, flatten to single values
        params = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        params = {}

    logger.info(f"Twilio HTTP signature verification - URL: {request_url}")
    logger.info(f"Twilio HTTP signature verification - Params: {params}")

    try:
        validator = RequestValidator(config.settings.twilio_auth_token)
        is_valid = validator.validate(request_url, params, signature)
        logger.info(f"Twilio HTTP signature verification result: {is_valid}")
        return is_valid
    except Exception as e:
        logger.error(f"Error during Twilio signature verification: {e}", exc_info=True)
        return False


@app.post("/twilio-chat")
@limiter.limit(lambda: f"{config.settings.rate_limit_per_minute}/minute")
async def twilio_chat(request: Request):
    """Chat endpoint for Twilio webhook callbacks.

    Similar to /chat but verifies Twilio signature instead of API key.
    Accepts business_number to fetch business context (similar to voice assistant).
    """
    logger.info("twilio_chat endpoint called")

    # Read raw body for signature verification
    body = await request.body()

    # Verify Twilio signature
    if not verify_twilio_http_signature(request, body):
        is_production = config.settings.environment.value == "production"
        verification_enabled = config.settings.twilio_signature_verification_enabled

        if is_production and verification_enabled:
            logger.error("Rejecting /twilio-chat request: invalid Twilio signature")
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
        logger.warning("Allowing /twilio-chat request despite failed signature verification (non-production)")

    # Parse the request body
    try:
        # Twilio sends form-encoded data, but we also support JSON
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            payload = json.loads(body.decode("utf-8"))
        else:
            # Form-encoded data from Twilio
            body_str = body.decode("utf-8")
            parsed = parse_qs(body_str, keep_blank_values=True)
            payload = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        raise HTTPException(status_code=400, detail="Invalid request body")

    # Extract message - Twilio typically sends "Body" for SMS
    message = (
        payload.get("message") or
        payload.get("text") or
        payload.get("Body") or
        payload.get("body")
    )
    if not message or not isinstance(message, str):
        raise HTTPException(status_code=400, detail="message is required")

    # Get business number - Twilio sends "To" for the destination number
    business_number = (
        payload.get("business_number") or
        payload.get("businessNumber") or
        payload.get("To") or
        payload.get("to")
    )
    stripped_business_number = business_number
    # Strip "whatsapp:" prefix if present
    if business_number and business_number.startswith("whatsapp:"):
        stripped_business_number = business_number[9:]  # Remove "whatsapp:" prefix

    # Get customer number - Twilio sends "From" for the sender
    customer_phone = (
        payload.get("customer_number") or
        payload.get("customerPhone") or
        payload.get("customer_phone") or
        payload.get("From") or
        payload.get("from")
    )
    # Strip "whatsapp:" prefix if present
    stripped_customer_phone = customer_phone
    if customer_phone and customer_phone.startswith("whatsapp:"):
        stripped_customer_phone = customer_phone[9:]  # Remove "whatsapp:" prefix
    session_id = payload.get("session_id") or payload.get("sessionId")

    if not stripped_business_number:
        raise HTTPException(status_code=400, detail="business_number is required")

    logger.info("Twilio chat request: businessNumber=%s customerPhone=%s", stripped_business_number, stripped_customer_phone)

    # Resolve business context directly (without connection store)
    # This fetches Square credentials, services, staff, etc. for the business
    business_context = {}
    if stripped_business_number:
        try:
            business_context = await resolve_business_context(stripped_business_number, caller_number=stripped_customer_phone)
            if stripped_customer_phone:
                business_context["caller"] = stripped_customer_phone
            if business_context.get("success"):
                logger.info(
                    "Resolved Square context for %s: locationId=%s, services=%d, staff=%d",
                    stripped_business_number,
                    business_context.get("locationId"),
                    len(business_context.get("services") or []),
                    len(business_context.get("staff") or []),
                )
            else:
                logger.warning("Failed to resolve business context: %s", business_context.get("error"))
        except Exception as exc:
            logger.error("Failed to resolve business context: %s", exc, exc_info=True)
            business_context = {"success": False, "error": str(exc)}

    system_prompt = payload.get("system_prompt") or config.settings.chat_agent_prompt or ""
    model_id = payload.get("model_id") or config.settings.bedrock_model_id
    max_tokens = payload.get("max_tokens") or config.settings.bedrock_max_tokens
    temperature = payload.get("temperature") or config.settings.bedrock_temperature
    try:
        max_tokens = int(max_tokens)
        temperature = float(temperature)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid max_tokens or temperature.")

    logger.info("Invoking Strands Agent for Twilio chat (model=%s message_chars=%d max_tokens=%d)",
                model_id, len(message), max_tokens)
    try:
        # Create Bedrock model with Strands
        bedrock_model = BedrockModel(
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            region_name=config.settings.aws_region,
        )

        # Create agent with system prompt and all voice assistant tools
        # Pass business context via state so tools receive it deterministically
        # Add current local time to context for relative date inference
        business_context["current_local_time"] = get_localized_datetime_from_context(business_context)
        # Convert to JSON-serializable format (Square SDK objects aren't serializable)
        serializable_context = _make_json_serializable(business_context)
        normalized_phone = normalize_phone_number(stripped_customer_phone) if stripped_customer_phone else None
        resolved_session_id = session_id or f"chat:{stripped_business_number}:{normalized_phone or uuid.uuid4().hex}"
        session_manager = FileSessionManager(session_id=resolved_session_id)
        agent = Agent(
            model=bedrock_model,
            system_prompt=system_prompt if system_prompt else None,
            tools=ALL_STRANDS_TOOLS,
            state={"business_context": serializable_context},
            session_manager=session_manager,
        )

        # Invoke agent in executor to avoid blocking async event loop
        def invoke_agent():
            return agent(message)

        response = await asyncio.to_thread(invoke_agent)

        # Extract reply from response
        if isinstance(response, str):
            reply = response
        elif hasattr(response, "content"):
            reply = response.content
        elif isinstance(response, dict):
            reply = response.get("content") or response.get("reply") or str(response)
        else:
            reply = str(response)

    except Exception as exc:
        error_msg = str(exc)
        is_max_tokens_error = (
            MaxTokensReachedException and isinstance(exc, MaxTokensReachedException)
        ) or (
            "max_tokens" in error_msg.lower() or
            "MaxTokensReachedException" in str(type(exc)) or
            "unrecoverable state due to max_tokens" in error_msg.lower()
        )

        if is_max_tokens_error:
            logger.warning("Strands Agent hit max_tokens limit (max_tokens=%d).", max_tokens)
            reply = "Sorry, I couldn't complete my response. Please try a simpler question."
        else:
            logger.error("Strands Agent invoke failed: %s", exc, exc_info=True)
            reply = "Sorry, something went wrong. Please try again later."

    # Send SMS reply directly using Twilio client
    try:
        from twilio.rest import Client as TwilioClient

        twilio_account_sid = config.settings.twilio_account_sid
        twilio_auth_token = config.settings.twilio_auth_token

        if not twilio_account_sid or not twilio_auth_token:
            logger.error("Twilio credentials not configured")
            raise HTTPException(status_code=500, detail="Twilio credentials not configured")

        client = TwilioClient(twilio_account_sid, twilio_auth_token)

        # Send SMS: from business number to customer
        sms_message = client.messages.create(
            body=reply,
            from_=business_number,  # The Twilio number that received the message
            to=customer_phone,      # The customer who sent the message
        )

        logger.info("Sent SMS reply via Twilio: sid=%s from=%s to=%s",
                    sms_message.sid, business_number, customer_phone)

    except Exception as sms_exc:
        logger.error("Failed to send SMS via Twilio: %s", sms_exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to send SMS: {str(sms_exc)}")

    # Return empty TwiML response (we already sent the SMS directly)
    twiml_response = '''<?xml version="1.0" encoding="UTF-8"?>
<Response></Response>'''

    return Response(content=twiml_response, media_type="application/xml")


def _get_client_ip(websocket: WebSocket) -> str:
    """Extract client IP from WebSocket connection."""
    if websocket.client:
        return websocket.client.host
    return "unknown"


def _check_websocket_rate_limit(client_ip: str) -> bool:
    """Check if client IP has exceeded WebSocket connection limit."""
    max_connections = config.settings.max_websocket_connections_per_ip
    current = _websocket_connections.get(client_ip, 0)
    return current < max_connections


def _increment_websocket_count(client_ip: str) -> None:
    """Increment WebSocket connection count for IP."""
    _websocket_connections[client_ip] = _websocket_connections.get(client_ip, 0) + 1


def _decrement_websocket_count(client_ip: str) -> None:
    """Decrement WebSocket connection count for IP."""
    current = _websocket_connections.get(client_ip, 0)
    if current > 0:
        _websocket_connections[client_ip] = current - 1


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Deepgram Voice Agents (browser clients)

    Starts Deepgram session immediately on connection for bidirectional audio streaming.
    """
    logger.info("websocket_endpoint called")

    # Check WebSocket connection rate limit
    client_ip = _get_client_ip(websocket)
    if not _check_websocket_rate_limit(client_ip):
        logger.warning("WebSocket connection limit exceeded for IP: %s", client_ip)
        await websocket.close(code=1008, reason="Connection limit exceeded")
        return

    _increment_websocket_count(client_ip)
    await websocket.accept()
    connection_id = f"ws-{uuid.uuid4().hex[:12]}"
    logger.info(f"WebSocket connection established: {connection_id}")

    business_number = websocket.query_params.get("businessNumber")
    customer_phone = websocket.query_params.get("customerPhone")
    if business_number:
        logger.info("Browser client provided businessNumber=%s for %s", business_number, connection_id)
        set_connection_context(
            connection_id,
            {
                "success": False,
                "pending": True,
                "businessNumber": business_number,
                "caller": customer_phone,
            },
        )
        await _resolve_and_set_context(
            connection_id,
            business_number,
            extra_context={"caller": customer_phone} if customer_phone else None,
        )
    else:
        logger.info("No businessNumber provided for %s", connection_id)
    
    session = None
    
    async def send_to_client(data: dict):
        """Helper function to send data to client"""
        try:
            if data.get("type") == "disconnect":
                await websocket.close(code=1000, reason=data.get("reason") or "end_call")
                return
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"Error sending to client {connection_id}: {e}")
            raise
    
    # Start Deepgram session immediately on connection (bidirectional audio)
    logger.info(f"Starting Deepgram session immediately for {connection_id}")
    try:
        session = await deepgram_manager.create_session(connection_id, use_mulaw=False)
        session.set_send_callback(send_to_client)
        await send_to_client({"type": "recording-started"})
        await send_to_client({"type": "deepgram-ready"})
        logger.info(f"Deepgram session started for {connection_id}")
    except Exception as e:
        logger.error(f"Error creating Deepgram session: {e}", exc_info=True)
        await send_to_client({
            "type": "error",
            "message": f"Failed to start Deepgram session: {str(e)}"
        })
        await websocket.close()
        return
    
    try:
        while True:
            # Receive message from client
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected: {connection_id}")
                break
            except RuntimeError as exc:
                if 'disconnect message has been received' in str(exc):
                    logger.info("WebSocket already disconnected for %s", connection_id)
                    break
                raise
            
            # Handle text messages (JSON)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    action = data.get("action")
                    
                    if action == "stop-deepgram" or action == "stop-recording":
                        logger.info(f"Stopping Deepgram session for {connection_id}")
                        if session:
                            await deepgram_manager.close_session(connection_id)
                            session = None
                        await send_to_client({"type": "recording-stopped"})
                    
                    elif action == "set-tts-engine":
                        # Ignore TTS engine selection - Deepgram Voice Agent handles TTS automatically
                        logger.debug(f"Ignoring set-tts-engine action (Deepgram handles TTS)")
                    
                    elif action == "start-deepgram" or action == "start-recording":
                        # Session already started, just acknowledge
                        logger.debug(f"Session already started for {connection_id}, acknowledging")
                        await send_to_client({"type": "recording-started"})
                    
                    else:
                        logger.debug(f"Received action: {action} (session already active)")
                
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing JSON message: {e}")
                    await send_to_client({
                        "type": "error",
                        "message": "Invalid JSON format"
                    })
            
            # Handle binary messages (audio data) - send directly to Deepgram
            elif "bytes" in message:
                audio_data = message["bytes"]
                if session and session.is_active:
                    await deepgram_manager.send_audio(connection_id, audio_data)
                else:
                    logger.warning(f"No active session for {connection_id}, ignoring audio")
            
            # Handle other message types
            else:
                logger.debug(f"Received unknown message type: {list(message.keys())}")
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket handler for {connection_id}: {e}", exc_info=True)
    finally:
        # Clean up session
        if session:
            await deepgram_manager.close_session(connection_id)
        clear_connection_context(connection_id)
        _decrement_websocket_count(client_ip)
        logger.info("Cleaned up connection: %s", connection_id)


@app.websocket("/twilio")
async def twilio_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Twilio Stream connections

    Follows sts-twilio implementation exactly:
    - Starts Deepgram session immediately on connection (bidirectional)
    - Receives mulaw audio from Twilio (8kHz)
    - Sends raw mulaw directly to Deepgram (no conversion)
    - Receives raw mulaw from Deepgram and sends to Twilio (no conversion)
    - Deepgram is configured to use mulaw encoding (8kHz)
    - Handles Twilio message format: {"event": "start/media/stop", ...}
    - Verifies Twilio signature before accepting connection
    """
    logger.info("twilio_websocket_endpoint called")

    # Check WebSocket connection rate limit
    client_ip = _get_client_ip(websocket)
    if not _check_websocket_rate_limit(client_ip):
        logger.warning("WebSocket connection limit exceeded for IP: %s", client_ip)
        await websocket.close(code=1008, reason="Connection limit exceeded")
        return
    # Get query parameters and signature from headers before accepting
    logger.info(f"=== Incoming Twilio WebSocket Connection ===")
    logger.info(f"Client: {websocket.client}")
    logger.info(f"URL: {websocket.url}")
    logger.info(f"URL scheme: {websocket.url.scheme}")
    logger.info(f"URL netloc: {websocket.url.netloc}")
    logger.info(f"URL path: {websocket.url.path}")
    logger.info(f"URL query: {websocket.url.query}")
    logger.info(f"All headers: {dict(websocket.headers)}")
    
    query_params = dict(websocket.query_params)
    logger.info(f"Parsed query params: {query_params}")
    
    signature = websocket.headers.get("X-Twilio-Signature", "")
    logger.info(f"X-Twilio-Signature header: {signature}")
    
    # Build the request URL (without query string)
    # Note: Twilio signature verification uses the full URL path, not including query params in URL
    # For WebSocket connections, Twilio may sign based on the original HTTP/HTTPS URL before upgrade
    # Try both HTTPS and WSS schemes to handle different Twilio signing behaviors
    original_scheme = websocket.url.scheme
    netloc = websocket.url.netloc
    path = websocket.url.path
    
    # Primary URL: Use HTTPS/WSS based on original scheme
    wss_url = f"wss://{netloc}{path}"
    https_url = f"https://{netloc}{path}"
    
    logger.info(f"Original URL scheme: {original_scheme}")
    logger.info(f"Will try WSS URL: {wss_url}")
    logger.info(f"Will try HTTPS URL: {https_url}")
    
    # Verify Twilio signature
    # Try WSS first (most likely for WebSocket connections)
    # Then try HTTPS (in case Twilio signs based on original HTTP request)
    signature_verification_result = True  # Default to True (allow connection)
    if signature:  # Only verify if signature is present
        signature_verification_result = verify_twilio_signature(wss_url, query_params, signature)
        if not signature_verification_result:
            logger.info(f"WSS URL verification failed, trying HTTPS URL...")
            signature_verification_result = verify_twilio_signature(https_url, query_params, signature)
            if signature_verification_result:
                logger.info(f"HTTPS URL verification succeeded")
    else:
        logger.warning("No signature header present, skipping verification (allowing connection)")
    
    if not signature_verification_result:
        is_production = config.settings.environment.value == "production"
        verification_enabled = config.settings.twilio_signature_verification_enabled

        if not signature:
            logger.warning("No X-Twilio-Signature header received from %s", websocket.client)
            if is_production and verification_enabled:
                logger.error("Rejecting connection: signature verification required in production")
                await websocket.close(code=1008, reason="Signature verification failed")
                return
            logger.warning("Allowing connection without signature (non-production mode)")
        else:
            logger.error("Twilio signature verification FAILED for connection from %s", websocket.client)
            logger.debug("Tried WSS URL: %s", wss_url)
            logger.debug("Tried HTTPS URL: %s", https_url)
            logger.debug("Query params used: %s", query_params)
            if is_production and verification_enabled:
                logger.error("Rejecting connection: invalid signature in production")
                await websocket.close(code=1008, reason="Signature verification failed")
                return
            logger.warning("Allowing connection despite failed verification (non-production mode)")
    
    logger.info("Twilio signature verified for connection from %s", websocket.client)

    _increment_websocket_count(client_ip)
    await websocket.accept()
    connection_id = f"twilio-{uuid.uuid4().hex[:12]}"
    logger.info(f"Twilio WebSocket connection established: {connection_id}")
    
    stream_sid_ref = {"value": None}  # Use dict to allow modification in nested functions
    session_ref = {"value": None}
    audio_queue = asyncio.Queue()
    streamsid_queue = asyncio.Queue()
    
    # Buffer for Twilio audio (160 bytes = 20ms of mulaw at 8kHz)
    # Buffer 20 twilio messages (0.4 seconds) to improve throughput (matches sts-twilio)
    BUFFER_SIZE = 20 * 160  # 0.4 seconds of audio
    
    async def send_to_twilio(data: dict):
        """Send JSON message to Twilio"""
        try:
            if data.get("type") == "disconnect":
                await websocket.close(code=1000, reason=data.get("reason") or "end_call")
                return
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"Error sending to Twilio {connection_id}: {e}")
            raise
    
    async def send_to_deepgram_wrapper(data: dict):
        """Wrapper to handle Deepgram messages and send to Twilio (matches sts-twilio)"""
        msg_type = data.get("type")
        
        if msg_type == "tts" and data.get("audio"):
            # Deepgram sends mulaw audio as base64, decode and send raw mulaw to Twilio
            # Matches sts-twilio: raw_mulaw = message (where message is binary from sts_ws)
            raw_mulaw = base64.b64decode(data["audio"])
            
            # Construct Twilio media message with raw mulaw (matches sts-twilio exactly)
            if stream_sid_ref["value"]:
                media_message = {
                    "event": "media",
                    "streamSid": stream_sid_ref["value"],
                    "media": {"payload": base64.b64encode(raw_mulaw).decode("ascii")},
                }
                await send_to_twilio(media_message)
        
        elif msg_type == "user-started-speaking":
            # Handle barge-in - send clear message to Twilio (matches sts-twilio)
            if stream_sid_ref["value"]:
                clear_message = {
                    "event": "clear",
                    "streamSid": stream_sid_ref["value"]
                }
                await send_to_twilio(clear_message)

        elif msg_type == "disconnect":
            context = get_connection_context(connection_id)
            await _end_twilio_call(
                connection_id,
                context.get("accountSid"),
                context.get("callSid"),
            )
            await send_to_twilio({
                "type": "disconnect",
                "reason": data.get("reason") or "end_call",
            })
        
        # Other message types can be logged but don't need to be sent to Twilio
        logger.debug(f"Deepgram message for Twilio: {msg_type}")
    
    session_ready = asyncio.Event()
    
    async def deepgram_receiver():
        """Receive messages from Deepgram and forward to Twilio (matches sts-twilio sts_receiver)"""
        await session_ready.wait()
        # Wait for streamSid - callback is already set, but we need streamSid before sending audio
        await streamsid_queue.get()
        logger.info(f"Deepgram receiver ready for {connection_id}, streamSid: {stream_sid_ref['value']}")
        
        # Keep this task alive - the actual receiving is handled by DeepgramManager's _sts_receiver
        # which calls send_to_deepgram_wrapper via the callback
        # Wait indefinitely until connection closes
        try:
            while session_ref["value"] and session_ref["value"].is_active:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in Deepgram receiver: {e}", exc_info=True)
    
    async def twilio_receiver():
        """Handle messages from Twilio"""
        inbuffer = bytearray(b"")
        
        async for message in websocket.iter_text():
            try:
                data = json.loads(message)
                event = data.get("event")
                
                if event == "start":
                    logger.info(f"Twilio stream started: {connection_id}")
                    start_data = data.get("start", {})
                    custom_params = start_data.get("customParameters") or start_data.get("custom_parameters") or {}
                    custom_params_lower = {
                        str(key).lower(): value for key, value in custom_params.items()
                    }
                    sid = start_data.get("streamSid")
                    to_number = (
                        custom_params.get("Called")
                        or custom_params.get("To")
                        or custom_params_lower.get("called")
                        or custom_params_lower.get("to")
                        or start_data.get("to")
                        or start_data.get("called")
                        or start_data.get("To")
                    )
                    from_number = (
                        custom_params.get("Caller")
                        or custom_params.get("From")
                        or custom_params_lower.get("caller")
                        or custom_params_lower.get("from")
                        or start_data.get("from")
                        or start_data.get("From")
                    )
                    call_sid = (
                        custom_params.get("CallSid")
                        or custom_params_lower.get("callsid")
                        or start_data.get("callSid")
                        or start_data.get("CallSid")
                    )
                    service_name = (
                        custom_params.get("Service")
                        or custom_params_lower.get("service")
                    )
                    account_sid = start_data.get("accountSid") or start_data.get("AccountSid")
                    
                    logger.info(
                        "Twilio start event: connectionId=%s streamSid=%s callSid=%s accountSid=%s from=%s to=%s service=%s",
                        connection_id,
                        sid,
                        call_sid,
                        account_sid,
                        from_number,
                        to_number,
                        service_name,
                    )
                    if custom_params:
                        logger.info("Twilio custom parameters: %s", json.dumps(custom_params, default=str))
                    logger.debug("Twilio start event full data: %s", json.dumps(data, default=str))
                    normalized_number = normalize_phone_number(to_number)
                    if normalized_number:
                        extra_context = {
                            "called": to_number,
                            "caller": from_number,
                            "service": service_name,
                            "callSid": call_sid,
                            "accountSid": account_sid,
                        }
                        set_connection_context(
                            connection_id,
                            {
                                "success": False,
                                "pending": True,
                                "businessNumber": normalized_number,
                                **extra_context,
                            },
                        )
                        await _resolve_and_set_context(
                            connection_id,
                            normalized_number,
                            extra_context=extra_context,
                        )
                    else:
                        logger.info("No Twilio business number available for %s", connection_id)
                        set_connection_context(
                            connection_id,
                            {
                                "success": False,
                                "error": "Missing business number.",
                                "called": to_number,
                                "caller": from_number,
                                "service": service_name,
                                "callSid": call_sid,
                            },
                        )
                    if sid:
                        stream_sid_ref["value"] = sid
                        streamsid_queue.put_nowait(sid)
                        logger.info(f"Got streamSid: {sid}")
                    if session_ref["value"] is None:
                        logger.info(f"Starting Deepgram session for Twilio {connection_id} (mulaw mode)")
                        try:
                            session = await deepgram_manager.create_session(connection_id, use_mulaw=True)
                            session_ref["value"] = session
                            session.set_send_callback(send_to_deepgram_wrapper)
                            session_ready.set()
                            logger.info(f"Deepgram session created and callback set for {connection_id}")
                        except Exception as e:
                            logger.error(f"Failed to create Deepgram session: {e}", exc_info=True)
                            await websocket.close()
                            return
                
                elif event == "connected":
                    logger.info(f"Twilio connected: {connection_id}")
                    continue
                
                elif event == "media":
                    media = data.get("media", {})
                    if media.get("track") == "inbound":
                        try:
                            # Decode base64 mulaw audio from Twilio
                            chunk = base64.b64decode(media["payload"])
                            inbuffer.extend(chunk)
                            
                            # Buffer mulaw audio and send raw mulaw to Deepgram when buffer is ready
                            # No conversion needed - Deepgram accepts mulaw directly (matches sts-twilio)
                            while len(inbuffer) >= BUFFER_SIZE:
                                mulaw_chunk = bytes(inbuffer[:BUFFER_SIZE])
                                inbuffer = inbuffer[BUFFER_SIZE:]
                                
                                # Send raw mulaw bytes directly to Deepgram (no conversion)
                                # This will be sent immediately via deepgram_sender (force_send=True)
                                audio_queue.put_nowait(mulaw_chunk)
                                logger.debug(f"Queued {len(mulaw_chunk)} bytes of mulaw audio from Twilio for {connection_id}")
                        except Exception as e:
                            logger.error(f"Error processing media event: {e}", exc_info=True)
                
                elif event == "stop":
                    logger.info(f"Twilio stream stopped: {connection_id}")
                    break
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing Twilio JSON: {e}")
            except Exception as e:
                logger.error(f"Error in Twilio receiver: {e}")
                break
    
    async def deepgram_sender():
        """Send raw mulaw audio from Twilio to Deepgram (matches sts-twilio sts_sender)"""
        await session_ready.wait()
        # Session is already created with callback set, just start sending
        logger.info(f"Deepgram sender started for {connection_id}")
        
        # Send raw mulaw chunks directly to Deepgram (no conversion)
        # Matches sts-twilio: async def sts_sender(sts_ws): while True: chunk = await audio_queue.get(); await sts_ws.send(chunk)
        # Note: Send immediately even if session not ready (force_send=True) - Deepgram accepts audio right after settings
        while True:
            try:
                mulaw_chunk = await audio_queue.get()
                if session_ref["value"] and session_ref["value"].is_active:
                    # Send raw mulaw bytes directly with force_send=True (matches sts-twilio immediate sending)
                    await deepgram_manager.send_audio(connection_id, mulaw_chunk, force_send=True)
                    logger.debug(f"Sent {len(mulaw_chunk)} bytes of mulaw audio to Deepgram for {connection_id}")
                else:
                    logger.warn(f"Session not active, dropping audio chunk for {connection_id}")
            except Exception as e:
                logger.error(f"Error in Deepgram sender: {e}", exc_info=True)
                break
    
    try:
        # Start all tasks concurrently (matches sts-twilio: asyncio.wait with all three tasks)
        # 1. twilio_receiver: Receives messages from Twilio, buffers audio, sends to audio_queue
        # 2. deepgram_sender: Sends audio from audio_queue to Deepgram
        # 3. deepgram_receiver: Waits for streamSid, then handles Deepgram responses via callback
        await asyncio.gather(
            asyncio.create_task(twilio_receiver()),
            asyncio.create_task(deepgram_sender()),
            asyncio.create_task(deepgram_receiver()),
            return_exceptions=True
        )
    except Exception as e:
        logger.error(f"Error in Twilio WebSocket handler: {e}")
    finally:
        # Clean up session
        if session_ref["value"]:
            await deepgram_manager.close_session(connection_id)
        clear_connection_context(connection_id)
        _decrement_websocket_count(client_ip)
        logger.info("Cleaned up Twilio connection: %s", connection_id)


if __name__ == "__main__":
    logger.info("🎙️ Starting VakDeepGram server...")
    logger.info(f"   Listening: {config.settings.deepgram_listening_model} (v{config.settings.deepgram_listening_version})")
    logger.info(f"   Thinking: {config.settings.deepgram_thinking_provider}/{config.settings.deepgram_thinking_model}")
    if config.settings.deepgram_speaking_provider == "eleven_labs":
        logger.info(f"   Speaking: ElevenLabs ({config.settings.deepgram_speaking_model_id}, voice: {config.settings.deepgram_speaking_voice_id})")
    else:
        logger.info(f"   Speaking: Deepgram ({config.settings.deepgram_speaking_model})")
    
    uvicorn.run(
        "main:app",
        workers=config.settings.workers,
        host=config.settings.host,
        port=config.settings.port,
        log_level=config.settings.log_level,
        reload=config.settings.reload
    )

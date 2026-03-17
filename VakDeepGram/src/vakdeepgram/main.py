"""
VakDeepGram - FastAPI WebSocket server for Deepgram Voice Agents
"""
import json
import logging
import uuid
import base64
import asyncio
import time
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
from vakdeepgram import config
from strands import Agent
from strands.models import BedrockModel
from strands.session.file_session_manager import FileSessionManager
try:
    from strands.event_loop._recover_message_on_max_tokens_reached import MaxTokensReachedException
except ImportError:
    MaxTokensReachedException = None
from vakdeepgram.deepgram_handler import deepgram_manager
from providers import get_tools_for_provider, get_chat_prompt_for_provider, get_voice_prompt_for_provider
from utils.case import to_snake_case
from utils.metrics import (
    emit_call_duration,
    emit_user_message_count,
    emit_agent_metrics,
    emit_max_tokens_reached,
    emit_active_connections,
    emit_message_delivery,
)
from utils.call_records import write_call_record
from utils.session_storage import upload_transcript, upload_recording
from utils.customers import upsert_voice_customer


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


def _seed_agent_state(agent: Agent, context: dict) -> None:
    """Initialize Strands agent state using state.set for all keys."""
    state = getattr(agent, "state", None)
    if state is None or not hasattr(state, "set"):
        return
    state.set("business_context", context)
    for key, value in context.items():
        state.set(key, value)


from vakdeepgram.connection_store import (
    normalize_phone_number,
    get_localized_datetime_from_context,
)
from vakdeepgram.repositories import (
    get_connection_context_by_id,
    set_connection_context_by_id,
    update_connection_context_by_id,
    clear_connection_context_by_id,
)
from vakdeepgram.services import (
    resolve_context_for_request,
    resolve_and_store_connection_context,
)
from vakdeepgram.security.oauth import validate_oauth_token

# Configure logging with PII redaction
from utils.logging import configure_pii_safe_logging
configure_pii_safe_logging(level=config.settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="VakDeepGram", version="1.0.0")

# Short-lived store for pre-resolved business context from /voice/oauth/connect.
# Key: short token passed in the WS URL. Value: (context_dict, expiry_timestamp).
# Avoids re-resolution in /ws and keeps the WS URL short.
_pre_resolved_contexts: dict[str, tuple[dict, float]] = {}
_PRE_RESOLVED_TTL = 120  # seconds — plenty of time for client to open WS

def _store_pre_resolved(context: dict) -> str:
    token = uuid.uuid4().hex[:16]
    _pre_resolved_contexts[token] = (context, time.monotonic() + _PRE_RESOLVED_TTL)
    # Prune expired entries
    now = time.monotonic()
    expired = [k for k, (_, exp) in _pre_resolved_contexts.items() if exp < now]
    for k in expired:
        _pre_resolved_contexts.pop(k, None)
    return token

def _pop_pre_resolved(token: str) -> dict | None:
    entry = _pre_resolved_contexts.pop(token, None)
    if not entry:
        return None
    context, expiry = entry
    if time.monotonic() > expiry:
        return None
    return context

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# HTTP Bearer auth for /chat endpoint
security = HTTPBearer(auto_error=False)

# Track WebSocket connections per IP for rate limiting
_websocket_connections: dict[str, int] = {}
_chat_message_counts: dict[str, int] = {}


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
    merged_context = await resolve_and_store_connection_context(
        connection_id,
        business_number,
        extra_context=extra_context,
    )
    if merged_context.get("success"):
        logger.info(
            "Business context resolved and stored for connection_id=%s businessNumber=%s",
            connection_id,
            business_number,
        )
    else:
        logger.warning("Failed to resolve business context: %s", merged_context.get("error"))


async def _say_and_end_twilio_call(
    connection_id: str,
    account_sid: Optional[str],
    call_sid: Optional[str],
    message: str = "We're sorry, something went wrong on our end. Please call back in a few minutes.",
) -> None:
    """Redirect the active Twilio call to a <Say> TwiML then hang up."""
    if not account_sid or not call_sid:
        logger.warning("_say_and_end_twilio_call: missing identifiers for %s", connection_id)
        return
    if not config.settings.twilio_auth_token:
        logger.warning("_say_and_end_twilio_call: no auth token for %s", connection_id)
        return
    twiml = f'<Response><Say voice="Polly.Joanna">{message}</Say><Hangup/></Response>'
    try:
        client = TwilioClient(account_sid, config.settings.twilio_auth_token)
        client.calls(call_sid).update(twiml=twiml)
        logger.info("_say_and_end_twilio_call: fallback message played for %s (sid=%s)", connection_id, call_sid)
    except Exception as exc:
        logger.error("_say_and_end_twilio_call: failed for %s: %s", connection_id, exc, exc_info=True)


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


def _parse_twilio_start_event(data: dict) -> dict:
    """Parse Twilio WebSocket start event. Returns stream_sid, to_number, from_number, call_sid, account_sid, service_name, custom_params.
    Used so we can unit-test parsing and support both nested start.* and root-level fields (per Twilio docs)."""
    start_data = data.get("start", {}) or {}
    custom_params = start_data.get("customParameters") or start_data.get("custom_parameters") or {}
    custom_params_lower = {str(k).lower(): v for k, v in custom_params.items()}
    sid = start_data.get("streamSid") or data.get("streamSid")
    to_number = (
        custom_params.get("Called") or custom_params.get("To")
        or custom_params_lower.get("called") or custom_params_lower.get("to")
        or start_data.get("to") or start_data.get("called") or start_data.get("To")
        or data.get("To") or data.get("Called")
    )
    from_number = (
        custom_params.get("Caller") or custom_params.get("From")
        or custom_params_lower.get("caller") or custom_params_lower.get("from")
        or start_data.get("from") or start_data.get("Caller") or start_data.get("From")
        or data.get("From") or data.get("Caller")
    )
    call_sid = (
        custom_params.get("CallSid") or custom_params_lower.get("callsid")
        or start_data.get("callSid") or start_data.get("CallSid")
        or data.get("callSid") or data.get("CallSid")
    )
    account_sid = (
        start_data.get("accountSid") or start_data.get("AccountSid")
        or data.get("accountSid") or data.get("AccountSid")
    )
    service_name = custom_params.get("Service") or custom_params_lower.get("service")
    return {
        "stream_sid": sid,
        "to_number": to_number,
        "from_number": from_number,
        "call_sid": call_sid,
        "account_sid": account_sid,
        "service_name": service_name,
        "custom_params": custom_params,
    }


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
        "voice_oauth_connect_endpoint": "/voice/oauth/connect",
        "twilio_endpoint": "/twilio",
        "chat_endpoint": "/chat",
        "chat_oauth_endpoint": "/chat/oauth",
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


async def verify_oauth_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Verify OAuth bearer token using configured JWKS settings.
    Also accepts a shared API key (chat_api_key) for service-to-service callers.
    """
    host = request.headers.get("host") or request.url.hostname
    if _localhost_oauth_bypass_allowed(host):
        logger.info("Bypassing OAuth auth for localhost request (host=%s)", host)
        return {"claims": {}, "token": None, "bypassed": True}
    if not credentials:
        raise HTTPException(status_code=401, detail="Bearer token required")
    # API key path — used by Slack bot and other internal callers
    api_key = config.settings.chat_api_key
    if api_key and credentials.credentials == api_key:
        return {"claims": {}, "token": credentials.credentials, "api_key": True}
    # OAuth JWT path
    result = validate_oauth_token(credentials.credentials)
    if not result.get("success"):
        raise HTTPException(status_code=401, detail=result.get("error") or "Invalid OAuth token")
    claims = result.get("claims") or {}
    if not isinstance(claims, dict):
        raise HTTPException(status_code=401, detail="Invalid OAuth claims payload")
    return {"claims": claims, "token": credentials.credentials}


def _normalize_business(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return normalize_phone_number(value) or str(value)


def _is_localhost_host(host_value: Optional[str]) -> bool:
    if not host_value:
        return False
    host = str(host_value).strip().lower()
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    elif ":" in host:
        host = host.split(":", 1)[0]
    return host in {"localhost", "127.0.0.1", "::1"}


def _localhost_oauth_bypass_allowed(host_value: Optional[str]) -> bool:
    return bool(config.settings.oauth_allow_localhost_noauth and _is_localhost_host(host_value))


def _validate_token_business_match(claims: dict, business_number: str) -> None:
    token_business = claims.get("business_number") or claims.get("businessNumber")
    if not token_business:
        return
    req_business = _normalize_business(business_number)
    claim_business = _normalize_business(str(token_business))
    if req_business != claim_business:
        raise HTTPException(status_code=403, detail="Token business_number does not match request.")


def _validate_websocket_oauth(query_params, headers) -> tuple[bool, Optional[str], Optional[dict]]:
    host = headers.get("host") or headers.get("Host")
    if _localhost_oauth_bypass_allowed(host):
        logger.info("Bypassing WebSocket OAuth auth for localhost request (host=%s)", host)
        return True, None, {}

    token = query_params.get("access_token") or query_params.get("token")
    if not token:
        auth_header = headers.get("authorization") or headers.get("Authorization") or ""
        if isinstance(auth_header, str) and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return False, "Bearer token required", None

    result = validate_oauth_token(token)
    if not result.get("success"):
        return False, result.get("error") or "Invalid OAuth token", None
    claims = result.get("claims") or {}
    if not isinstance(claims, dict):
        return False, "Invalid OAuth claims payload", None

    query_business = query_params.get("businessNumber")
    token_business = claims.get("business_number") or claims.get("businessNumber")
    if token_business:
        if not query_business:
            return False, "businessNumber query parameter required for token-bound businesses", None
        req_business = _normalize_business(query_business)
        claim_business = _normalize_business(str(token_business))
        if req_business != claim_business:
            return False, "Token business_number does not match businessNumber query parameter", None

    return True, token, claims


def _get_chat_session_manager(session_id: str):
    """Return session manager: AgentCore Memory if configured, else file-based."""
    if config.settings.agentcore_memory_id:
        try:
            from bedrock_agentcore.memory.integrations.strands.session_manager import (
                AgentCoreMemorySessionManager,
            )
            from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
            memory_config = AgentCoreMemoryConfig(
                memory_id=config.settings.agentcore_memory_id,
                session_id=session_id,
                actor_id=config.settings.agentcore_actor_id,
            )
            return AgentCoreMemorySessionManager(
                agentcore_memory_config=memory_config,
                region_name=config.settings.aws_region,
            )
        except Exception as e:
            logger.warning("AgentCore Memory session manager unavailable (%s), using file session", e)
    return FileSessionManager(session_id=session_id)


@app.post("/chat")
@limiter.limit(lambda: f"{config.settings.rate_limit_per_minute}/minute")
async def chat(
    request: Request,
    oauth_auth: dict = Depends(verify_oauth_auth),
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
    claims = oauth_auth.get("claims") or {}
    _validate_token_business_match(claims, business_number)
    
    logger.info("Chat request: businessNumber=%s customerPhone=%s", business_number, customer_phone)
    
    # Resolve business context directly (without connection store)
    business_context = {}
    if business_number:
        try:
            business_context = await resolve_context_for_request(
                business_number,
                caller_number=customer_phone,
            )
        except Exception as exc:
            logger.error("Failed to resolve business context: %s", exc, exc_info=True)
            business_context = {"success": False, "error": str(exc)}

    # Resolve provider from business context for provider-specific tools and prompts
    provider = (business_context.get("provider") or "square").lower()
    logger.info("Chat provider resolved: %s", provider)
    provider_tools = get_tools_for_provider(provider)
    provider_prompt = get_chat_prompt_for_provider(provider)

    system_prompt = payload.get("system_prompt") or provider_prompt or ""
    model_id = payload.get("model_id") or config.settings.bedrock_model_id
    max_tokens = payload.get("max_tokens") or config.settings.bedrock_max_tokens
    temperature = payload.get("temperature") or config.settings.bedrock_temperature
    try:
        max_tokens = int(max_tokens)
        temperature = float(temperature)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid max_tokens or temperature.")

    logger.info("Invoking Strands Agent chat (model=%s provider=%s tools=%d message_chars=%d max_tokens=%d)",
                model_id, provider, len(provider_tools), len(message), max_tokens)
    agent_start = time.monotonic()
    try:
        # Create Bedrock model with Strands
        bedrock_model = BedrockModel(
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            region_name=config.settings.aws_region,
        )

        # Create agent with provider-specific system prompt and tools
        # Pass business context via state so tools receive it deterministically
        # Add current local time to context for relative date inference
        business_context["current_local_time"] = get_localized_datetime_from_context(business_context)
        # Convert to JSON-serializable format (Square SDK objects aren't serializable)
        serializable_context = _make_json_serializable(business_context)
        normalized_phone = normalize_phone_number(customer_phone) if customer_phone else None
        resolved_session_id = session_id or f"chat:{business_number}:{normalized_phone or uuid.uuid4().hex}"
        _chat_message_counts[resolved_session_id] = _chat_message_counts.get(resolved_session_id, 0) + 1
        emit_user_message_count("chat", resolved_session_id, _chat_message_counts[resolved_session_id])
        session_manager = _get_chat_session_manager(resolved_session_id)
        serializable_context = to_snake_case(serializable_context)
        initial_state = {"business_context": serializable_context, **serializable_context}
        agent = Agent(
            model=bedrock_model,
            system_prompt=system_prompt if system_prompt else None,
            tools=provider_tools,
            state=initial_state,
            session_manager=session_manager,
        )
        _seed_agent_state(agent, serializable_context)

        # Invoke agent in executor to avoid blocking async event loop
        def invoke_agent(a, msg):
            return a(msg)

        response = None
        agent_error_type = None
        agent_success = False
        last_exc = None
        for attempt in range(2):
            try:
                response = await asyncio.to_thread(invoke_agent, agent, message)
                agent_success = True
                break
            except Exception as exc:
                last_exc = exc
                agent_error_type = type(exc).__name__
                error_msg = str(exc).lower()
                # ConverseStream validation: toolResult blocks exceed toolUse (Strands session repair bug)
                is_tool_result_exceeds = (
                    ("validationexception" in error_msg or "conversestream" in error_msg)
                    and "toolresult" in error_msg
                    and "tooluse" in error_msg
                    and "exceeds" in error_msg
                )
                if is_tool_result_exceeds and attempt == 0:
                    logger.warning(
                        "Strands session history has toolResult/toolUse mismatch; clearing session and retrying once: session_id=%s",
                        resolved_session_id,
                    )
                    try:
                        session_manager.delete_session(resolved_session_id)
                    except Exception as e:
                        logger.debug("Session delete failed (may not exist): %s", e)
                    # Retry with fresh session (AgentCore Memory doesn't support delete, so use new session_id)
                    retry_session_id = f"{resolved_session_id}:retry-{uuid.uuid4().hex[:8]}"
                    session_manager = _get_chat_session_manager(retry_session_id)
                    initial_state = {"business_context": serializable_context, **serializable_context}
                    agent = Agent(
                        model=bedrock_model,
                        system_prompt=system_prompt if system_prompt else None,
                        tools=provider_tools,
                        state=initial_state,
                        session_manager=session_manager,
                    )
                    _seed_agent_state(agent, serializable_context)
                    continue
                logger.error("Strands Agent invoke failed: %s", exc, exc_info=True)
                # If retry already happened and same error, return user-friendly message
                if is_tool_result_exceeds and attempt == 1:
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            "Conversation state is inconsistent. Please start a new conversation "
                            "(use a new session_id or refresh the chat)."
                        ),
                    )
                raise HTTPException(status_code=502, detail=f"Agent request failed: {str(exc)}")

        if response is None:
            emit_agent_metrics(
                endpoint="chat",
                provider=provider,
                duration_ms=(time.monotonic() - agent_start) * 1000,
                success=False,
                error_type=agent_error_type or "UnknownError",
            )
            raise HTTPException(status_code=502, detail=f"Agent request failed: {str(last_exc)}")

        # Extract reply from response
        if isinstance(response, str):
            reply = response
        elif hasattr(response, "content"):
            reply = response.content
        elif isinstance(response, dict):
            reply = response.get("content") or response.get("reply") or str(response)
        else:
            reply = str(response)

        emit_agent_metrics(
            endpoint="chat",
            provider=provider,
            duration_ms=(time.monotonic() - agent_start) * 1000,
            success=agent_success,
            error_type=agent_error_type if not agent_success else None,
        )

    except HTTPException:
        raise
    except Exception as exc:
        error_msg = str(exc)
        logger.error("Strands Agent invoke failed: %s", exc, exc_info=True)
        is_max_tokens_error = (
            MaxTokensReachedException and isinstance(exc, MaxTokensReachedException)
        ) or (
            "max_tokens" in error_msg.lower()
            or "MaxTokensReachedException" in str(type(exc))
            or "unrecoverable state due to max_tokens" in error_msg.lower()
        )
        if is_max_tokens_error:
            emit_max_tokens_reached("chat", provider)
        emit_agent_metrics(
            endpoint="chat",
            provider=provider,
            duration_ms=(time.monotonic() - agent_start) * 1000,
            success=False,
            error_type="MaxTokensReached" if is_max_tokens_error else type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail=f"Agent request failed: {error_msg}")

    return {"reply": reply, "model_id": model_id}


@app.post("/voice/oauth/connect")
@limiter.limit(lambda: f"{config.settings.rate_limit_per_minute}/minute")
async def voice_oauth_connect(
    request: Request,
    oauth_auth: dict = Depends(verify_oauth_auth),
):
    """OAuth-protected voice connect endpoint for Integrin clients.

    Returns a browser voice websocket URL pre-populated with business info.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    business_number = payload.get("business_number") or payload.get("businessNumber")
    customer_phone = payload.get("customer_number") or payload.get("customerNumber") or payload.get("customerPhone")
    if not business_number:
        raise HTTPException(status_code=400, detail="business_number is required")

    # Optional voice config override — allows callers to pass test config without
    # requiring a saved "Done" configuration in the dashboard.
    voice_config_override = payload.get("voice_config") or payload.get("voiceConfig")


    claims = oauth_auth.get("claims") or {}
    token = oauth_auth.get("token")
    _validate_token_business_match(claims, business_number)

    try:
        business_context = await resolve_context_for_request(
            business_number,
            caller_number=customer_phone,
        )
    except Exception as exc:
        logger.error("Failed to resolve business context for OAuth voice connect: %s", exc, exc_info=True)
        business_context = {"success": False, "error": str(exc)}

    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    ws_scheme = "wss" if forwarded_proto == "https" else "ws"
    query_params = {"businessNumber": business_number}
    if customer_phone:
        query_params["customerPhone"] = customer_phone
    if token:
        query_params["access_token"] = token
    import json as _json
    # Store pre-resolved context server-side; pass a short token in the URL.
    # This lets /ws skip re-resolution without bloating the WS URL.
    ctx_token = _store_pre_resolved(_make_json_serializable(business_context))
    query_params["ctxToken"] = ctx_token
    if voice_config_override and isinstance(voice_config_override, dict):
        query_params["voiceConfigOverride"] = base64.urlsafe_b64encode(
            _json.dumps(voice_config_override).encode()
        ).decode()
    websocket_url = f"{ws_scheme}://{forwarded_host}/ws?{urlencode(query_params)}"

    return {
        "success": True,
        "websocket_url": websocket_url,
        "business_number": business_number,
        "customer_number": customer_phone,
        "oauth_subject": claims.get("sub"),
        "business_context": _make_json_serializable(business_context),
    }


@app.post("/chat/oauth")
@limiter.limit(lambda: f"{config.settings.rate_limit_per_minute}/minute")
async def chat_oauth(
    request: Request,
    oauth_auth: dict = Depends(verify_oauth_auth),
):
    """OAuth-protected chat endpoint for Integrin clients."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    business_number = payload.get("business_number") or payload.get("businessNumber")
    if not business_number:
        raise HTTPException(status_code=400, detail="business_number is required")
    claims = oauth_auth.get("claims") or {}
    _validate_token_business_match(claims, business_number)
    return await chat(request, oauth_auth=oauth_auth)


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


@app.post("/twilio/twiml")
async def twilio_twiml(request: Request):
    """TwiML webhook for inbound Twilio voice calls.

    Twilio calls this endpoint when a call comes in. Returns TwiML that
    connects the call to the /twilio WebSocket for media streaming.
    """
    body = await request.body()
    if not verify_twilio_http_signature(request, body):
        verification_enabled = config.settings.twilio_signature_verification_enabled
        if verification_enabled:
            logger.error("Rejecting /twilio/twiml request: invalid Twilio signature")
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
        logger.warning("Allowing /twilio/twiml request despite failed signature verification (non-production)")

    forwarded_proto = request.headers.get("X-Forwarded-Proto", "https")
    forwarded_host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", ""))
    ws_scheme = "wss" if forwarded_proto == "https" else "ws"
    stream_url = f"{ws_scheme}://{forwarded_host}/twilio"

    logger.info("twilio_twiml: proto=%s host=%s stream_url=%s", forwarded_proto, forwarded_host, stream_url)

    # Parse Twilio POST body for call metadata
    form = await request.form()
    to_number = form.get("To", "")
    from_number = form.get("From", "")
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    env = config.settings.environment
    call_type = "DEV" if env == "development" else ("STAGING" if env == "staging" else "PROD")

    logger.info(
        "twilio_twiml: inbound call — from=%s to=%s sid=%s status=%s env=%s call_type=%s",
        from_number, to_number, call_sid, call_status, env, call_type,
    )

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}">
      <Parameter name="Called" value="{to_number}"/>
      <Parameter name="Caller" value="{from_number}"/>
      <Parameter name="CallSid" value="{call_sid}"/>
      <Parameter name="CallType" value="{call_type}"/>
      <Parameter name="Stage" value="CustomerQuery"/>
      <Parameter name="Service" value="Groomers"/>
    </Stream>
  </Connect>
</Response>"""

    logger.info("twilio_twiml: returning TwiML:\n%s", twiml)
    return Response(content=twiml, media_type="application/xml")


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
            business_context = await resolve_context_for_request(
                stripped_business_number,
                caller_number=stripped_customer_phone,
            )
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

    # Resolve provider from business context for provider-specific tools and prompts
    provider = (business_context.get("provider") or "square").lower()
    logger.info("Twilio chat provider resolved: %s", provider)
    provider_tools = get_tools_for_provider(provider)
    provider_prompt = get_chat_prompt_for_provider(provider)

    system_prompt = payload.get("system_prompt") or provider_prompt or ""
    model_id = payload.get("model_id") or config.settings.bedrock_model_id
    max_tokens = payload.get("max_tokens") or config.settings.bedrock_max_tokens
    temperature = payload.get("temperature") or config.settings.bedrock_temperature
    try:
        max_tokens = int(max_tokens)
        temperature = float(temperature)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid max_tokens or temperature.")

    logger.info("Invoking Strands Agent for Twilio chat (model=%s provider=%s tools=%d message_chars=%d max_tokens=%d)",
                model_id, provider, len(provider_tools), len(message), max_tokens)
    agent_start = time.monotonic()
    try:
        # Create Bedrock model with Strands
        bedrock_model = BedrockModel(
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            region_name=config.settings.aws_region,
        )

        # Create agent with provider-specific system prompt and tools
        # Pass business context via state so tools receive it deterministically
        # Add current local time to context for relative date inference
        business_context["current_local_time"] = get_localized_datetime_from_context(business_context)
        # Convert to JSON-serializable format (Square SDK objects aren't serializable)
        serializable_context = _make_json_serializable(business_context)
        normalized_phone = normalize_phone_number(stripped_customer_phone) if stripped_customer_phone else None
        resolved_session_id = session_id or f"chat:{stripped_business_number}:{normalized_phone or uuid.uuid4().hex}"
        _chat_message_counts[resolved_session_id] = _chat_message_counts.get(resolved_session_id, 0) + 1
        emit_user_message_count("twilio_chat", resolved_session_id, _chat_message_counts[resolved_session_id])
        session_manager = _get_chat_session_manager(resolved_session_id)
        serializable_context = to_snake_case(serializable_context)
        initial_state = {"business_context": serializable_context, **serializable_context}
        agent = Agent(
            model=bedrock_model,
            system_prompt=system_prompt if system_prompt else None,
            tools=provider_tools,
            state=initial_state,
            session_manager=session_manager,
        )
        _seed_agent_state(agent, serializable_context)

        # Invoke agent in executor to avoid blocking async event loop
        def invoke_agent(a, msg):
            return a(msg)

        response = None
        agent_error_type = None
        agent_success = False
        last_exc = None
        tool_result_exceeded_after_retry = False
        for attempt in range(2):
            try:
                response = await asyncio.to_thread(invoke_agent, agent, message)
                agent_success = True
                break
            except Exception as exc:
                last_exc = exc
                agent_error_type = type(exc).__name__
                error_msg = str(exc).lower()
                is_tool_result_exceeds = (
                    ("validationexception" in error_msg or "conversestream" in error_msg)
                    and "toolresult" in error_msg
                    and "tooluse" in error_msg
                    and "exceeds" in error_msg
                )
                if is_tool_result_exceeds and attempt == 0:
                    logger.warning(
                        "Strands session history has toolResult/toolUse mismatch; clearing session and retrying once: session_id=%s",
                        resolved_session_id,
                    )
                    try:
                        session_manager.delete_session(resolved_session_id)
                    except Exception as e:
                        logger.debug("Session delete failed (may not exist): %s", e)
                    retry_session_id = f"{resolved_session_id}:retry-{uuid.uuid4().hex[:8]}"
                    session_manager = _get_chat_session_manager(retry_session_id)
                    initial_state = {"business_context": serializable_context, **serializable_context}
                    agent = Agent(
                        model=bedrock_model,
                        system_prompt=system_prompt if system_prompt else None,
                        tools=provider_tools,
                        state=initial_state,
                        session_manager=session_manager,
                    )
                    _seed_agent_state(agent, serializable_context)
                    continue
                if is_tool_result_exceeds and attempt == 1:
                    tool_result_exceeded_after_retry = True
                    break
                raise

        if response is not None:
            if isinstance(response, str):
                reply = response
            elif hasattr(response, "content"):
                reply = response.content
            elif isinstance(response, dict):
                reply = response.get("content") or response.get("reply") or str(response)
            else:
                reply = str(response)
        elif tool_result_exceeded_after_retry:
            reply = "Sorry, the conversation state was inconsistent. Please start a new message thread."
        else:
            reply = "Sorry, something went wrong. Please try again later."

        emit_agent_metrics(
            endpoint="twilio_chat",
            provider=provider,
            duration_ms=(time.monotonic() - agent_start) * 1000,
            success=agent_success,
            error_type=agent_error_type if not agent_success else None,
        )
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
            emit_max_tokens_reached("twilio_chat", provider)
            emit_agent_metrics(
                endpoint="twilio_chat",
                provider=provider,
                duration_ms=(time.monotonic() - agent_start) * 1000,
                success=False,
                error_type="MaxTokensReached",
            )
            reply = "Sorry, I couldn't complete my response. Please try a simpler question."
        else:
            logger.error("Strands Agent invoke failed: %s", exc, exc_info=True)
            emit_agent_metrics(
                endpoint="twilio_chat",
                provider=provider,
                duration_ms=(time.monotonic() - agent_start) * 1000,
                success=False,
                error_type=type(exc).__name__,
            )
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
        emit_message_delivery("sms", True)

    except Exception as sms_exc:
        logger.error("Failed to send SMS via Twilio: %s", sms_exc, exc_info=True)
        emit_message_delivery("sms", False)
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


def _increment_websocket_count(client_ip: str, endpoint: str) -> None:
    """Increment WebSocket connection count for IP."""
    _websocket_connections[client_ip] = _websocket_connections.get(client_ip, 0) + 1
    total = sum(_websocket_connections.values())
    emit_active_connections(endpoint, total)


def _decrement_websocket_count(client_ip: str, endpoint: str) -> None:
    """Decrement WebSocket connection count for IP."""
    current = _websocket_connections.get(client_ip, 0)
    if current > 0:
        _websocket_connections[client_ip] = current - 1
    total = sum(_websocket_connections.values())
    emit_active_connections(endpoint, total)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Deepgram Voice Agents (browser clients)

    Starts Deepgram session immediately on connection for bidirectional audio streaming.
    """
    logger.info("websocket_endpoint called")
    is_valid_oauth, _, _ = _validate_websocket_oauth(websocket.query_params, websocket.headers)
    if not is_valid_oauth:
        logger.warning("Rejecting /ws connection due to OAuth validation failure")
        await websocket.close(code=1008, reason="OAuth validation failed")
        return

    # Check WebSocket connection rate limit
    client_ip = _get_client_ip(websocket)
    if not _check_websocket_rate_limit(client_ip):
        logger.warning("WebSocket connection limit exceeded for IP: %s", client_ip)
        await websocket.close(code=1008, reason="Connection limit exceeded")
        return

    _increment_websocket_count(client_ip, "ws")
    await websocket.accept()
    connection_id = f"ws-{uuid.uuid4().hex[:12]}"
    logger.info(f"WebSocket connection established: {connection_id}")
    connection_start = time.monotonic()

    business_number = websocket.query_params.get("businessNumber")
    customer_phone = websocket.query_params.get("customerPhone")
    if business_number:
        logger.info("Browser client provided businessNumber=%s for %s", business_number, connection_id)

        # If /voice/oauth/connect already resolved the context, use it directly via token
        ctx_token = websocket.query_params.get("ctxToken")
        pre_resolved = _pop_pre_resolved(ctx_token) if ctx_token else None
        if pre_resolved:
            pre_resolved_snake = to_snake_case(pre_resolved)
            if customer_phone:
                pre_resolved_snake["caller"] = customer_phone
            set_connection_context_by_id(connection_id, pre_resolved_snake)
            logger.info("Using pre-resolved business context for %s via ctxToken (skipping re-resolution)", connection_id)

        if not pre_resolved:
            set_connection_context_by_id(
                connection_id,
                {"success": False, "pending": True, "businessNumber": business_number, "caller": customer_phone},
            )
            await _resolve_and_set_context(
                connection_id,
                business_number,
                extra_context={"caller": customer_phone} if customer_phone else None,
            )

        # Apply inline voice config override (for testing without saved config)
        voice_config_override_b64 = websocket.query_params.get("voiceConfigOverride")
        if voice_config_override_b64:
            try:
                import json as _json
                _b64_clean = voice_config_override_b64.rstrip("=")
                _b64_padding = (-len(_b64_clean)) % 4
                override_raw = _json.loads(
                    base64.urlsafe_b64decode(_b64_clean + "=" * _b64_padding)
                )
                override_snake = to_snake_case(override_raw)
                existing_ctx = get_connection_context_by_id(connection_id)
                existing_voice = existing_ctx.get("voice_config") or {}
                # Override wins for voice keys; saved config fills missing keys (e.g. forwarding_number)
                merged_voice = {**existing_voice, **override_snake}
                update_connection_context_by_id(connection_id, {"voice_config": merged_voice})
                logger.info(
                    "Applied voice config override for %s: override_keys=%s -> provider=%s voice_id=%s",
                    connection_id,
                    list(override_snake.keys()),
                    merged_voice.get("voice_provider"),
                    merged_voice.get("voice_id"),
                )
            except Exception as exc:
                logger.warning("Failed to apply voiceConfigOverride for %s: %s", connection_id, exc)

    else:
        logger.info("No businessNumber provided for %s", connection_id)
    
    session = None
    
    async def send_to_client(data: dict):
        """Helper function to send data to client"""
        try:
            if data.get("type") == "disconnect":
                # Send disconnect JSON first so the client can finish playing farewell TTS.
                # Schedule a forced close as a fallback in case the client doesn't close itself.
                await websocket.send_json(data)
                async def _force_close_after_grace():
                    await asyncio.sleep(8)
                    try:
                        await websocket.close(code=1000, reason=data.get("reason") or "end_call")
                    except Exception:
                        pass
                asyncio.create_task(_force_close_after_grace())
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
        # Collect session recording data BEFORE closing the session (session is removed on close)
        recording_data = deepgram_manager.get_session_recording_data(connection_id) if session else {}
        # Clean up session
        if session:
            await deepgram_manager.close_session(connection_id)
        duration_ms = (time.monotonic() - connection_start) * 1000
        emit_call_duration("ws", duration_ms)
        # Persist call record before clearing context
        if config.settings.call_record_table:
            ctx = get_connection_context_by_id(connection_id)
            outcome = (
                "forwarded" if ctx.get("callForwarded")
                else "no_context" if not ctx.get("success")
                else "completed"
            )
            # Upload transcript and recording to S3 if bucket is configured
            transcript_s3_key = None
            recording_s3_key = None
            if config.settings.recordings_bucket and recording_data:
                transcript_s3_key = await upload_transcript(
                    call_id=connection_id,
                    transcript_turns=recording_data.get("transcript_turns", []),
                    bucket_name=config.settings.recordings_bucket,
                    aws_region=config.settings.aws_region,
                    key_prefix=config.settings.recordings_key_prefix,
                    metadata={
                        "endpoint": "ws",
                        "businessNumber": ctx.get("business_number") or ctx.get("businessNumber") or "",
                    },
                )
                audio_chunks = recording_data.get("audio_chunks", [])
                if audio_chunks:
                    recording_s3_key = await upload_recording(
                        call_id=connection_id,
                        audio_chunks=audio_chunks,
                        sample_rate=config.settings.deepgram_output_sample_rate or 24000,
                        is_mulaw=False,
                        bucket_name=config.settings.recordings_bucket,
                        aws_region=config.settings.aws_region,
                        key_prefix=config.settings.recordings_key_prefix,
                        metadata={
                            "endpoint": "ws",
                            "businessNumber": ctx.get("business_number") or ctx.get("businessNumber") or "",
                        },
                    )
            # Upsert VoiceCustomer record if a customer was identified during the call
            customer_id = None
            customer_obj = ctx.get("customer")
            business_number = ctx.get("business_number") or ctx.get("businessNumber")
            booking_created = bool(ctx.get("bookingCreated") or ctx.get("booking_created"))
            if customer_obj and config.settings.voice_customer_table:
                from utils.customers import _extract_customer_fields
                fields = _extract_customer_fields(customer_obj)
                customer_id = await upsert_voice_customer(
                    customer=customer_obj,
                    provider=ctx.get("provider") or "unknown",
                    business_number=business_number or "",
                    caller_number=ctx.get("caller"),
                    booking_created=booking_created,
                    table_name=config.settings.voice_customer_table,
                    aws_region=config.settings.aws_region,
                )
            else:
                fields = {}
            await write_call_record(
                connection_id=connection_id,
                endpoint="ws",
                duration_ms=duration_ms,
                table_name=config.settings.call_record_table,
                aws_region=config.settings.aws_region,
                business_number=business_number,
                caller_number=ctx.get("caller"),
                call_sid=ctx.get("callSid"),
                provider=ctx.get("provider"),
                merchant_id=ctx.get("merchant_id"),
                location_id=ctx.get("location_id"),
                setmore_account_id=ctx.get("setmore_account_id"),
                outcome=outcome,
                user_message_count=int(ctx.get("userMessageCount") or ctx.get("user_message_count") or 0),
                tool_call_count=int(ctx.get("toolCallCount") or ctx.get("tool_call_count") or 0),
                tool_call_error_count=int(ctx.get("toolCallErrorCount") or ctx.get("tool_call_error_count") or 0),
                booking_created=booking_created,
                customer_found=bool(ctx.get("customerFound") or ctx.get("customer_found")),
                sms_booking_link_sent=bool(ctx.get("smsBookingLinkSent") or ctx.get("sms_booking_link_sent")),
                max_tokens_reached=bool(ctx.get("maxTokensReached") or ctx.get("max_tokens_reached")),
                forwarded_call=bool(ctx.get("callForwarded") or ctx.get("call_forwarded")),
                sms_sent_count=int(ctx.get("smsSentCount") or ctx.get("sms_sent_count") or 0),
                whatsapp_sent_count=int(ctx.get("whatsappSentCount") or ctx.get("whatsapp_sent_count") or 0),
                transcript_s3_key=transcript_s3_key,
                recording_s3_key=recording_s3_key,
                customer_id=customer_id,
                customer_first_name=fields.get("first_name"),
                customer_last_name=fields.get("last_name"),
            )
        clear_connection_context_by_id(connection_id)
        _decrement_websocket_count(client_ip, "ws")
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

    _increment_websocket_count(client_ip, "twilio_ws")
    await websocket.accept()
    connection_id = f"twilio-{uuid.uuid4().hex[:12]}"
    logger.info(f"Twilio WebSocket connection established: {connection_id}")
    connection_start = time.monotonic()
    
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
            # Deepgram sends mulaw audio as base64, decode and send to Twilio
            raw_mulaw = base64.b64decode(data["audio"])
            if not stream_sid_ref["value"]:
                return
            # Send outbound audio in fixed 20ms (160-byte) frames to match Twilio's
            # expected cadence and avoid clicks at chunk boundaries (Twilio uses 20ms frames).
            TWILIO_FRAME_BYTES = 160
            offset = 0
            while offset < len(raw_mulaw):
                frame = raw_mulaw[offset : offset + TWILIO_FRAME_BYTES]
                offset += len(frame)
                if len(frame) < TWILIO_FRAME_BYTES:
                    # Pad last partial frame with silence (0xff = mulaw silence) to avoid click
                    frame = frame + bytes([0xFF] * (TWILIO_FRAME_BYTES - len(frame)))
                media_message = {
                    "event": "media",
                    "streamSid": stream_sid_ref["value"],
                    "media": {"payload": base64.b64encode(frame).decode("ascii")},
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
            context = get_connection_context_by_id(connection_id)
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
        try:
            await asyncio.wait_for(streamsid_queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("deepgram_receiver: timed out waiting for streamSid for %s", connection_id)
            return
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
                    parsed = _parse_twilio_start_event(data)
                    sid = parsed["stream_sid"]
                    to_number = parsed["to_number"]
                    from_number = parsed["from_number"]
                    call_sid = parsed["call_sid"]
                    account_sid = parsed["account_sid"]
                    service_name = parsed["service_name"]
                    custom_params = parsed["custom_params"]
                    # Log full start payload at INFO so AWS/CloudWatch logs show exact Twilio payload for debugging
                    logger.info(
                        "Twilio start event full payload (connectionId=%s): %s",
                        connection_id,
                        json.dumps(data, default=str),
                    )
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
                    if to_number is None:
                        start_keys = list((data.get("start") or {}).keys())
                        logger.warning(
                            "Twilio start: no To/Called in payload (business number unknown). "
                            "Pass <Parameter name=\"To\" value=\"+1...\"/> and <Parameter name=\"From\" value=\"+1...\"/> in TwiML <Stream>. "
                            "Payload top-level keys=%s start keys=%s",
                            list(data.keys()),
                            start_keys,
                        )
                    normalized_number = normalize_phone_number(to_number) if to_number else None
                    if to_number and not normalized_number:
                        logger.warning(
                            "Twilio start: to_number not valid for normalization (use E.164 e.g. +1XXXXXXXXXX): %r",
                            to_number,
                        )
                    if normalized_number:
                        extra_context = {
                            "called": to_number,
                            "caller": from_number,
                            "service": service_name,
                            "callSid": call_sid,
                            "accountSid": account_sid,
                        }
                        set_connection_context_by_id(
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
                        logger.info(
                            "Twilio business context resolve requested for connectionId=%s businessNumber=%s",
                            connection_id,
                            normalized_number,
                        )
                    else:
                        logger.info("No Twilio business number available for %s", connection_id)
                        set_connection_context_by_id(
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

                            async def _twilio_fatal_error_fallback(error_msg: str) -> None:
                                logger.error("Fatal Deepgram error on Twilio call %s — playing fallback message", connection_id)
                                await _say_and_end_twilio_call(connection_id, account_sid, call_sid)

                            session.on_fatal_error = _twilio_fatal_error_fallback
                            session_ready.set()
                            logger.info(f"Deepgram session created and callback set for {connection_id}")
                        except Exception as e:
                            logger.error(f"Failed to create Deepgram session: {e}", exc_info=True)
                            await _say_and_end_twilio_call(connection_id, account_sid, call_sid)
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
        audio_queue.put_nowait(None)
    
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
                if mulaw_chunk is None:
                    logger.info(f"deepgram_sender: received stop sentinel for {connection_id}")
                    break
                if session_ref["value"] and session_ref["value"].is_active:
                    # Send raw mulaw bytes directly with force_send=True (matches sts-twilio immediate sending)
                    await deepgram_manager.send_audio(connection_id, mulaw_chunk, force_send=True)
                    logger.debug(f"Sent {len(mulaw_chunk)} bytes of mulaw audio to Deepgram for {connection_id}")
                else:
                    logger.warning(f"Session not active, dropping audio chunk for {connection_id}")
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
        # Collect session recording data BEFORE closing the session
        recording_data = deepgram_manager.get_session_recording_data(connection_id) if session_ref["value"] else {}
        # Clean up session
        if session_ref["value"]:
            await deepgram_manager.close_session(connection_id)
        duration_ms = (time.monotonic() - connection_start) * 1000
        emit_call_duration("twilio_ws", duration_ms)
        # Persist call record before clearing context
        if config.settings.call_record_table:
            ctx = get_connection_context_by_id(connection_id)
            outcome = (
                "forwarded" if ctx.get("callForwarded")
                else "no_context" if not ctx.get("success")
                else "completed"
            )
            # Upload transcript and recording to S3 if bucket is configured
            transcript_s3_key = None
            recording_s3_key = None
            if config.settings.recordings_bucket and recording_data:
                transcript_s3_key = await upload_transcript(
                    call_id=connection_id,
                    transcript_turns=recording_data.get("transcript_turns", []),
                    bucket_name=config.settings.recordings_bucket,
                    aws_region=config.settings.aws_region,
                    key_prefix=config.settings.recordings_key_prefix,
                    metadata={
                        "endpoint": "twilio_ws",
                        "businessNumber": ctx.get("business_number") or ctx.get("businessNumber") or "",
                    },
                )
                audio_chunks = recording_data.get("audio_chunks", [])
                if audio_chunks:
                    recording_s3_key = await upload_recording(
                        call_id=connection_id,
                        audio_chunks=audio_chunks,
                        sample_rate=8000,
                        is_mulaw=True,
                        bucket_name=config.settings.recordings_bucket,
                        aws_region=config.settings.aws_region,
                        key_prefix=config.settings.recordings_key_prefix,
                        metadata={
                            "endpoint": "twilio_ws",
                            "businessNumber": ctx.get("business_number") or ctx.get("businessNumber") or "",
                        },
                    )
            customer_id = None
            customer_obj = ctx.get("customer")
            business_number = ctx.get("business_number") or ctx.get("businessNumber")
            booking_created = bool(ctx.get("bookingCreated") or ctx.get("booking_created"))
            if customer_obj and config.settings.voice_customer_table:
                from utils.customers import _extract_customer_fields
                fields = _extract_customer_fields(customer_obj)
                customer_id = await upsert_voice_customer(
                    customer=customer_obj,
                    provider=ctx.get("provider") or "unknown",
                    business_number=business_number or "",
                    caller_number=ctx.get("caller"),
                    booking_created=booking_created,
                    table_name=config.settings.voice_customer_table,
                    aws_region=config.settings.aws_region,
                )
            else:
                fields = {}
            await write_call_record(
                connection_id=connection_id,
                endpoint="twilio_ws",
                duration_ms=duration_ms,
                table_name=config.settings.call_record_table,
                aws_region=config.settings.aws_region,
                business_number=business_number,
                caller_number=ctx.get("caller"),
                call_sid=ctx.get("callSid"),
                provider=ctx.get("provider"),
                merchant_id=ctx.get("merchant_id"),
                location_id=ctx.get("location_id"),
                setmore_account_id=ctx.get("setmore_account_id"),
                outcome=outcome,
                user_message_count=int(ctx.get("userMessageCount") or ctx.get("user_message_count") or 0),
                tool_call_count=int(ctx.get("toolCallCount") or ctx.get("tool_call_count") or 0),
                tool_call_error_count=int(ctx.get("toolCallErrorCount") or ctx.get("tool_call_error_count") or 0),
                booking_created=booking_created,
                customer_found=bool(ctx.get("customerFound") or ctx.get("customer_found")),
                sms_booking_link_sent=bool(ctx.get("smsBookingLinkSent") or ctx.get("sms_booking_link_sent")),
                max_tokens_reached=bool(ctx.get("maxTokensReached") or ctx.get("max_tokens_reached")),
                forwarded_call=bool(ctx.get("callForwarded") or ctx.get("call_forwarded")),
                sms_sent_count=int(ctx.get("smsSentCount") or ctx.get("sms_sent_count") or 0),
                whatsapp_sent_count=int(ctx.get("whatsappSentCount") or ctx.get("whatsapp_sent_count") or 0),
                transcript_s3_key=transcript_s3_key,
                recording_s3_key=recording_s3_key,
                customer_id=customer_id,
                customer_first_name=fields.get("first_name"),
                customer_last_name=fields.get("last_name"),
            )
        clear_connection_context_by_id(connection_id)
        _decrement_websocket_count(client_ip, "twilio_ws")
        logger.info("Cleaned up Twilio connection: %s", connection_id)


if __name__ == "__main__":
    logger.info("🎙️ Starting VakDeepGram server...")
    logger.info(f"   Listening: {config.settings.deepgram_listening_model} (v{config.settings.deepgram_listening_version})")
    logger.info(f"   Thinking: {config.settings.deepgram_thinking_provider}/{config.settings.deepgram_thinking_model}")
    if config.settings.deepgram_speaking_provider == "eleven_labs":
        logger.info(f"   Speaking: ElevenLabs ({config.settings.deepgram_speaking_model_id}, voice: {config.settings.deepgram_speaking_voice_id})")
    else:
        logger.info(f"   Speaking: Deepgram ({config.settings.deepgram_speaking_model})")
    
    # Pass app as import string when using reload or multiple workers (uvicorn requirement)
    use_import_string = config.settings.reload or config.settings.workers != 1
    app_ref: str | FastAPI = "vakdeepgram.main:app" if use_import_string else app
    uvicorn.run(
        app_ref,
        workers=config.settings.workers,
        host=config.settings.host,
        port=config.settings.port,
        log_level=config.settings.log_level,
        reload=config.settings.reload,
    )

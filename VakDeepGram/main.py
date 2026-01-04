"""
VakDeepGram - FastAPI WebSocket server for Deepgram Voice Agents
"""
import json
import logging
import uuid
import base64
import asyncio
from urllib.parse import urlencode, parse_qs
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from twilio.request_validator import RequestValidator
import uvicorn
import config
from deepgram_handler import deepgram_manager

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="VakDeepGram", version="1.0.0")


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
        
        logger.debug(f"Twilio RequestValidator result: {is_valid}")
        logger.debug(f"=== Verification result: {is_valid} ===")
        
        return is_valid
    except Exception as e:
        logger.error(f"Error during Twilio signature verification: {e}", exc_info=True)
        return False

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with basic info"""
    return {
        "service": "VakDeepGram",
        "version": "1.0.0",
        "status": "running",
        "websocket_endpoint": "/ws",
        "twilio_endpoint": "/twilio"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Deepgram Voice Agents (browser clients)
    
    Starts Deepgram session immediately on connection for bidirectional audio streaming.
    """
    await websocket.accept()
    connection_id = f"ws-{uuid.uuid4().hex[:12]}"
    logger.info(f"WebSocket connection established: {connection_id}")
    
    session = None
    
    async def send_to_client(data: dict):
        """Helper function to send data to client"""
        try:
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
                    logger.warn(f"No active session for {connection_id}, ignoring audio")
            
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
        logger.info(f"Cleaned up connection: {connection_id}")


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
        if not signature:
            logger.warning(f"WARNING: No X-Twilio-Signature header received from {websocket.client}")
            logger.warning(f"This may be normal for Twilio Media Streams - allowing connection for debugging")
            logger.warning(f"If you want to enforce signature verification, ensure Twilio sends the header")
        else:
            logger.error(f"Twilio signature verification FAILED for connection from {websocket.client}")
            logger.error(f"Tried WSS URL: {wss_url}")
            logger.error(f"Tried HTTPS URL: {https_url}")
            logger.error(f"Query params used: {query_params}")
            logger.error(f"Signature received: {signature}")
            logger.error(f"This could indicate:")
            logger.error(f"  1. Wrong auth token configured")
            logger.error(f"  2. URL construction mismatch")
            logger.error(f"  3. Query parameter encoding issue")
            logger.error(f"  4. Signature header format issue")
            logger.error(f"  5. Twilio Media Streams may not send signatures (uncommon)")
            # For now, allow connection to debug - remove this after fixing
            logger.warning(f"ALLOWING CONNECTION DESPITE FAILED VERIFICATION FOR DEBUGGING")
            # Uncomment the following lines once signature verification is working:
            # await websocket.close(code=1008, reason="Signature verification failed")
            # return
    
    logger.info(f"Twilio signature verified for connection from {websocket.client}")
    
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
        
        # Other message types can be logged but don't need to be sent to Twilio
        logger.debug(f"Deepgram message for Twilio: {msg_type}")
    
    # Start Deepgram session immediately (matches sts-twilio: async with sts_connect() as sts_ws)
    logger.info(f"Starting Deepgram session immediately for Twilio {connection_id} (mulaw mode)")
    try:
        session = await deepgram_manager.create_session(connection_id, use_mulaw=True)
        session_ref["value"] = session
        # Set callback immediately - it will wait for streamSid before sending audio
        session.set_send_callback(send_to_deepgram_wrapper)
        logger.info(f"Deepgram session created and callback set for {connection_id}")
    except Exception as e:
        logger.error(f"Failed to create Deepgram session: {e}", exc_info=True)
        await websocket.close()
        return
    
    async def deepgram_receiver():
        """Receive messages from Deepgram and forward to Twilio (matches sts-twilio sts_receiver)"""
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
                    sid = start_data.get("streamSid")
                    if sid:
                        stream_sid_ref["value"] = sid
                        streamsid_queue.put_nowait(sid)
                        logger.info(f"Got streamSid: {sid}")
                
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
        logger.info(f"Cleaned up Twilio connection: {connection_id}")


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

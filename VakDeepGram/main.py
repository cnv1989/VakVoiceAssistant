"""
VakDeepGram - FastAPI WebSocket server for Deepgram Voice Agents
"""
import json
import logging
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
        "websocket_endpoint": "/ws"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Deepgram Voice Agents"""
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
                    
                    if action == "start-deepgram" or action == "start-recording":
                        logger.info(f"Starting Deepgram Voice Agent session for {connection_id}")
                        try:
                            session = await deepgram_manager.create_session(connection_id)
                            session.set_send_callback(send_to_client)
                            await send_to_client({"type": "recording-started"})
                        except Exception as e:
                            logger.error(f"Error creating Deepgram session: {e}", exc_info=True)
                            await send_to_client({
                                "type": "error",
                                "message": f"Failed to start Deepgram session: {str(e)}"
                            })
                    
                    elif action == "stop-deepgram" or action == "stop-recording":
                        logger.info(f"Stopping Deepgram session for {connection_id}")
                        if session:
                            await deepgram_manager.close_session(connection_id)
                        await send_to_client({"type": "recording-stopped"})
                    
                    elif action == "set-tts-engine":
                        # Ignore TTS engine selection - Deepgram Voice Agent handles TTS automatically
                        logger.debug(f"Ignoring set-tts-engine action (Deepgram handles TTS)")
                    
                    else:
                        logger.warn(f"Unsupported action: {action}")
                        await send_to_client({
                            "type": "error",
                            "message": f"Unsupported action: {action}"
                        })
                
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing JSON message: {e}")
                    await send_to_client({
                        "type": "error",
                        "message": "Invalid JSON format"
                    })
            
            # Handle binary messages (audio data)
            elif "bytes" in message:
                audio_data = message["bytes"]
                if session:
                    await deepgram_manager.send_audio(connection_id, audio_data)
                else:
                    logger.warn(f"No active session for {connection_id}, ignoring audio")
            
            # Handle other message types
            else:
                logger.debug(f"Received unknown message type: {list(message.keys())}")
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket handler for {connection_id}: {e}")
    finally:
        # Clean up session
        if session:
            await deepgram_manager.close_session(connection_id)
        logger.info(f"Cleaned up connection: {connection_id}")


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

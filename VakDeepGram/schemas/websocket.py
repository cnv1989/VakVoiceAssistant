"""
Pydantic schemas for WebSocket message validation.
"""
from typing import Optional, Literal, Union
from pydantic import BaseModel, Field


# Incoming message types (from client)

class WebSocketAction(BaseModel):
    """Action message from client."""
    action: Literal[
        "start-deepgram",
        "stop-deepgram",
        "start-recording",
        "stop-recording",
        "set-tts-engine",
    ]
    engine: Optional[str] = None  # For set-tts-engine action


class WebSocketIncomingMessage(BaseModel):
    """Generic incoming WebSocket message."""
    action: Optional[str] = None
    type: Optional[str] = None


# Outgoing message types (to client)

class TTSMessage(BaseModel):
    """TTS audio message to client."""
    type: Literal["tts"] = "tts"
    audio: str  # Base64-encoded audio data
    messageId: Optional[str] = None
    connectionId: str
    size: int
    encoding: Literal["linear16", "mulaw"]


class TranscriptMessage(BaseModel):
    """Transcript message to client."""
    type: Literal["transcript"] = "transcript"
    text: str
    role: Literal["user", "agent"]
    isPartial: bool = False
    messageId: Optional[str] = None
    connectionId: Optional[str] = None


class LLMTokenMessage(BaseModel):
    """LLM token stream message to client."""
    type: Literal["llm-token"] = "llm-token"
    token: str
    messageId: Optional[str] = None
    connectionId: Optional[str] = None


class LLMResponseMessage(BaseModel):
    """Complete LLM response message to client."""
    type: Literal["llm-response"] = "llm-response"
    text: str
    role: Literal["agent"] = "agent"
    messageId: Optional[str] = None
    connectionId: Optional[str] = None


class ErrorMessage(BaseModel):
    """Error message to client."""
    type: Literal["error"] = "error"
    message: str
    code: Optional[str] = None


class DisconnectMessage(BaseModel):
    """Disconnect message to client."""
    type: Literal["disconnect"] = "disconnect"
    reason: str = "end_call"
    connectionId: Optional[str] = None


class ReadyMessage(BaseModel):
    """Ready/status message to client."""
    type: Literal[
        "deepgram-ready",
        "recording-started",
        "recording-stopped",
        "settings-applied",
        "ready-to-listen",
        "processing-audio",
        "user-started-speaking",
        "agent-started-speaking",
        "deepgram-disconnected",
    ]
    connectionId: Optional[str] = None
    messageId: Optional[str] = None


class WelcomeMessage(BaseModel):
    """Welcome message to client."""
    type: Literal["welcome"] = "welcome"
    message: str
    connectionId: str


class MessageIdMessage(BaseModel):
    """Message ID notification to client."""
    type: Literal["message-id"] = "message-id"
    messageId: str
    connectionId: str


# Union type for all outgoing messages
OutgoingWebSocketMessage = Union[
    TTSMessage,
    TranscriptMessage,
    LLMTokenMessage,
    LLMResponseMessage,
    ErrorMessage,
    DisconnectMessage,
    ReadyMessage,
    WelcomeMessage,
    MessageIdMessage,
]

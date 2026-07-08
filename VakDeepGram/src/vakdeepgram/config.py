"""
Configuration settings for VakDeepGram service
"""
from enum import Enum
from pydantic_settings import BaseSettings
from typing import Optional


class Environment(str, Enum):
    """Application environment."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class SquareEnv(str, Enum):
    """Square API environment."""
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Business Profile
    # Controls the agent's persona: which industry-flavored system prompt it
    # uses (see providers/common/persona.py for presets and how to add more).
    business_name: Optional[str] = None
    business_vertical: str = "generic"
    # Full override for the "#Role" sentence, bypassing business_vertical presets.
    business_role_description: Optional[str] = None

    # Deepgram Configuration
    deepgram_api_key: str
    deepgram_project_id: Optional[str] = None
    # Optional: If not provided, agent will be created dynamically via API
    deepgram_agent_id: Optional[str] = None
    
    # Twilio Configuration
    twilio_account_sid: Optional[str] = None  # Required for sending SMS via Twilio API
    twilio_auth_token: Optional[str] = None  # Required for signature verification and sending SMS
    twilio_signature_verification_enabled: bool = True  # Set to False to skip verification
    twilio_from_number: Optional[str] = None  # Override from-number for outbound SMS (defaults to business number)
    twilio_business_number: Optional[str] = None  # Inbound business phone number (Twilio)
    twilio_whatsapp_number: Optional[str] = "+14155238886"  # WhatsApp-enabled number (Twilio sandbox for testing)

    # Application Environment
    environment: Environment = Environment.DEVELOPMENT

    # CORS Configuration
    cors_allowed_origins: list[str] = []  # Empty = allow all in dev, specific origins in prod

    # Rate Limiting
    rate_limit_per_minute: int = 100  # Requests per minute per IP
    max_websocket_connections_per_ip: int = 10

    # Authentication
    chat_api_key: Optional[str] = None  # API key for /chat endpoint (None = no auth in dev)
    oauth_jwks_url: Optional[str] = None
    oauth_issuer: Optional[str] = None
    oauth_audience: Optional[str] = None
    oauth_required_scope: Optional[str] = None
    oauth_allow_localhost_noauth: bool = False

    # Connection Store
    connection_ttl_seconds: int = 3600  # 1 hour TTL for connection contexts
    business_context_ttl_seconds: int = 300  # Cache TTL for business context lookups
    optimize_business_context: bool = True  # Reduce payload size for agents
    prefetch_availability_days: int = 14  # Days of availability to prefetch

    # Square Configuration
    # Table name defaults below match what VakInfra's CDK stack creates by
    # default (see VakInfra/lib/vak-app-stack.ts and VakInfra/README.md's
    # "Bringing your own tables" section for importing existing tables).
    square_environment: SquareEnv = SquareEnv.PRODUCTION
    square_account_table: str = "Vak-SquareAccount-production"
    business_number_table: str = "Vak-BusinessNumber-production"
    aws_region: str = "us-west-2"

    # Setmore Configuration
    setmore_account_table: str = "Vak-SetmoreAccount-production"
    setmore_api_base_url: str = "https://developer.setmore.com/api/v1"
    setmore_request_timeout_seconds: int = 30

    # Business Automations Configuration (for voice settings)
    business_automations_table: str = "Vak-BusinessAutomations-production"

    # Call Analytics - DynamoDB table for per-call records written by VakDeepGram
    call_record_table: str = "Vak-CallRecord-production"

    # Voice Customer tracking - DynamoDB table for caller profiles (upserted per call)
    voice_customer_table: str = "Vak-VoiceCustomer-production"
    user_booking_link_table: str = "Vak-UserBookingLink-production"

    # Session storage - S3 bucket for transcripts and recordings
    # When set, transcripts are uploaded to S3 at the end of every call.
    recordings_bucket: Optional[str] = None  # S3 bucket name (e.g. vak-artifacts-{account}-{region}-prod)
    recordings_key_prefix: str = "call-sessions"  # S3 key prefix inside the bucket

    bedrock_model_id: str = "us.anthropic.claude-opus-4-6-v1"
    bedrock_max_tokens: int = 8192  # Maximum tokens for Claude models - increased for tool usage
    bedrock_temperature: float = 0.4

    # Bedrock AgentCore Memory (optional – when set, chat uses AgentCore Memory for session storage)
    agentcore_memory_id: Optional[str] = None  # Bedrock AgentCore Memory ID (create in AWS console)
    agentcore_actor_id: str = "vak-chat-agent"  # Actor ID for the chat agent in memory

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    workers: int = 2
    reload: bool = False
    
    # Optional: Deepgram Agent Configuration
    deepgram_agent_language: str = "en"
    deepgram_listening_model: str = "flux-general-en"
    deepgram_listening_version: str = "v2"
    deepgram_thinking_provider: str = "google"
    deepgram_thinking_model: str = "gemini-2.0-flash"
    
    # Speaking/TTS Configuration
    # Set to "eleven_labs" to use ElevenLabs, "deepgram" (or empty) for Deepgram TTS
    deepgram_speaking_provider: str = "eleven_labs"
    deepgram_speaking_model: Optional[str] = None  # Used for Deepgram TTS
    deepgram_speaking_model_id: Optional[str] = "eleven_flash_v2_5"  # Used for ElevenLabs (low latency)
    deepgram_speaking_voice_id: Optional[str] = "cgSgspJ2msm6clMCkdW9"  # Used for ElevenLabs
    
    deepgram_input_sample_rate: int = 48000
    deepgram_output_sample_rate: int = 24000

    deepgram_sts_timeout_seconds: int = 300

    # Audio buffer and WebSocket settings
    max_audio_buffer_size: int = 100  # Max buffered audio chunks before dropping oldest
    websocket_ping_interval: int = 30  # Seconds between WebSocket pings

    booking_availability_window_minutes: int = 30
    booking_availability_window_by_service: dict[str, int] = {}

    # Default greeting used until business context resolves a business name.
    # The system prompts themselves live in providers/square/prompts.py and
    # providers/setmore/prompts.py, built from the business profile above via
    # providers/common/persona.py.
    deepgram_agent_greeting: Optional[str] = "Hi, how can I help you today?"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()


# ---------------------------------------------------------------------------
# Channel-specific prompt suffixes
# ---------------------------------------------------------------------------

SMS_PROMPT_SUFFIX = """
#SMS Format
This response will be sent as an SMS text message. Follow these rules:
-Use plain text only. Do NOT use markdown symbols like **, *, #, or _.
-Keep responses short and conversational — ideally under 300 characters.
-When listing services or options, use a simple numbered list (1. Item) with no bold or headers.
-If there are many items (e.g., full service menu), summarize the categories and offer to share details on request instead of listing everything.
-Never send a wall of text.
"""

WHATSAPP_PROMPT_SUFFIX = """
#WhatsApp Format
This response will be sent as a WhatsApp message. Follow these rules:
-You may use WhatsApp formatting: *bold*, _italic_, and numbered lists.
-Keep responses concise but informative — aim for under 500 characters.
-When listing services or options, use a clean numbered list.
-If there are many items, summarize categories and offer to share details.
-Be conversational and friendly.
"""

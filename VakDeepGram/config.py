"""
Configuration settings for VakDeepGram service
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Deepgram Configuration
    deepgram_api_key: str
    deepgram_project_id: Optional[str] = None
    # Optional: If not provided, agent will be created dynamically via API
    deepgram_agent_id: Optional[str] = None
    
    # Twilio Configuration
    twilio_auth_token: Optional[str] = "203d5f5968243a3b4bc09da73e7b998c"  # Required for signature verification
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "debug"
    workers: int = 2
    reload: bool = False
    
    # Optional: Deepgram Agent Configuration
    deepgram_agent_language: str = "en"
    deepgram_listening_model: str = "flux-general-en"
    deepgram_listening_version: str = "v2"
    deepgram_thinking_provider: str = "google"
    deepgram_thinking_model: str = "gemini-2.5-flash"
    
    # Speaking/TTS Configuration
    # Set to "eleven_labs" to use ElevenLabs, "deepgram" (or empty) for Deepgram TTS
    deepgram_speaking_provider: str = "eleven_labs"
    deepgram_speaking_model: Optional[str] = None  # Used for Deepgram TTS
    deepgram_speaking_model_id: Optional[str] = "eleven_multilingual_v2"  # Used for ElevenLabs
    deepgram_speaking_voice_id: Optional[str] = "cgSgspJ2msm6clMCkdW9"  # Used for ElevenLabs
    
    deepgram_input_sample_rate: int = 48000
    deepgram_output_sample_rate: int = 24000
    
    # Default prompt and greeting matching the provided configuration
    deepgram_agent_prompt: Optional[str] = """#Role
You are a barber shop assistant helping customers with questions about store hours, prices for different services, and scheduling appointments.

#General Guidelines
-Be warm, friendly, and professional.
-Speak clearly and naturally in a conversational tone.
-Keep responses concise—answer only what the customer is asking. Do not provide extra information unless specifically requested.
-If unclear, ask for clarification briefly.
-If asked about something outside your scope (store hours, prices, scheduling), politely redirect: "I can help you with our hours, prices, or booking an appointment."

#What You Help With
-Store hours: Provide current operating hours when asked.
-Prices: Share pricing for different services (haircuts, beard trims, etc.) when asked.
-Scheduling: Help customers book appointments when requested.

#Style
-Answer directly and naturally.
-Be concise—only provide the information requested.
-Use simple, clear language.
-Never interrupt the customer.

#Important
-Only answer what the customer asks for. Do not volunteer additional information.
-If you don't know specific details (like exact prices or hours), say so honestly.
-Keep the conversation natural and flowing.
"""
    
    deepgram_agent_greeting: Optional[str] = "Hi, Welcome to the Barber Shop. How can I help you?"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

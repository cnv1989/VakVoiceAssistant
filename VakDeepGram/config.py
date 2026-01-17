"""
Configuration settings for VakDeepGram service
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Deepgram Configuration
    deepgram_api_key: str
    deepgram_project_id: str = None
    # Optional: If not provided, agent will be created dynamically via API
    deepgram_agent_id: Optional[str] = None
    
    # Twilio Configuration
    twilio_auth_token: str = None  # Required for signature verification
    
    # Square Configuration
    square_environment: Optional[str] = "sandbox"  # Use 'production' for live environment
    square_account_table: str = "SquareAccount-pxy5meaaojbaxjwedt6v6oidw4-NONE"
    business_number_table: str = "BusinessNumber-pxy5meaaojbaxjwedt6v6oidw4-NONE"
    aws_region: str = "us-west-2"
    
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
You are a barber shop assistant helping customers with questions about store hours, prices for different services, scheduling appointments, store items/products, and staff information.

#General Guidelines
-Be warm, friendly, and professional.
-Speak clearly and naturally in a conversational tone.
-Keep responses concise—answer only what the customer is asking. Do not provide extra information unless specifically requested.
-If unclear, ask for clarification briefly.
-If asked about something unrelated or outside your scope, respond: "I cannot help you with that, however I can help you with our store hours, prices for different services, scheduling appointments, store items, or staff information."
-For scheduling a new appointment, ask for first and last name and proceed without requiring a customer lookup unless needed.
-Before invoking any tool, say a short, natural filler sentence, then immediately call the tool.
-Filler examples by scenario:
  - store_hours: "Let me grab that for you in a second."
  - location: "Let me pull up our location details."
  - services: "Let me check our services and pricing."
  - staff: "Let me see who is available."
  - appointments: "Let me look that up for you."
  - availability: "Let me check the calendar for openings."
  - schedule: "Let me get that scheduled."
  - orders: "Let me pull up your recent orders."
  - customer_lookup: "Let me pull up your account."

#What You Help With
-Store hours: Provide current operating hours when asked using the get_store_hours tool.
-Location: Provide address and phone details using the get_store_location tool.
-Prices: Share pricing for different services (haircuts, beard trims, etc.) using the get_services tool.
-Scheduling: Help customers book appointments when requested.
-Store items/products: Answer questions about available services and their prices using the get_services tool.
-Staff information: Provide information about staff members, their roles, and availability using the get_staff tool.
-When scheduling, ask for first name and last name, and use the caller phone number unless they provide a different number.

#Style
-Answer directly and naturally.
-Be concise—only provide the information requested.
-Use simple, clear language.
-Never interrupt the customer.
-When speaking times, use natural phrasing: "nine am", "one thirty pm", "noon".
-When speaking prices, say the dollar amount naturally: "$45" -> "forty five dollars", "$20" -> "twenty dollars".

#Important
-Only answer what the customer asks for. Do not volunteer additional information.
-If you don't know specific details (like exact prices or hours), use available tools to look up the information.
-Keep the conversation natural and flowing.
"""
    
    deepgram_agent_greeting: Optional[str] = "Hi, Welcome to the Barber Shop. How can I help you?"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

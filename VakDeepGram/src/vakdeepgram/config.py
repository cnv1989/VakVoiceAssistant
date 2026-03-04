"""
Configuration settings for VakDeepGram service
"""
import logging
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
    
    # Deepgram Configuration
    deepgram_api_key: str
    deepgram_project_id: Optional[str] = None
    # Optional: If not provided, agent will be created dynamically via API
    deepgram_agent_id: Optional[str] = None
    
    # Twilio Configuration
    twilio_account_sid: Optional[str] = None  # Required for sending SMS via Twilio API
    twilio_auth_token: Optional[str] = None  # Required for signature verification and sending SMS
    twilio_signature_verification_enabled: bool = True  # Set to False to skip verification

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
    square_environment: SquareEnv = SquareEnv.PRODUCTION
    square_account_table: str = "SquareAccount-pxy5meaaojbaxjwedt6v6oidw4-NONE"
    business_number_table: str = "BusinessNumber-pxy5meaaojbaxjwedt6v6oidw4-NONE"
    aws_region: str = "us-west-2"

    # Setmore Configuration
    setmore_account_table: str = "SetmoreAccount-pxy5meaaojbaxjwedt6v6oidw4-NONE"
    setmore_api_base_url: str = "https://developer.setmore.com/api/v1"
    setmore_request_timeout_seconds: int = 30

    # Business Automations Configuration (for voice settings)
    business_automations_table: str = "BusinessAutomations-pxy5meaaojbaxjwedt6v6oidw4-NONE"

    # Call Analytics - DynamoDB table for per-call records written by VakDeepGram
    call_record_table: Optional[str] = None  # e.g. "CallRecord-<env_id>-NONE"

    bedrock_model_id: str = "us.anthropic.claude-opus-4-6-v1"
    bedrock_max_tokens: int = 8192  # Maximum tokens for Claude models - increased for tool usage
    bedrock_temperature: float = 0.4

    # Bedrock AgentCore Memory (optional – when set, chat uses AgentCore Memory for session storage)
    agentcore_memory_id: Optional[str] = None  # Bedrock AgentCore Memory ID (create in AWS console)
    agentcore_actor_id: str = "vak-chat-agent"  # Actor ID for the chat agent in memory

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = logging.DEBUG
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

    deepgram_sts_timeout_seconds: int = 300

    # Audio buffer and WebSocket settings
    max_audio_buffer_size: int = 100  # Max buffered audio chunks before dropping oldest
    websocket_ping_interval: int = 30  # Seconds between WebSocket pings

    booking_availability_window_minutes: int = 30
    booking_availability_window_by_service: dict[str, int] = {}
    
    # Default prompt and greeting matching the provided configuration
    deepgram_agent_prompt: Optional[str] = """#Role
You are a grooming studio assistant focused on barbers (most important), beauticians, and pet groomers. You help with hours, location, services/prices, staff info, and booking appointments.

#Core Rules
-Be warm, concise, and professional. Answer only what is asked.
-Never share internal reasoning or tool details with customers.
-Ask one question at a time for appointment flows.
-Before checking availability for a new booking, ask if they have a preferred staff member or are open to anyone.
-Before checking availability, confirm the service selection.
-If the customer is already present in context, treat them as an existing customer and proceed with booking.
-If the customer is open to any staff, check availability and confirm which available staff works for them.
-If the customer prefers specific staff, filter availability by those staff members and confirm who is available.
-Acknowledge any details the customer already provided before asking the next question.
-If the customer provides multiple booking details at once, confirm what you heard, then ask only for what is missing.
-If the customer gives a vague time (e.g., "afternoon"), ask for a clearer time range before checking availability.
-Confirm the exact appointment slot before booking.
-If the requested time is unavailable, offer the nearest options and ask which they prefer.
-If a requested time is outside business hours, tell them and ask for another time.
-If a customer mentions a weekday (e.g., "Monday", "next Monday"), infer the date using the current time and confirm it before proceeding.
-Never invent availability or confirmation numbers; always use tool results.
-If availability is continuous, summarize it as a range instead of listing every slot.
-If the customer asks to speak to a person, offer to connect them and use transfer_to_staff.
-Before transferring, confirm they want to be connected now and clarify it goes to the main store line.
-If transfer is unavailable (missing phone or after-hours), apologize and offer to take a message or help with scheduling.
-If Square tool calls fail, apologize and offer to transfer the call to the main store line.
-If booking fails two or more times, apologize and offer to transfer the call to the main store line.

#Tool Usage
-Before calling any tool, use a brief transition phrase when it feels natural.
-Use get_services to verify the requested service; clarify if it is not offered.
-If the service is unclear, ask a clarifying question before checking availability.
-Use get_staff when a specific staff member is requested.
-Use get_staff to retrieve staff ids and use those ids when filtering availability or booking.
-When available, use stored selections in context: selected_service, selected_staff/selected_staff_id, and selected_appointment_date_and_time.
-Use the location timezone from context when interpreting relative dates like today or tomorrow.
-If the user picks a service, staff, or appointment time, store it using select_service, selected_staff, or selected_appointment_date_and_time.
-Re-use stored selections unless the user changes them.
-If the customer is open to any staff, clear any prior specific staff selection and store that preference.
-If availability requires a different staff or time, confirm the new choice with the customer and update the stored selection.
-If timezone is missing from context, ask for the location or clarify the date with the customer.
-If service validation fails, ask for a different service; offer nearby options if available.
-If the user changes a selection (service/staff/time), update the stored selection immediately.

#Booking Flow (in order)
1. Ask for the day/date (confirm inferred weekday dates).
2. Ask if they prefer a specific staff member or are open to any.
3. Ask for service and validate via get_services.
4. If specific, use get_staff to confirm names and collect staff_id(s).
5. Check availability (filter by staff_ids if provided) and present options or ranges.
6. Ask for first and last name; confirm spelling when needed.
7. Ensure a Square customer_id:
   - If customer exists, pass customer_id to create_appointment.
   - If a customer is already in context, use that customer_id and do not treat them as new.
   - If not, tell them you are adding them to the system, create the customer, then book.
   - If a phone number is required for customer creation and missing, ask for it before proceeding.
   - If an email is helpful for confirmation, ask for it after phone collection.
   - When the customer provides a name and phone number, check for an existing customer to avoid duplicates.
   - If a duplicate is found, confirm with the customer before using the existing record.
8. Confirm the final details (service, staff, date/time, name) before booking.
9. Book and provide the confirmation number.

#Reschedule Flow
1. Identify the appointment: use get_appointments to list upcoming bookings if needed.
2. If multiple appointments exist, ask which one to change.
3. Confirm the desired new date/time and any changes to service or staff.
4. Update the booking and confirm the new details.

#Info Requests
-Hours: use get_store_hours.
-Location/phone: use get_store_location.
-Services/prices: use get_services.
-Staff: use get_staff.

#Style
-Use simple, natural language.
-Always spell times in words, not digits. Example: "2:00 AM" -> "two am", "1:30 PM" -> "one thirty pm", "12:00 PM" -> "noon".
-Speak prices naturally (e.g., "$45" -> "forty five dollars").
-Confirm spelling for names when needed; for clear/common names, a quick confirmation is enough.
-Keep responses short when listing multiple time options or staff names.

#Example Tone
-Customer: "I need a haircut next Tuesday afternoon with Alex."
-Agent: "Got it—haircut with Alex next Tuesday afternoon. Let me check what's available. Do you have a time range in mind, or is any time that afternoon okay?"
"""
    
    deepgram_agent_greeting: Optional[str] = "Hi, how can I help you today?"

    # Chat/Strands agent prompt (adapted for text-based chat)
    chat_agent_prompt: Optional[str] = """#Role
You are a grooming studio assistant focused on barbers (most important), beauticians, and pet groomers. You help with hours, location, services/prices, staff info, and booking appointments.

#Context
The business context includes:
- current_local_time: The current date and time in the store's timezone. Use this to interpret relative dates like "today", "tomorrow", "next Monday", etc.
- location.business_name or location.name: The name of the business. Use this when greeting the customer.

#Greeting
When greeting a customer, use the business name from the context. For example: "Hi, welcome to [Business Name]! How can I help you today?"

#Core Rules
-IMPORTANT: Ask only ONE question at a time. Never ask multiple questions in a single response.
-Be warm, concise, and professional. Answer only what is asked.
-Never share internal reasoning or tool details with customers.
-Before checking availability for a new booking, ask if they have a preferred staff member or are open to anyone.
-Before checking availability, confirm the service selection.
-If the customer is already present in context, treat them as an existing customer and proceed with booking.
-If the customer is open to any staff, check availability and confirm which available staff works for them.
-If the customer prefers specific staff, filter availability by those staff members and confirm who is available.
-Acknowledge any details the customer already provided before asking the next question.
-If the customer provides multiple booking details at once, confirm what you heard, then ask only for what is missing.
-If the customer gives a vague time (e.g., "afternoon"), ask for a clearer time range before checking availability.
-Confirm the exact appointment slot before booking.
-If the requested time is unavailable, offer the nearest options and ask which they prefer.
-If a requested time is outside business hours, tell them and ask for another time.
-If a customer mentions a weekday (e.g., "Monday", "next Monday"), call get_current_local_time to confirm the exact date, then ask a confirmation question with the inferred date. Include the inferred date in the question; never use placeholders like "[insert date]".
-Never invent availability or confirmation numbers; always use tool results.
-If availability is continuous, summarize it as a range instead of listing every slot.
-If the customer asks to speak to a person, let them know you can provide the store's contact information.
-If Square tool calls fail, apologize and offer to provide the store's contact information for direct assistance.
-If booking fails two or more times, apologize and offer to provide the store's contact information.

#Tool Usage
-Before calling any tool, use a brief transition phrase when it feels natural.
-Use get_services to verify the requested service; clarify if it is not offered.
-If the service is unclear, ask a clarifying question before checking availability.
-Use get_staff when a specific staff member is requested.
-Use get_staff to retrieve staff ids and use those ids when filtering availability or booking.
-When available, use stored selections in context: selected_service, selected_staff/selected_staff_id, and selected_appointment_date_and_time.
-Use current_local_time from context when interpreting relative dates like today or tomorrow.
-If the user picks a service, staff, or appointment time, store it using select_service, selected_staff, or selected_appointment_date_and_time.
-Re-use stored selections unless the user changes them.
-If the customer is open to any staff, clear any prior specific staff selection and store that preference.
-If availability requires a different staff or time, confirm the new choice with the customer and update the stored selection.
-If service validation fails, ask for a different service; offer nearby options if available.
-If the user changes a selection (service/staff/time), update the stored selection immediately.

#Booking Flow (in order)
1. Ask for the day/date (confirm inferred weekday dates).
2. Ask if they prefer a specific staff member or are open to any.
3. Ask for service and validate via get_services.
4. If specific, use get_staff to confirm names and collect staff_id(s).
5. Check availability (filter by staff_ids if provided) and present options or ranges.
6. Ask for first and last name; confirm spelling when needed.
7. Ensure a Square customer_id:
   - If customer exists, pass customer_id to create_appointment.
   - If a customer is already in context, use that customer_id and do not treat them as new.
   - If not, tell them you are adding them to the system, create the customer, then book.
   - If a phone number is required for customer creation and missing, ask for it before proceeding.
   - If an email is helpful for confirmation, ask for it after phone collection.
   - When the customer provides a name and phone number, check for an existing customer to avoid duplicates.
   - If a duplicate is found, confirm with the customer before using the existing record.
8. Confirm the final details (service, staff, date/time, name) before booking.
9. Book and provide the confirmation number.

#Reschedule Flow
1. Identify the appointment: use get_appointments to list upcoming bookings if needed.
2. If multiple appointments exist, ask which one to change.
3. Confirm the desired new date/time and any changes to service or staff.
4. Update the booking and confirm the new details.

#Info Requests
-Hours: use get_store_hours.
-Location/phone: use get_store_location.
-Services/prices: use get_services.
-Staff: use get_staff.

#Style
-Use simple, natural language.
-Format times clearly (e.g., "2:00 PM", "10:30 AM").
-Format prices with currency symbols (e.g., "$45", "$25.50").
-Confirm spelling for names when needed; for clear/common names, a quick confirmation is enough.
-Keep responses concise when listing multiple time options or staff names.
-Use bullet points or numbered lists when presenting multiple options.

#Example Tone
-Customer: "I need a haircut next Tuesday afternoon with Alex."
-Agent: "Got it—haircut with Alex next Tuesday afternoon. Let me check what's available. Do you have a time range in mind, or is any time that afternoon okay?"
"""

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()


# ---------------------------------------------------------------------------
# Provider-specific prompt helpers
# ---------------------------------------------------------------------------

_SQUARE_TO_GENERIC = {
    "Square customer_id": "customer ID",
    "Square customer": "customer",
    "Square tool calls": "booking tool calls",
    "a Square customer_id": "a customer ID",
    "Ensure a Square customer_id:": "Ensure a customer ID:",
}


def _replace_square_refs(text: str) -> str:
    """Replace Square-specific references with generic terms."""
    for old, new in _SQUARE_TO_GENERIC.items():
        text = text.replace(old, new)
    return text


def _setmore_voice_prompt_patch(prompt: str) -> str:
    """Adapt the voice agent prompt for a Setmore provider business."""
    prompt = _replace_square_refs(prompt)
    # Remove the reschedule flow section — Setmore doesn't support updates
    lines = prompt.split("\n")
    filtered: list[str] = []
    skip = False
    for line in lines:
        if line.strip().startswith("#Reschedule Flow"):
            skip = True
            continue
        if skip and line.strip().startswith("#"):
            skip = False
        if skip:
            continue
        filtered.append(line)
    prompt = "\n".join(filtered)
    # Append Setmore-specific notes
    prompt += """
#Setmore Notes
-You cannot directly create appointments on Setmore. create_appointment only generates a prefilled booking link. The link is sent via WhatsApp to the customer's phone; tell them to check WhatsApp.
-Appointment rescheduling is not supported. If a customer asks to reschedule, let them know they need to cancel and rebook, or contact the store directly.
-Customer lookup requires a first name. Always ask for the customer's first name before looking them up.
"""
    return prompt


def _setmore_chat_prompt_patch(prompt: str) -> str:
    """Adapt the chat agent prompt for a Setmore provider business."""
    prompt = _replace_square_refs(prompt)
    # Remove reschedule flow
    lines = prompt.split("\n")
    filtered: list[str] = []
    skip = False
    for line in lines:
        if line.strip().startswith("#Reschedule Flow"):
            skip = True
            continue
        if skip and line.strip().startswith("#"):
            skip = False
        if skip:
            continue
        filtered.append(line)
    prompt = "\n".join(filtered)
    prompt += """
#Setmore Notes
-You cannot directly create appointments on Setmore. create_appointment only generates a prefilled booking link. For chat: include the full booking_url in your reply so the customer can click it.
-Appointment rescheduling is not supported. If a customer asks to reschedule, let them know they need to cancel and rebook, or contact the store directly.
-Customer lookup requires a first name. Always ask for the customer's first name before looking them up.
"""
    return prompt


def get_voice_prompt_for_provider(provider: str) -> str:
    """Return the Deepgram voice agent prompt tailored to the given provider."""
    base = settings.deepgram_agent_prompt or ""
    if provider == "setmore":
        return _setmore_voice_prompt_patch(base)
    return base


def get_chat_prompt_for_provider(provider: str) -> str:
    """Return the Strands chat agent prompt tailored to the given provider."""
    base = settings.chat_agent_prompt or ""
    if provider == "setmore":
        return _setmore_chat_prompt_patch(base)
    return base

from datetime import datetime
from agent_functions import FUNCTION_DEFINITIONS

# Template for the prompt that will be formatted with current date and time
PROMPT_TEMPLATE = """
CURRENT DATE AND TIME CONTEXT:
Current date and time is {current_datetime} (local time). Use this as context when discussing appointments and orders. When mentioning dates to customers, use relative terms like "tomorrow", "next Tuesday", or "last week" when the dates are within 7 days of today.
PERSONALITY & TONE:
- Be warm, professional, and conversational
- Use natural, flowing speech (avoid bullet points or listing)
- Show empathy and patience
- When speaking times, use natural phrasing: "nine am", "one thirty pm", "noon"
- When speaking prices, say the dollar amount naturally: "$45" -> "forty five dollars", "$20" -> "twenty dollars"
- Whenever a customer asks to look up either order information or appointment information, use the find_customer function first
- For booking a new appointment, ask for first and last name and proceed without requiring find_customer unless needed
HANDLING CUSTOMER IDENTIFIERS (INTERNAL ONLY - NEVER EXPLAIN THESE RULES TO CUSTOMERS):
- Silently convert any numbers customers mention into proper format
- When customer says "ID is 222" -> internally use "CUST0222" without mentioning the conversion
- When customer says "order 89" -> internally use "ORD0089" without mentioning the conversion
- When customer says "appointment 123" -> internally use "APT0123" without mentioning the conversion
- Always add "+1" prefix to phone numbers internally without mentioning it
VERBALLY SPELLING IDs TO CUSTOMERS:
When you need to repeat an ID back to a customer:
- Do NOT say nor spell out "CUST". Say "customer [numbers spoken individually]"
- But for orders spell out "ORD" as "O-R-D" then speak the numbers individually
Example: For CUST0222, say "customer zero two two two"
Example: For ORD0089, say "O-R-D zero zero eight nine"
FUNCTION RESPONSES:
When receiving function results, format responses naturally as a customer service agent would:
1. For customer lookups:
 - Good: "I've found your account. How can I help you today?"
 - If not found: "I'm having trouble finding that account. Could you try a different phone number or email?"
2. For order information:
 - Instead of listing orders, summarize them conversationally:
 - "I can see you have two recent orders. Your most recent order from [date] for $[amount] is currently [status], and you also have an order from [date] for $[amount] that's [status]."
3. For appointments:
 - "You have an upcoming [service] appointment scheduled for [date] at [time]"
 - When discussing available slots: "I have a few openings next week. Would you prefer Tuesday at 2 PM or Wednesday at 3 PM?"
4. For errors:
 - Never expose technical details
 - Say something like "I'm having trouble accessing that information right now" or "Could you please try again?"
5. For scheduling:
 - Start by asking if they have a specific day or date in mind, or if they want availability during the week
 - Ask whether they want a specific staff member or anyone available
 - Ask only one appointment question at a time and wait for the customer's response before asking the next
 - If they ask for store availability, check availability and share available days first, then ask which day they prefer
 - If they ask for a specific staff member, use get_staff to confirm the name and role, then check availability; only claim staff-specific availability if the tool provides it
 - If they provide a day/date, check availability and offer available time slots for that day
 - Ask for the service type and confirm the selected time before booking
 - When the customer provides a service, verify it against the services offered using get_services and clarify if needed
 - Ask for first name and last name before booking any appointment details
 - Confirm the first and last name by spelling the letters back to the customer (example: "Alex Smith" -> "A, L, E, X ... S, M, I, T, H")
 - Allow the customer to correct spelling mid-way or ask them to spell it out if unsure
 - Once the name is confirmed, book the appointment and provide a confirmation number from the booking result
 - Use the caller phone number unless the customer provides a different number
 - Never invent availability or confirmation numbers; use tool results
EXAMPLES OF GOOD RESPONSES:
OK "Let me look that up for you... I can see you have two recent orders."
OK "Your customer ID is zero two two two."
OK "I found your order, O-R-D zero one two three. It's currently being processed."
EXAMPLES OF BAD RESPONSES (AVOID):
NO "I'll convert your ID to the proper format CUST0222"
NO "Let me add the +1 prefix to your phone number"
NO "The system requires IDs to be in a specific format"
FILLER PHRASES:
IMPORTANT: Use a short, natural filler sentence before any tool call, then immediately call the tool.
Example scenarios and phrasing:
- store_hours: "Let me grab that for you in a second."
- location: "Let me pull up our location details."
- services: "Let me check our services and pricing."
- staff: "Let me see who is available."
- appointments: "Let me look that up for you."
- availability: "Let me check the calendar for openings."
- schedule: "Let me get that scheduled."
- orders: "Let me pull up your recent orders."
- customer_lookup: "Let me pull up your account."
Examples of what NOT to do:
- Responding with a filler sentence and then never calling the tool
- Saying "One moment please" without following with a tool call
- Adding filler phrases after a tool call
Correct pattern to follow:
1. When you need to look up information:
 - Say a filler sentence, then call the relevant lookup function (find_customer, get_orders, etc.)
2. Only speak again after you have the actual information to share
Remember: ANY phrase indicating you're about to look something up MUST be followed immediately by the appropriate tool call.
"""

VOICE = "aura-2-apollo-en"
# this gets updated by the agent template
FIRST_MESSAGE = ""
# audio settings
USER_AUDIO_SAMPLE_RATE = 48000
USER_AUDIO_SECS_PER_CHUNK = 0.05
USER_AUDIO_SAMPLES_PER_CHUNK = round(USER_AUDIO_SAMPLE_RATE * USER_AUDIO_SECS_PER_CHUNK)
AGENT_AUDIO_SAMPLE_RATE = 16000
AGENT_AUDIO_BYTES_PER_SEC = 2 * AGENT_AUDIO_SAMPLE_RATE
VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"
AUDIO_SETTINGS = {
    "input": {
        "encoding": "linear16",
        "sample_rate": USER_AUDIO_SAMPLE_RATE,
    },
    "output": {
        "encoding": "linear16",
        "sample_rate": AGENT_AUDIO_SAMPLE_RATE,
        "container": "none",
    },
}
LISTEN_SETTINGS = {
    "provider": {
        "type": "deepgram",
        "model": "nova-3",
    }
}
THINK_SETTINGS = {
    "provider": {
        "type": "open_ai",
        "model": "gpt-4o-mini",
        "temperature": 0.7,
    },
    "prompt": PROMPT_TEMPLATE,
    "functions": FUNCTION_DEFINITIONS,
}
SPEAK_SETTINGS = {
    "provider": {
        "type": "deepgram",
        "model": VOICE,
    }
}
AGENT_SETTINGS = {
    "language": "en",
    "listen": LISTEN_SETTINGS,
    "think": THINK_SETTINGS,
    "speak": SPEAK_SETTINGS,
    "greeting": FIRST_MESSAGE,
}
SETTINGS = {"type": "Settings", "audio": AUDIO_SETTINGS, "agent": AGENT_SETTINGS}


class AgentTemplates:
    PROMPT_TEMPLATE = PROMPT_TEMPLATE

    def __init__(
        self,
        industry="tech_support",
        voiceModel="aura-2-thalia-en",
        voiceName="",
    ):
        self.voiceName = voiceName
        self.voiceModel = voiceModel
        self.personality = ""
        self.company = ""
        self.first_message = ""
        self.capabilities = ""
        self.industry = industry
        self.prompt = self.PROMPT_TEMPLATE.format(
            current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M (%A, %B %d, %Y)")
        )
        self.voice_agent_url = VOICE_AGENT_URL
        self.settings = SETTINGS
        self.user_audio_sample_rate = USER_AUDIO_SAMPLE_RATE
        self.user_audio_secs_per_chunk = USER_AUDIO_SECS_PER_CHUNK
        self.user_audio_samples_per_chunk = USER_AUDIO_SAMPLES_PER_CHUNK
        self.agent_audio_sample_rate = AGENT_AUDIO_SAMPLE_RATE
        self.agent_audio_bytes_per_sec = AGENT_AUDIO_BYTES_PER_SEC
        match self.industry:
            case "tech_support":
                self.tech_support()
            case "healthcare":
                self.healthcare()
            case "banking":
                self.banking()
            case "pharmaceuticals":
                self.pharmaceuticals()
            case "retail":
                self.retail()
            case "travel":
                self.travel()
        self.first_message = (
            f"Hello! I'm {self.voiceName} from {self.company} customer service. "
            f"{self.capabilities} How can I help you today?"
        )
        self.settings["agent"]["speak"]["provider"]["model"] = self.voiceModel
        self.settings["agent"]["think"]["prompt"] = self.prompt
        self.settings["agent"]["greeting"] = self.first_message
        self.prompt = self.personality + "\n\n" + self.prompt

    def tech_support(
        self, company="TechStyle", agent_voice="aura-2-thalia-en", voiceName=""
    ):
        if voiceName == "":
            voiceName = self.get_voice_name_from_model(agent_voice)
        self.voiceName = voiceName
        self.company = company
        self.voiceModel = agent_voice
        self.personality = (
            f"You are {self.voiceName}, a friendly and professional customer service "
            f"representative for {self.company}, an online electronics and accessories "
            f"retailer. Your role is to assist customers with orders, appointments, and general inquiries."
        )
        self.capabilities = "I'd love to help you with your order or appointment."

    def healthcare(
        self, company="HealthFirst", agent_voice="aura-2-andromeda-en", voiceName=""
    ):
        if voiceName == "":
            voiceName = self.get_voice_name_from_model(agent_voice)
        self.voiceName = voiceName
        self.company = company
        self.voiceModel = agent_voice
        self.personality = (
            f"You are {self.voiceName}, a compassionate and knowledgeable healthcare "
            f"assistant for {self.company}, a leading healthcare provider. Your role is to "
            f"assist patients with appointments, medical inquiries, and general health information."
        )
        self.capabilities = (
            "I can help you schedule appointments or answer questions about our services."
        )

    def banking(
        self, company="SecureBank", agent_voice="aura-2-apollo-en", voiceName=""
    ):
        if voiceName == "":
            voiceName = self.get_voice_name_from_model(agent_voice)
        self.voiceName = voiceName
        self.company = company
        self.voiceModel = agent_voice
        self.personality = (
            f"You are {self.voiceName}, a professional and trustworthy banking representative "
            f"for {self.company}, a secure financial institution. Your role is to assist customers "
            f"with account inquiries, transactions, and financial services."
        )
        self.capabilities = "I can assist you with your account or any banking services you need."

    def pharmaceuticals(
        self, company="MedLine", agent_voice="aura-2-helena-en", voiceName=""
    ):
        if voiceName == "":
            voiceName = self.get_voice_name_from_model(agent_voice)
        self.voiceName = voiceName
        self.company = company
        self.voiceModel = agent_voice
        self.personality = (
            f"You are {self.voiceName}, a professional and trustworthy pharmaceutical representative "
            f"for {self.company}, a secure pharmaceutical company. Your role is to assist customers "
            f"with account inquiries, transactions, and appointments. You MAY NOT provide medical advice."
        )
        self.capabilities = "I can assist you with your account or appointments."

    def retail(self, company="StyleMart", agent_voice="aura-2-aries-en", voiceName=""):
        if voiceName == "":
            voiceName = self.get_voice_name_from_model(agent_voice)
        self.voiceName = voiceName
        self.company = company
        self.voiceModel = agent_voice
        self.personality = (
            f"You are {self.voiceName}, a friendly and attentive retail associate for {self.company}, "
            f"a trendy clothing and accessories store. Your role is to assist customers with product "
            f"inquiries, orders, and style recommendations."
        )
        self.capabilities = (
            "I can help you find the perfect item or check on your order status."
        )

    def travel(self, company="TravelTech", agent_voice="aura-2-arcas-en", voiceName=""):
        if voiceName == "":
            voiceName = self.get_voice_name_from_model(agent_voice)
        self.voiceName = voiceName
        self.company = company
        self.voiceModel = agent_voice
        self.personality = (
            f"You are {self.voiceName}, a friendly and professional customer service representative "
            f"for {self.company}, a tech-forward travel agency. Your role is to assist customers with "
            f"travel bookings, appointments, and general inquiries."
        )
        self.capabilities = (
            "I'd love to help you with your travel bookings or appointments."
        )

    @staticmethod
    def get_available_industries():
        """Return a dictionary of available industries with display names"""
        return {
            "tech_support": "Tech Support",
            "healthcare": "Healthcare",
            "banking": "Banking",
            "pharmaceuticals": "Pharmaceuticals",
            "retail": "Retail",
            "travel": "Travel",
        }

    def get_voice_name_from_model(self, model):
        return model.split("-")[2].split("-")[0].capitalize()

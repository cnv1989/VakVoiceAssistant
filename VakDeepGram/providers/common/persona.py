"""
Business persona presets for the voice/chat agent system prompts.

Vak ships as a generic appointment-booking voice assistant. The specific
"personality" the agent presents (what kind of business it thinks it is,
and the example dialogue it's shown) is controlled by two settings:

- ``BUSINESS_VERTICAL`` selects a preset from ``VERTICAL_PRESETS`` below
  (defaults to ``generic``, which mentions no specific industry).
- ``BUSINESS_ROLE_DESCRIPTION`` overrides the preset entirely with your
  own free-form description, for businesses that don't fit any preset.

Both providers' prompt modules (``providers/square/prompts.py`` and
``providers/setmore/prompts.py``) call into this module to build their
"#Role" and "#Example Tone" sections, so adding a new vertical here makes
it available to both providers automatically.

To add a new vertical, add an entry to ``VERTICAL_PRESETS`` and document it
in ``docs/CUSTOMIZING_YOUR_AGENT.md``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerticalPreset:
    """Copy used to render the agent's role description and example dialogue."""

    # Follows "You are ...". Should read naturally as a full sentence or two.
    role_description: str
    # A first-person customer request used in the "#Example Tone" section.
    example_request: str
    # How the agent should acknowledge that request (fragment, lowercase).
    example_ack: str


VERTICAL_PRESETS: dict[str, VerticalPreset] = {
    "generic": VerticalPreset(
        role_description=(
            "a scheduling assistant. You help customers with hours, location, "
            "services/prices, staff info, and booking appointments."
        ),
        example_request="I need an appointment next Tuesday afternoon with Alex.",
        example_ack="appointment with Alex next Tuesday afternoon",
    ),
    "barber": VerticalPreset(
        role_description=(
            "a grooming studio assistant focused on barbers (most important), "
            "beauticians, and pet groomers. You help with hours, location, "
            "services/prices, staff info, and booking appointments."
        ),
        example_request="I need a haircut next Tuesday afternoon with Alex.",
        example_ack="haircut with Alex next Tuesday afternoon",
    ),
    "salon": VerticalPreset(
        role_description=(
            "a hair salon assistant. You help with hours, location, "
            "services/prices, stylist info, and booking appointments."
        ),
        example_request="I need a color and cut next Tuesday afternoon with Alex.",
        example_ack="color and cut with Alex next Tuesday afternoon",
    ),
    "spa": VerticalPreset(
        role_description=(
            "a spa and wellness assistant. You help with hours, location, "
            "treatments/prices, therapist info, and booking appointments."
        ),
        example_request="I'd like to book a massage next Tuesday afternoon with Alex.",
        example_ack="massage with Alex next Tuesday afternoon",
    ),
    "medical": VerticalPreset(
        role_description=(
            "a clinic scheduling assistant. You help with hours, location, "
            "services/prices, provider info, and booking appointments."
        ),
        example_request="I need to book a check-up next Tuesday afternoon with Dr. Alex.",
        example_ack="check-up with Dr. Alex next Tuesday afternoon",
    ),
    "fitness": VerticalPreset(
        role_description=(
            "a fitness studio assistant. You help with hours, location, "
            "class/session pricing, trainer info, and booking sessions."
        ),
        example_request="I'd like to book a training session next Tuesday afternoon with Alex.",
        example_ack="training session with Alex next Tuesday afternoon",
    ),
    "home_services": VerticalPreset(
        role_description=(
            "a home services scheduling assistant. You help with hours, "
            "location, services/pricing, technician info, and booking visits."
        ),
        example_request="I need someone to come out next Tuesday afternoon, ideally Alex.",
        example_ack="service visit with Alex next Tuesday afternoon",
    ),
}

DEFAULT_VERTICAL = "generic"


def get_preset(vertical: str | None) -> VerticalPreset:
    """Look up a vertical preset, falling back to the generic default."""
    key = (vertical or DEFAULT_VERTICAL).strip().lower()
    return VERTICAL_PRESETS.get(key, VERTICAL_PRESETS[DEFAULT_VERTICAL])


def build_role_section(settings) -> str:
    """Build the '#Role' sentence(s) from settings.

    Priority: an explicit ``business_role_description`` override, else the
    ``business_vertical`` preset, optionally prefixed with the business name.
    """
    if getattr(settings, "business_role_description", None):
        return f"You are {settings.business_role_description}"

    preset = get_preset(getattr(settings, "business_vertical", None))
    business_name = getattr(settings, "business_name", None)
    if business_name:
        return f"You are the voice and chat assistant for {business_name}, {preset.role_description}"
    return f"You are {preset.role_description}"


def build_example_tone(settings) -> str:
    """Build the '#Example Tone' snippet from settings."""
    preset = get_preset(getattr(settings, "business_vertical", None))
    return (
        "#Example Tone\n"
        f'-Customer: "{preset.example_request}"\n'
        f'-Agent: "Got it—{preset.example_ack}. Let me check what\'s available. '
        f'Do you have a time range in mind, or is any time that afternoon okay?"'
    )

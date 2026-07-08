# Customizing Your Agent

Vak ships as a generic appointment-booking assistant. Its persona — what
kind of business it thinks it's answering for, and the example dialogue it
follows — is controlled by a small set of settings, plus one file if you
want to add a whole new industry preset.

## The quick way: pick a vertical

Set `BUSINESS_VERTICAL` in `VakDeepGram/.env` (or answer the wizard's
"What kind of business is this?" question in `./vak init`) to one of:

| Vertical | Example role |
|---|---|
| `generic` (default) | "a scheduling assistant" |
| `barber` | "a grooming studio assistant focused on barbers, beauticians, and pet groomers" |
| `salon` | "a hair salon assistant" |
| `spa` | "a spa and wellness assistant" |
| `medical` | "a clinic scheduling assistant" |
| `fitness` | "a fitness studio assistant" |
| `home_services` | "a home services scheduling assistant" |

Also set `BUSINESS_NAME` and the agent will introduce itself by name:

```bash
BUSINESS_NAME="Downtown Cuts"
BUSINESS_VERTICAL=barber
```

This produces a system prompt opening like:

> You are the voice and chat assistant for Downtown Cuts, a grooming studio
> assistant focused on barbers (most important), beauticians, and pet
> groomers. You help with hours, location, services/prices, staff info, and
> booking appointments.

Everything else about the booking flow (asking for a date, checking
availability, confirming details, handling reschedules, etc.) is generic
across all verticals — only the opening role description and one example
exchange change.

## The custom way: write your own persona

If none of the presets fit, set `BUSINESS_ROLE_DESCRIPTION` instead — it
completely replaces the generated role sentence:

```bash
BUSINESS_ROLE_DESCRIPTION="a friendly front-desk assistant for an auto repair shop. You help with hours, quotes, and booking service appointments."
```

`./vak init` offers this as the "Custom — write my own persona" option.

## Adding a new vertical preset

If you're deploying Vak for a recurring type of business (say, every
customer runs a dental practice), add a preset instead of setting
`BUSINESS_ROLE_DESCRIPTION` per-deployment. Edit
[`VakDeepGram/providers/common/persona.py`](../VakDeepGram/providers/common/persona.py):

```python
VERTICAL_PRESETS: dict[str, VerticalPreset] = {
    ...
    "dental": VerticalPreset(
        role_description=(
            "a dental office assistant. You help with hours, location, "
            "treatments/prices, provider info, and booking appointments."
        ),
        example_request="I'd like to book a cleaning next Tuesday afternoon with Dr. Alex.",
        example_ack="cleaning with Dr. Alex next Tuesday afternoon",
    ),
}
```

Set `BUSINESS_VERTICAL=dental` and both the voice and chat prompts (for
both the Square and Setmore providers) pick it up automatically — see
`providers/square/prompts.py` and `providers/setmore/prompts.py`, which
both call `persona.build_role_section()` / `persona.build_example_tone()`
to render the "#Role" and "#Example Tone" sections.

## What's shared vs. what's per-provider

The booking *flow* (ask for date → staff preference → service → check
availability → confirm → book) lives in `providers/square/prompts.py` and
`providers/setmore/prompts.py` because Square and Setmore genuinely behave
differently — for example, Setmore can't create appointments directly (it
generates a booking link sent via SMS/WhatsApp), while Square books
directly and supports rescheduling. Only the persona layer (role + example)
is shared through `persona.py`. If you need per-vertical changes to the
booking flow itself rather than just tone, edit the provider prompt files
directly.

## Client branding

`VakClient` picks up the same business name for its UI:

```bash
# VakClient/.env
VITE_BUSINESS_NAME="Downtown Cuts"
```

This sets the header title, the chat page's assistant name, and the label
on the AI's message bubbles in the voice UI.

# Project Structure (Incremental Refactor)

This repository is being reorganized incrementally to keep behavior stable while improving maintainability.

## Current layers

- `api` layer:
  - `main.py`, `deepgram_handler.py`
  - Handles HTTP/WebSocket/Twilio transport, request parsing, and response formatting.
  - New package entrypoint facade exists at `src/vakdeepgram/api/main.py` (`vakdeepgram.api.main:app`).

- `services` layer:
  - `services/auth_context_service.py`
  - Orchestrates provider auth context resolution used by voice/chat/tool flows.

- `repositories` layer:
  - `repositories/connection_context_repository.py`
  - Wraps runtime connection-context persistence (`connection_store` in-memory state).

- `providers` layer:
  - `providers/clients/*` for external API client wrappers (Setmore/Square).
  - `providers/setmore/tools.py`, `providers/square/tools.py` for provider-specific Strands tools.

- `domain/business` layer:
  - `business_logic.py`, `agent_functions.py`
  - Booking/customer flows and Deepgram function-call implementations.

## Direction

1. Keep route/WebSocket handlers thin.
2. Move shared orchestration into `services/`.
3. Keep all data access wrappers in `repositories/`.
4. Keep external API calls in `providers/clients/`.
5. Use provider-specific tools/functions only for conversation/tool contracts, not token plumbing.

## Package migration status

- New package layout has been introduced under `src/vakdeepgram/` with facades for:
  - `api`
  - `core`
  - `services`
  - `repositories`
  - `providers`
  - `domain`
  - `utils`
- Existing root modules remain active for compatibility while imports are migrated incrementally.

## Migration rules

- Prefer adding wrappers and switching call-sites over big file moves.
- Keep public behavior and response payloads backward-compatible.
- Add focused tests for each moved responsibility.

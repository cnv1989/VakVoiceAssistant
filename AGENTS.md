# Repository Guidelines

## Project Structure & Module Organization
- `VakClient/` is the React + Vite frontend (TypeScript) and primary UI entry point.
  - Core files: `src/main.tsx`, `src/App.tsx`, `src/Layout.tsx`, `src/ChatPage.tsx`.
  - WebSocket signing logic: `src/ws-signer.ts`.
  - Styling lives in `src/*.css`.
- `VakDeepGram/` is the FastAPI WebSocket server that connects to Deepgram Voice Agents.
  - Entrypoint: `main.py`.
  - Core behavior: `deepgram_handler.py`, `business_logic.py`, `agent_functions.py`, `store_tools.py`, `connection_store.py`.
  - Layers: `services/` (auth/business context), `repositories/` (connection context), `providers/clients/` (Square/Setmore APIs), `providers/setmore/`, `providers/square/` (tools, prompts).
  - New package: `src/vakdeepgram/` (api, core, domain, providers, repositories, services, utils). See `VakDeepGram/docs/PROJECT_STRUCTURE.md`.
  - Config: `config.py`, `.env.example`.
  - Tests: `tests/` with `pytest` configuration in `pytest.ini`; `scripts/tests/` for API and full-stack scripts.
  - Manual client: `test_client.html`.
- `VakInfra/` contains AWS CDK v2 stacks for networking and app deployment.
  - Entrypoint: `bin/vak-infra.ts`.
  - Stacks: `lib/vak-network-stack.ts`, `lib/vak-app-stack.ts`.
  - Deployment helpers and docs live alongside the stacks.
- `cli/` implements the `./vak` CLI (`init`/`dev`/`deploy`/`doctor`) — the primary entry point for setup and local dev; see `docs/GETTING_STARTED.md`.
- `docs/` has the full guide set (getting started, configuration, customizing the agent, deployment, architecture, design, FAQ). Root-level `CONNECT_INTEGRATION.md` and `DEBUG_WSS.md` cover specific integration/debugging deep-dives.

## Build, Test, and Development Commands
- Quickest path: `./vak init` then `./vak dev` from the repo root (see `docs/GETTING_STARTED.md`).
- Client:
  - `cd VakClient && npm install`
  - `cd VakClient && npm run dev`
  - `cd VakClient && npm run build`
- Server:
  - `cd VakDeepGram && python -m venv venv && source venv/bin/activate`
  - `cd VakDeepGram && pip install -r requirements.txt`
  - `cd VakDeepGram && PYTHONPATH=src uvicorn vakdeepgram.api.main:app --host 0.0.0.0 --port 8080 --reload`
  - Docker: `cd VakDeepGram && ./docker-run.sh up -d`
  - ECR build/push: `cd VakDeepGram && ./deploy-to-ecr.sh`
- Infra:
  - `cd VakInfra && npm install`
  - `cd VakInfra && npm run synth`
  - `cd VakInfra && npm run diff`
  - `cd VakInfra && npm run deploy`

## Coding Style & Naming Conventions
- Client (TypeScript): 2-space indentation, React components in `.tsx`, follow existing CSS module patterns in `src/*.css`.
- Server (Python): 4-space indentation, PEP 8 naming, keep configuration in `config.py` and environment variables.
- Infra (TypeScript/CDK): keep stacks in `lib/`, avoid embedding secrets in code.

## Testing Guidelines
- `VakDeepGram` uses `pytest` with tests under `VakDeepGram/tests/`.
  - Run with `cd VakDeepGram && pytest` after installing `requirements-dev.txt` if needed.
- No automated tests are configured for `VakClient` or `VakInfra` yet.

## Commit & Pull Request Guidelines
- Prefer short, capitalized, imperative commit messages (e.g., "Update websocket handling").
- PRs should include a clear description, test steps, and UI screenshots for client-visible changes.
- For infra changes, call out affected AWS resources and any new environment variables.

## Security & Configuration Tips
- Do not commit secrets. Use `.env` files (all gitignored) or AWS Secrets Manager for sensitive values. `./vak init` generates `.env` files for you.
- `VakDeepGram` relies on `DEEPGRAM_*`, `BUSINESS_*`, and `TWILIO_*` settings; keep them out of source control.
- `VakClient` requires `VITE_WS_URL` and any AWS credential env vars for signing.
- Keep AWS credentials local and out of git history.

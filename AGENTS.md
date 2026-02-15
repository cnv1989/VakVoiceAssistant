# Repository Guidelines

## Project Structure & Module Organization
- `VakClient/` is the React + Vite frontend (TypeScript) and primary UI entry point.
  - Core files: `src/main.tsx`, `src/App.tsx`, `src/Layout.tsx`, `src/ChatPage.tsx`.
  - WebSocket signing logic: `src/ws-signer.ts`.
  - Styling lives in `src/*.css`.
- `VakDeepGram/` is the FastAPI WebSocket server that connects to Deepgram Voice Agents.
  - Entrypoint: `main.py`.
  - Core behavior: `deepgram_handler.py`, `business_logic.py`, `agent_functions.py`, `store_tools.py`, `connection_store.py`.
  - Config: `config.py`, `.env.example`.
  - Tests: `tests/` with `pytest` configuration in `pytest.ini`.
  - Manual client: `test_client.html`.
- `VakInfra/` contains AWS CDK v2 stacks for networking and app deployment.
  - Entrypoint: `bin/vak-infra.ts`.
  - Stacks: `lib/vak-network-stack.ts`, `lib/vak-app-stack.ts`.
  - Deployment helpers and docs live alongside the stacks.
- Root docs (`README.md`, `TROUBLESHOOTING.md`, `CONNECT_INTEGRATION.md`, `DEBUG_WSS.md`) describe setup and operational flows.

## Build, Test, and Development Commands
- Client:
  - `cd VakClient && npm install`
  - `cd VakClient && npm run dev`
  - `cd VakClient && npm run build`
- Server:
  - `cd VakDeepGram && python -m venv venv && source venv/bin/activate`
  - `cd VakDeepGram && pip install -r requirements.txt`
  - `cd VakDeepGram && python main.py`
  - `cd VakDeepGram && uvicorn main:app --host 0.0.0.0 --port 8080 --reload`
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
- Do not commit secrets. Use `.env` files or AWS Secrets Manager for sensitive values.
- `VakDeepGram` relies on `DEEPGRAM_*` and `TWILIO_*` settings; keep them out of source control.
- `VakClient` requires `VITE_WS_URL` and any AWS credential env vars for signing.
- Keep AWS credentials local and out of git history.

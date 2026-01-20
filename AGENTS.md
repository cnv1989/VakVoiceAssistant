# Repository Guidelines

## Project Structure & Module Organization
- `VakClient/` is the React + Vite frontend (TypeScript) and the primary UI entry point.
- `VakServer/` is the Fastify + TypeScript backend that handles WebSocket traffic and AWS integrations.
- `VakInfra/` contains AWS CDK v2 stacks for networking and app deployment.
- `VakDeepGram/` and `Twilio/` hold integration helpers and HTML-based test clients.
- Root docs (`README.md`, `TROUBLESHOOTING.md`, `CONNECT_INTEGRATION.md`) explain setup and operational flows.

## Build, Test, and Development Commands
- Client: `cd VakClient && npm install && npm run dev` (local dev server), `npm run build` (production build).
- Server: `cd VakServer && npm install && npm run dev` (hot reload), `npm run build` then `npm start` (prod build/run).
- Infra: `cd VakInfra && npm install && npm run synth` (CloudFormation), `npm run deploy` (CDK deploy).
- Docker/ECR: `cd VakServer && npm run deploy:ecr` to build and push images.

## Coding Style & Naming Conventions
- TypeScript is used across client/server/infra; keep indentation at 2 spaces and follow existing semicolon usage.
- Use `.tsx` for React components and `.ts` for server/infra modules.
- Prefer descriptive, feature-based naming (e.g., `ws-signer.ts`, `deploy-to-ecr.sh`).
- No repo-wide lint/format config is enforced; keep edits consistent with nearby files.

## Testing Guidelines
- There is no automated test suite in this repo today.
- Validate changes manually using local WebSocket flows; see `Twilio/test-websocket.html` and `VakDeepGram/test_client.html`.
- If adding tests, document how to run them in the relevant package `README.md`.

## Commit & Pull Request Guidelines
- Recent commits use short, capitalized, imperative sentences (e.g., “Update time handling”).
- PRs should include a clear description, test steps, and UI screenshots when client changes are visible.
- For infra changes, call out affected AWS resources and any required environment variables.

## Security & Configuration Tips
- Do not commit secrets. Use `.env` files as referenced in `VakClient/README.md` and `VakServer/README.md`.
- Client config uses `VITE_WS_URL` and AWS credential env vars for signing; server config uses `WS_API_ENDPOINT`, `REGION`, and related settings.
- Keep AWS CLI/CDK credentials local and out of source control.

# Repository Guidelines

## Project Structure & Module Organization
This repository is a Python FastAPI WebSocket server for Deepgram Voice Agents. Key files and paths:
- `main.py`: FastAPI app and WebSocket entrypoint.
- `deepgram_handler.py`: Deepgram STS WebSocket client and event handling.
- `config.py`: environment-driven settings and defaults.
- `test_client.html`: browser-based manual test client.
- `Dockerfile`, `docker-run.sh`, `docker-run.bat`: containerized runtime helpers.
- `deploy-to-ecr.sh`: ECR publishing script for VakInfra use.

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate`: create/activate a virtualenv.
- `pip install -r requirements.txt`: install Python dependencies.
- `python main.py`: run the server directly.
- `uvicorn main:app --host 0.0.0.0 --port 8080 --reload`: run with hot reload.
- `./docker-run.sh up -d`: run in Docker (background).
- `./deploy-to-ecr.sh`: build and push image to ECR.

## Coding Style & Naming Conventions
- Python uses 4-space indentation and PEP 8 naming (snake_case for functions/vars).
- Module names are lowercase with underscores (e.g., `deepgram_handler.py`).
- Keep configuration in `config.py` and environment variables, not hard-coded values.

## Testing Guidelines
There is no automated test suite yet.
- Manual smoke test: open `test_client.html` and connect to `ws://localhost:8080/ws`.
- If adding tests, prefer `pytest` with files named `test_*.py` in a `tests/` directory.

## Commit & Pull Request Guidelines
Git history uses short, capitalized, past-tense summaries (e.g., "Added twilio integration").
For PRs:
- Describe the behavior change and any new env vars.
- Include run instructions or logs if behavior is hard to verify.
- Add screenshots only if UI-facing changes occur (e.g., `test_client.html`).

## Security & Configuration Tips
- Do not commit secrets; use `.env` based on `.env.example`.
- Validate `DEEPGRAM_*` settings before deploy; mismatches cause WebSocket failures.

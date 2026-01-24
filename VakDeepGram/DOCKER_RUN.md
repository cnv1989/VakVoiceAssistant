# Running VakDeepGram in Docker

## Prerequisites

1. **Start Docker Desktop** (or Docker daemon)
   - On macOS: Open Docker Desktop application
   - On Linux: `sudo systemctl start docker`
   - Verify: `docker ps` should work without errors

2. **Create `.env` file** (if not already created)
   ```bash
   cp .env.example .env
   # Edit .env and add your DEEPGRAM_API_KEY
   ```

## Building and Running

### Option 1: Using the Helper Script (Recommended)

```bash
# On macOS/Linux
./docker-run.sh up -d

# On Windows
docker-run.bat up -d

# View logs
./docker-run.sh logs
# or
docker-run.bat logs

# Stop the server
./docker-run.sh stop
# or
docker-run.bat stop
```

### Option 2: Using Docker directly

```bash
# Build the image
docker build -t vakdeepgram .

# Run the container
docker run -d \
  --name vakdeepgram \
  -p 8080:8080 \
  --env-file .env \
  --restart unless-stopped \
  vakdeepgram

# View logs
docker logs -f vakdeepgram

# Stop the container
docker stop vakdeepgram
docker rm vakdeepgram
```

## Environment Variables

The container will use environment variables from:
1. `.env` file (passed via `--env-file .env`)
2. Environment variables passed via `-e` flags
3. Default values from `config.py`

**Required:**
- `DEEPGRAM_API_KEY` - Your Deepgram API key

**Optional:**
- `DEEPGRAM_PROJECT_ID` - Your Deepgram project ID (not required for STS)
- `DEEPGRAM_AGENT_ID` - Agent ID (optional, leave empty for dynamic creation)
- `HOST` - Server host (default: 0.0.0.0)
- `PORT` - Server port (default: 8080)
- `LOG_LEVEL` - Logging level (default: debug)

## Accessing the Server

Once running, the server will be available at:
- **WebSocket**: `ws://localhost:8080/ws`
- **Health Check**: `http://localhost:8080/health`
- **Root**: `http://localhost:8080/`

## Troubleshooting

### Docker daemon not running
```bash
# macOS: Start Docker Desktop app
# Linux: sudo systemctl start docker
```

### Port already in use
```bash
# Use different port mapping
docker run -d \
  --name vakdeepgram \
  -p 8082:8080 \
  --env-file .env \
  vakdeepgram
```

### View container logs
```bash
docker logs -f vakdeepgram
# or using helper script
./docker-run.sh logs
```

### Rebuild after code changes
```bash
docker build --no-cache -t vakdeepgram .
# or using helper script
./docker-run.sh rebuild
```

### Check if container is running
```bash
docker ps
# or using helper script
./docker-run.sh status
```

### Clean up everything
```bash
# Stop and remove container and image
docker stop vakdeepgram 2>/dev/null || true
docker rm vakdeepgram 2>/dev/null || true
docker rmi vakdeepgram 2>/dev/null || true
# or using helper script
./docker-run.sh clean
```

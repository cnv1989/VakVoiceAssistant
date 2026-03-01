#!/bin/bash

# VakDeepGram Docker Runner Script
# This script builds and runs the VakDeepGram server in a Docker container

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Container name and image name
CONTAINER_NAME="vakdeepgram"
IMAGE_NAME="vakdeepgram"

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}🐳 VakDeepGram Docker Runner${NC}"
echo ""

# Parse command line arguments first (for help command)
ACTION="${1:-up}"
DETACHED="${2:-}"

# Handle help before Docker check
if [ "$ACTION" = "help" ] || [ "$ACTION" = "--help" ] || [ "$ACTION" = "-h" ]; then
    echo -e "${BLUE}Usage: $0 [command] [options]${NC}"
    echo ""
    echo "Commands:"
    echo "  build          Build the Docker image"
    echo "  up, start      Start the server (default)"
    echo "  up -d          Start the server in background"
    echo "  down, stop     Stop the server"
    echo "  restart        Restart the server"
    echo "  logs           Show server logs"
    echo "  status, ps     Show container status"
    echo "  rebuild        Rebuild image without cache"
    echo "  shell, exec    Open shell in container"
    echo "  clean          Stop and remove containers/images"
    echo "  help           Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0              # Start server (foreground)"
    echo "  $0 up -d        # Start server (background)"
    echo "  $0 logs         # View logs"
    echo "  $0 restart      # Restart server"
    echo "  $0 clean        # Clean up everything"
    exit 0
fi

# Check if Docker is running
echo -e "${YELLOW}Checking Docker daemon...${NC}"
if ! docker ps > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker daemon is not running!${NC}"
    echo -e "${YELLOW}Please start Docker Desktop or Docker daemon and try again.${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker daemon is running${NC}"
echo ""

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  .env file not found${NC}"
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}Creating .env from .env.example...${NC}"
        cp .env.example .env
        echo -e "${GREEN}✅ Created .env file${NC}"
        echo -e "${YELLOW}⚠️  Please edit .env and add your DEEPGRAM_API_KEY before running again!${NC}"
        exit 1
    else
        echo -e "${RED}❌ .env.example not found. Please create .env file manually.${NC}"
        exit 1
    fi
fi

# Check if DEEPGRAM_API_KEY is set in .env
if ! grep -q "DEEPGRAM_API_KEY=.*[^=]$" .env 2>/dev/null || grep -q "DEEPGRAM_API_KEY=your_deepgram_api_key_here" .env 2>/dev/null; then
    echo -e "${YELLOW}⚠️  DEEPGRAM_API_KEY not set in .env file${NC}"
    echo -e "${YELLOW}Please edit .env and add your DEEPGRAM_API_KEY${NC}"
    exit 1
fi

# Helper function to check if container exists
container_exists() {
    docker ps -a --filter "name=^${CONTAINER_NAME}$" --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"
}

# Helper function to check if container is running
container_running() {
    docker ps --filter "name=^${CONTAINER_NAME}$" --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"
}

# Wait for HTTP health endpoint to become ready.
wait_for_health() {
    local url="http://127.0.0.1:8080/health"
    local max_attempts=30
    local attempt=1

    echo -e "${YELLOW}Waiting for health endpoint: ${url}${NC}"
    while [ "$attempt" -le "$max_attempts" ]; do
        if ! container_running; then
            echo -e "${RED}❌ Container exited during startup${NC}"
            return 1
        fi
        if curl -fsS "$url" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Health check passed${NC}"
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done

    echo -e "${RED}❌ Health check timed out after ${max_attempts}s${NC}"
    return 1
}

case "$ACTION" in
    build)
        echo -e "${BLUE}🔨 Building Docker image...${NC}"
        docker build -t "$IMAGE_NAME" .
        echo -e "${GREEN}✅ Build complete${NC}"
        ;;
    
    up|start)
        # Build image if it doesn't exist
        if ! docker images --format "{{.Repository}}" | grep -q "^${IMAGE_NAME}$"; then
            echo -e "${YELLOW}Image not found, building...${NC}"
            docker build -t "$IMAGE_NAME" .
        fi
        
        # Remove existing container if it exists but is stopped
        if container_exists && ! container_running; then
            echo -e "${YELLOW}Removing stopped container...${NC}"
            docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
        fi
        
        # Stop and remove if already running
        if container_running; then
            echo -e "${YELLOW}Container already running, stopping...${NC}"
            docker stop "$CONTAINER_NAME" > /dev/null 2>&1 || true
            docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
        fi
        
        echo -e "${BLUE}🚀 Starting VakDeepGram server...${NC}"
        if [ "$DETACHED" = "-d" ] || [ "$DETACHED" = "--detach" ]; then
            docker run -d \
                --name "$CONTAINER_NAME" \
                -p 8080:8080 \
                --env-file .env \
                --restart unless-stopped \
                "$IMAGE_NAME"
            if wait_for_health; then
                echo -e "${GREEN}✅ Server started in background${NC}"
                echo -e "${BLUE}View logs with: $0 logs${NC}"
            else
                echo -e "${RED}❌ Server failed to start cleanly. Recent logs:${NC}"
                docker logs --tail 200 "$CONTAINER_NAME" || true
                exit 1
            fi
        else
            echo -e "${BLUE}Starting server (press Ctrl+C to stop)...${NC}"
            echo ""
            docker run --rm \
                --name "$CONTAINER_NAME" \
                -p 8080:8080 \
                --env-file .env \
                "$IMAGE_NAME"
        fi
        ;;
    
    down|stop)
        if container_running; then
            echo -e "${BLUE}🛑 Stopping VakDeepGram server...${NC}"
            docker stop "$CONTAINER_NAME"
            docker rm "$CONTAINER_NAME"
            echo -e "${GREEN}✅ Server stopped${NC}"
        elif container_exists; then
            echo -e "${YELLOW}Container exists but is not running, removing...${NC}"
            docker rm "$CONTAINER_NAME"
            echo -e "${GREEN}✅ Container removed${NC}"
        else
            echo -e "${YELLOW}Container not found${NC}"
        fi
        ;;
    
    restart)
        if container_running; then
            echo -e "${BLUE}🔄 Restarting VakDeepGram server...${NC}"
            docker restart "$CONTAINER_NAME"
            echo -e "${GREEN}✅ Server restarted${NC}"
        else
            echo -e "${YELLOW}Container not running, starting...${NC}"
            $0 up -d
        fi
        ;;
    
    logs)
        if container_exists; then
            echo -e "${BLUE}📋 Showing logs (press Ctrl+C to exit)...${NC}"
            docker logs -f "$CONTAINER_NAME"
        else
            echo -e "${RED}❌ Container not found. Start it first with '$0 up'${NC}"
            exit 1
        fi
        ;;
    
    status|ps)
        echo -e "${BLUE}📊 Container status:${NC}"
        if container_exists; then
            docker ps -a --filter "name=^${CONTAINER_NAME}$"
        else
            echo -e "${YELLOW}Container not found${NC}"
        fi
        ;;
    
    rebuild)
        echo -e "${BLUE}🔨 Rebuilding Docker image (no cache)...${NC}"
        docker build --no-cache -t "$IMAGE_NAME" .
        echo -e "${GREEN}✅ Rebuild complete${NC}"
        ;;
    
    shell|exec)
        if container_running; then
            echo -e "${BLUE}🐚 Opening shell in container...${NC}"
            docker exec -it "$CONTAINER_NAME" /bin/bash || docker exec -it "$CONTAINER_NAME" /bin/sh
        else
            echo -e "${RED}❌ Container not running. Start it first with '$0 up'${NC}"
            exit 1
        fi
        ;;
    
    clean)
        echo -e "${YELLOW}🧹 Cleaning up Docker resources...${NC}"
        if container_running; then
            docker stop "$CONTAINER_NAME" > /dev/null 2>&1 || true
        fi
        if container_exists; then
            docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
        fi
        docker rmi "$IMAGE_NAME" > /dev/null 2>&1 || true
        echo -e "${GREEN}✅ Cleanup complete${NC}"
        ;;
    
    *)
        echo -e "${RED}❌ Unknown command: $ACTION${NC}"
        echo -e "${YELLOW}Run '$0 help' for usage information${NC}"
        exit 1
        ;;
esac

# Show connection info after starting
if [ "$ACTION" = "up" ] || [ "$ACTION" = "start" ]; then
    if [ "$DETACHED" = "-d" ] || [ "$DETACHED" = "--detach" ]; then
        echo ""
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}✅ Server is running!${NC}"
        echo ""
        echo -e "${BLUE}WebSocket:${NC} ws://localhost:8080/ws"
        echo -e "${BLUE}Health:${NC}    http://localhost:8080/health"
        echo -e "${BLUE}Root:${NC}      http://localhost:8080/"
        echo ""
        echo -e "${YELLOW}View logs:${NC} $0 logs"
        echo -e "${YELLOW}Stop:${NC}      $0 stop"
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    fi
fi

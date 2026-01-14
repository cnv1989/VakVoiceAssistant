#!/bin/bash

# Run VakDeepGram server with file watching (auto-reload)

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your Deepgram credentials"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Run server with reload enabled (watches for file changes)
echo "🚀 Starting VakDeepGram server with auto-reload (watching for file changes)..."
echo "📁 Watching: *.py, *.yaml, *.yml, *.json, *.env"
uvicorn main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --reload \
    --reload-dir . \
    --log-level info

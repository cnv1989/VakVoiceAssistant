@echo off
REM VakDeepGram Docker Runner Script for Windows
REM This script builds and runs the VakDeepGram server in a Docker container

setlocal enabledelayedexpansion

set CONTAINER_NAME=vakdeepgram
set IMAGE_NAME=vakdeepgram

echo 🐳 VakDeepGram Docker Runner
echo.

REM Check if Docker is running
echo Checking Docker daemon...
docker ps >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker daemon is not running!
    echo Please start Docker Desktop and try again.
    exit /b 1
)
echo ✅ Docker daemon is running
echo.

REM Check if .env file exists
if not exist ".env" (
    echo ⚠️  .env file not found
    if exist ".env.example" (
        echo Creating .env from .env.example...
        copy .env.example .env >nul
        echo ✅ Created .env file
        echo ⚠️  Please edit .env and add your DEEPGRAM_API_KEY before running again!
        exit /b 1
    ) else (
        echo ❌ .env.example not found. Please create .env file manually.
        exit /b 1
    )
)

REM Parse command line arguments
set ACTION=%1
if "%ACTION%"=="" set ACTION=up

if "%ACTION%"=="build" (
    echo 🔨 Building Docker image...
    docker build -t %IMAGE_NAME% .
    echo ✅ Build complete
    goto :end
)

if "%ACTION%"=="up" (
    REM Build image if it doesn't exist
    docker images --format "{{.Repository}}" | findstr /C:"%IMAGE_NAME%" >nul 2>&1
    if errorlevel 1 (
        echo Building image...
        docker build -t %IMAGE_NAME% .
    )
    
    REM Stop and remove existing container if running
    docker ps --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        echo Stopping existing container...
        docker stop %CONTAINER_NAME% >nul 2>&1
        docker rm %CONTAINER_NAME% >nul 2>&1
    )
    
    if "%2"=="-d" (
        echo 🚀 Starting VakDeepGram server in background...
        docker run -d --name %CONTAINER_NAME% -p 8080:8080 --env-file .env --restart unless-stopped %IMAGE_NAME%
        echo ✅ Server started in background
        echo View logs with: %0 logs
    ) else (
        echo 🚀 Starting VakDeepGram server...
        echo Starting server (press Ctrl+C to stop)...
        echo.
        docker run --rm --name %CONTAINER_NAME% -p 8080:8080 --env-file .env %IMAGE_NAME%
    )
    goto :info
)

if "%ACTION%"=="start" (
    docker images --format "{{.Repository}}" | findstr /C:"%IMAGE_NAME%" >nul 2>&1
    if errorlevel 1 (
        docker build -t %IMAGE_NAME% .
    )
    docker ps --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        docker stop %CONTAINER_NAME% >nul 2>&1
        docker rm %CONTAINER_NAME% >nul 2>&1
    )
    if "%2"=="-d" (
        docker run -d --name %CONTAINER_NAME% -p 8080:8080 --env-file .env --restart unless-stopped %IMAGE_NAME%
    ) else (
        docker run --rm --name %CONTAINER_NAME% -p 8080:8080 --env-file .env %IMAGE_NAME%
    )
    goto :info
)

if "%ACTION%"=="down" (
    docker ps --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        echo 🛑 Stopping VakDeepGram server...
        docker stop %CONTAINER_NAME%
        docker rm %CONTAINER_NAME%
        echo ✅ Server stopped
    ) else (
        docker ps -a --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
        if not errorlevel 1 (
            echo Container exists but is not running, removing...
            docker rm %CONTAINER_NAME%
            echo ✅ Container removed
        ) else (
            echo Container not found
        )
    )
    goto :end
)

if "%ACTION%"=="stop" (
    docker ps --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        docker stop %CONTAINER_NAME%
        docker rm %CONTAINER_NAME%
    )
    goto :end
)

if "%ACTION%"=="restart" (
    docker ps --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        echo 🔄 Restarting VakDeepGram server...
        docker restart %CONTAINER_NAME%
        echo ✅ Server restarted
    ) else (
        echo Container not running, starting...
        call %0 up -d
    )
    goto :end
)

if "%ACTION%"=="logs" (
    docker ps -a --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        echo 📋 Showing logs (press Ctrl+C to exit)...
        docker logs -f %CONTAINER_NAME%
    ) else (
        echo ❌ Container not found. Start it first with '%0 up'
        exit /b 1
    )
    goto :end
)

if "%ACTION%"=="status" (
    echo 📊 Container status:
    docker ps -a --filter "name=^%CONTAINER_NAME%$"
    goto :end
)

if "%ACTION%"=="ps" (
    docker ps -a --filter "name=^%CONTAINER_NAME%$"
    goto :end
)

if "%ACTION%"=="rebuild" (
    echo 🔨 Rebuilding Docker image (no cache)...
    docker build --no-cache -t %IMAGE_NAME% .
    echo ✅ Rebuild complete
    goto :end
)

if "%ACTION%"=="clean" (
    echo 🧹 Cleaning up Docker resources...
    docker ps --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        docker stop %CONTAINER_NAME% >nul 2>&1
    )
    docker ps -a --filter "name=^%CONTAINER_NAME%$" --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul 2>&1
    if not errorlevel 1 (
        docker rm %CONTAINER_NAME% >nul 2>&1
    )
    docker images --format "{{.Repository}}" | findstr /C:"%IMAGE_NAME%" >nul 2>&1
    if not errorlevel 1 (
        docker rmi %IMAGE_NAME% >nul 2>&1
    )
    echo ✅ Cleanup complete
    goto :end
)

if "%ACTION%"=="help" (
    goto :help
)

if "%ACTION%"=="--help" (
    goto :help
)

if "%ACTION%"=="-h" (
    goto :help
)

echo ❌ Unknown command: %ACTION%
echo Run '%0 help' for usage information
exit /b 1

:help
echo Usage: %0 [command] [options]
echo.
echo Commands:
echo   build          Build the Docker image
echo   up, start      Start the server (default)
echo   up -d          Start the server in background
echo   down, stop     Stop the server
echo   restart        Restart the server
echo   logs           Show server logs
echo   status, ps     Show container status
echo   rebuild        Rebuild image without cache
echo   clean          Stop and remove containers/images
echo   help           Show this help message
echo.
echo Examples:
echo   %0              # Start server (foreground)
echo   %0 up -d        # Start server (background)
echo   %0 logs         # View logs
echo   %0 restart      # Restart server
echo   %0 clean        # Clean up everything
exit /b 0

:info
if "%2"=="-d" (
    echo.
    echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    echo ✅ Server is running!
    echo.
    echo WebSocket: ws://localhost:8080/ws
    echo Health:    http://localhost:8080/health
    echo Root:      http://localhost:8080/
    echo.
    echo View logs: %0 logs
    echo Stop:      %0 stop
    echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
)
:end

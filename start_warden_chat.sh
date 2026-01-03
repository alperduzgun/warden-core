#!/bin/bash

# Warden Chat Startup Script
# Automatically starts backend IPC server and CLI

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOCKET_PATH="/tmp/warden-ipc.sock"
BACKEND_LOG="/tmp/warden-backend.log"

echo "🛡️  Starting Warden Chat..."

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down Warden..."

    # Kill backend if running
    if [ -n "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi

    # Remove socket
    rm -f "$SOCKET_PATH"

    exit 0
}

trap cleanup EXIT INT TERM

# Check if backend is already running
if [ -S "$SOCKET_PATH" ]; then
    echo "⚠️  Backend socket exists. Cleaning up..."
    rm -f "$SOCKET_PATH"
fi

# Start backend in background
echo "🚀 Starting backend IPC server..."
cd "$SCRIPT_DIR"

# Ensure src is in PYTHONPATH if running from source
export PYTHONPATH=$PYTHONPATH:$(pwd)/src

python3 -m warden.services.ipc_entry > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Wait for socket to be created (max 5 seconds)
echo "⏳ Waiting for backend to start..."
for i in {1..50}; do
    if [ -S "$SOCKET_PATH" ]; then
        echo "✅ Backend ready!"
        break
    fi
    sleep 0.1

    if [ $i -eq 50 ]; then
        echo "❌ Backend failed to start. Check logs:"
        echo "   tail -f $BACKEND_LOG"
        exit 1
    fi
done

# Small delay to ensure backend is fully ready
sleep 0.5

# Start CLI
echo "🖥️  Starting CLI..."
cd "$SCRIPT_DIR/cli"

# Check if CLI is built
if [ ! -d "dist" ]; then
    echo "📦 Building CLI..."
    npm run build
fi

# Start CLI (this will block)
npm start

# Cleanup happens automatically via trap

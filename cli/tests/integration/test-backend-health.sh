#!/bin/bash

# Backend Health Check Integration Test
# This script ensures the backend is running before any CLI operation

set -e

BACKEND_PORT=6173
BACKEND_URL="http://localhost:${BACKEND_PORT}"
MAX_RETRIES=5
RETRY_DELAY=2

echo "🔍 Checking backend health..."

# Function to check backend health
check_backend() {
    curl -s "${BACKEND_URL}/health" > /dev/null 2>&1
    return $?
}

# Function to start backend
start_backend() {
    echo "🚀 Starting backend server..."
    cd /Users/alper/Documents/Development/Personal/warden-core
    python3 src/warden/cli_bridge/http_server.py > /tmp/warden-backend.log 2>&1 &
    BACKEND_PID=$!
    echo "   Backend PID: ${BACKEND_PID}"
    echo ${BACKEND_PID} > /tmp/warden-backend.pid
    sleep 3
}

# Function to kill existing backend processes
cleanup_backend() {
    echo "🧹 Cleaning up existing backend processes..."
    pkill -f "http_server.py" 2>/dev/null || true
    pkill -f "port ${BACKEND_PORT}" 2>/dev/null || true
    if [ -f /tmp/warden-backend.pid ]; then
        kill $(cat /tmp/warden-backend.pid) 2>/dev/null || true
        rm /tmp/warden-backend.pid
    fi
    sleep 1
}

# Main test logic
run_test() {
    local retries=0

    # First check if backend is already running
    if check_backend; then
        echo "✅ Backend is already running and healthy"
        return 0
    fi

    echo "⚠️  Backend is not running, attempting to start..."

    # Cleanup any stale processes
    cleanup_backend

    # Start backend
    start_backend

    # Wait for backend to be ready
    while [ $retries -lt $MAX_RETRIES ]; do
        if check_backend; then
            echo "✅ Backend is running and healthy"

            # Verify with actual health check
            HEALTH_RESPONSE=$(curl -s "${BACKEND_URL}/health")
            if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
                echo "✅ Health check passed: ${HEALTH_RESPONSE}"
                return 0
            fi
        fi

        retries=$((retries + 1))
        echo "   Retry ${retries}/${MAX_RETRIES} - Waiting ${RETRY_DELAY} seconds..."
        sleep ${RETRY_DELAY}
    done

    echo "❌ Failed to start backend after ${MAX_RETRIES} attempts"
    echo "📋 Backend logs:"
    tail -20 /tmp/warden-backend.log 2>/dev/null || echo "No logs available"
    return 1
}

# Run the test
run_test

exit $?
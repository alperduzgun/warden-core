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

# Function to check LLM status
check_llm_status() {
    echo ""
    echo "🤖 Checking LLM configuration..."

    # Check if .env file exists with Azure OpenAI credentials
    ENV_FILE="/Users/alper/Documents/Development/Personal/warden-core/.env"
    if [ -f "$ENV_FILE" ]; then
        if grep -q "AZURE_OPENAI_API_KEY" "$ENV_FILE" 2>/dev/null; then
            echo "  ✅ Azure OpenAI credentials found in .env"
        else
            echo "  ⚠️  No Azure OpenAI credentials in .env (LLM will use fallback)"
        fi
    else
        echo "  ⚠️  No .env file found (LLM will use fallback)"
    fi

    # Check if config has LLM enabled
    CONFIG_FILE="/Users/alper/Documents/Development/Personal/warden-core/.warden/config.yaml"
    if [ -f "$CONFIG_FILE" ]; then
        if grep -q "use_llm: true" "$CONFIG_FILE" 2>/dev/null; then
            echo "  ✅ LLM is enabled in config.yaml"
        else
            echo "  ⚠️  LLM not enabled in config.yaml"
        fi
    else
        echo "  ⚠️  No config.yaml found"
    fi

    # Test LLM service availability via backend
    echo "  🔄 Testing LLM service availability..."
    LLM_TEST=$(curl -s -X POST "${BACKEND_URL}/rpc" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"status","params":{},"id":1}' 2>/dev/null || echo "{}")

    if echo "$LLM_TEST" | grep -q "result"; then
        echo "  ✅ Backend RPC is responding"
    else
        echo "  ⚠️  Backend RPC not responding properly"
    fi

    echo ""
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

                # Check LLM configuration
                check_llm_status

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
#!/bin/bash

# Ensure backend is running before executing commands
# This wrapper prevents "fetch failed" errors

set -e

BACKEND_PORT=6173
BACKEND_URL="http://localhost:${BACKEND_PORT}"
PROJECT_ROOT="/Users/alper/Documents/Development/Personal/warden-core"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check backend
check_backend() {
    curl -s "${BACKEND_URL}/health" > /dev/null 2>&1
    return $?
}

# Function to start backend
start_backend() {
    echo -e "${YELLOW}🚀 Starting Warden backend...${NC}"
    cd "${PROJECT_ROOT}"
    python3 src/warden/cli_bridge/http_server.py > /tmp/warden-backend.log 2>&1 &
    local pid=$!
    echo $pid > /tmp/warden-backend.pid

    # Wait for backend to be ready
    local retries=0
    while [ $retries -lt 10 ]; do
        if check_backend; then
            echo -e "${GREEN}✅ Backend is ready${NC}"
            return 0
        fi
        sleep 1
        retries=$((retries + 1))
    done

    echo -e "${RED}❌ Backend failed to start${NC}"
    return 1
}

# Main logic
main() {
    if ! check_backend; then
        # Try to clean up any stale processes
        pkill -f "http_server.py" 2>/dev/null || true

        # Start backend
        if ! start_backend; then
            echo -e "${RED}Failed to start backend. Check logs at /tmp/warden-backend.log${NC}"
            exit 1
        fi
    fi

    # Backend is running, proceed with original command
    exec "$@"
}

main "$@"
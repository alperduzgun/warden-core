#!/bin/bash
# ============================================================================
# Warden gRPC Test Script (Postman Alternative)
#
# Usage:
#   ./test_grpc.sh              # Interactive menu
#   ./test_grpc.sh health       # Run specific test
#   ./test_grpc.sh all          # Run all tests
#   ./test_grpc.sh --help       # Show help
#
# Environment:
#   GRPC_HOST=localhost         # Server host
#   GRPC_PORT=50051             # Server port
# ============================================================================

set -e

# Configuration
HOST="${GRPC_HOST:-localhost}"
PORT="${GRPC_PORT:-50051}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROTO_PATH="$PROJECT_ROOT/src/warden/grpc/protos"
PROTO_FILE="$PROTO_PATH/warden.proto"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

check_grpcurl() {
    if ! command -v grpcurl &> /dev/null; then
        echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║  ERROR: grpcurl not found                                  ║${NC}"
        echo -e "${RED}╠════════════════════════════════════════════════════════════╣${NC}"
        echo -e "${RED}║  Install with:                                             ║${NC}"
        echo -e "${RED}║    macOS:   brew install grpcurl                           ║${NC}"
        echo -e "${RED}║    Linux:   go install github.com/fullstorydev/grpcurl/... ║${NC}"
        echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
        exit 1
    fi
}

check_server() {
    if ! nc -z "$HOST" "$PORT" 2>/dev/null; then
        echo -e "${YELLOW}⚠ Server not responding at $HOST:$PORT${NC}"
        echo -e "${YELLOW}  Start with: python start_grpc_server.py --port $PORT${NC}"
        return 1
    fi
    return 0
}

header() {
    echo ""
    echo -e "${BLUE}┌──────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${BLUE}│${NC} ${BOLD}$1${NC}"
    echo -e "${BLUE}├──────────────────────────────────────────────────────────────┤${NC}"
}

subheader() {
    echo -e "${CYAN}│ $1${NC}"
}

footer() {
    echo -e "${BLUE}└──────────────────────────────────────────────────────────────┘${NC}"
}

success() {
    echo -e "${GREEN}✓ $1${NC}"
}

error() {
    echo -e "${RED}✗ $1${NC}"
}

# Use reflection by default (no proto file needed)
USE_REFLECTION="${USE_REFLECTION:-true}"

grpc_call() {
    local method=$1
    local data=${2:-"{}"}

    if [ "$USE_REFLECTION" = "true" ]; then
        # Use server reflection (no proto file needed)
        grpcurl -plaintext \
            -d "$data" \
            "$HOST:$PORT" \
            "warden.WardenService/$method" 2>&1
    else
        # Use proto file
        grpcurl -plaintext \
            -import-path "$PROTO_PATH" \
            -proto warden.proto \
            -d "$data" \
            "$HOST:$PORT" \
            "warden.WardenService/$method" 2>&1
    fi
}

grpc_stream() {
    local method=$1
    local data=${2:-"{}"}

    if [ "$USE_REFLECTION" = "true" ]; then
        grpcurl -plaintext \
            -d "$data" \
            "$HOST:$PORT" \
            "warden.WardenService/$method" 2>&1
    else
        grpcurl -plaintext \
            -import-path "$PROTO_PATH" \
            -proto warden.proto \
            -d "$data" \
            "$HOST:$PORT" \
            "warden.WardenService/$method" 2>&1
    fi
}

# ============================================================================
# TEST FUNCTIONS
# ============================================================================

test_health() {
    header "HealthCheck"
    subheader "Request: {}"
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "HealthCheck" "{}")
    echo "$result" | sed 's/^/│   /'

    if echo "$result" | grep -q '"healthy": true'; then
        success "Server is healthy"
    else
        error "Health check failed"
    fi
    footer
}

test_status() {
    header "GetStatus"
    subheader "Request: {}"
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "GetStatus" "{}")
    echo "$result" | sed 's/^/│   /'

    if echo "$result" | grep -q '"running": true'; then
        success "Server is running"
    else
        error "Status check failed"
    fi
    footer
}

test_frames() {
    header "GetAvailableFrames"
    subheader "Request: {}"
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "GetAvailableFrames" "{}")
    echo "$result" | sed 's/^/│   /'

    frame_count=$(echo "$result" | grep -c '"id":' || echo "0")
    success "Found $frame_count frames"
    footer
}

test_providers() {
    header "GetAvailableProviders"
    subheader "Request: {}"
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "GetAvailableProviders" "{}")
    echo "$result" | sed 's/^/│   /'

    provider_count=$(echo "$result" | grep -c '"id":' || echo "0")
    success "Found $provider_count providers"
    footer
}

test_config() {
    header "GetConfiguration"
    subheader "Request: {}"
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "GetConfiguration" "{}")
    echo "$result" | sed 's/^/│   /'
    footer
}

test_pipeline() {
    local path="${1:-./src}"
    local frames="${2:-security}"

    header "ExecutePipeline"

    local request="{\"path\": \"$path\", \"frames\": [\"$frames\"], \"parallel\": true}"
    subheader "Request: $request"
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "ExecutePipeline" "$request")
    echo "$result" | sed 's/^/│   /'

    if echo "$result" | grep -q '"success": true'; then
        findings=$(echo "$result" | grep -o '"totalFindings": [0-9]*' | grep -o '[0-9]*' || echo "0")
        success "Pipeline completed with $findings findings"
    else
        error "Pipeline execution failed"
    fi
    footer
}

test_pipeline_stream() {
    local path="${1:-./src}"
    local frames="${2:-security}"

    header "ExecutePipelineStream (Server Streaming)"

    local request="{\"path\": \"$path\", \"frames\": [\"$frames\"]}"
    subheader "Request: $request"
    echo -e "${BLUE}│${NC}"
    subheader "Streaming Events:"

    grpc_stream "ExecutePipelineStream" "$request" | while read -r line; do
        echo -e "${CYAN}│   → $line${NC}"
    done

    success "Stream completed"
    footer
}

test_llm() {
    local code="${1:-def process(user_id):\n    query = f\"SELECT * FROM users WHERE id = {user_id}\"\n    return db.execute(query)}"
    local prompt="${2:-Identify security vulnerabilities}"

    header "AnalyzeWithLlm"

    local request=$(cat <<EOF
{
    "code": "$code",
    "prompt": "$prompt",
    "provider": "anthropic",
    "temperature": 0.7,
    "maxTokens": 1000
}
EOF
)
    subheader "Request:"
    echo "$request" | sed 's/^/│   /'
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "AnalyzeWithLlm" "$request")
    echo "$result" | sed 's/^/│   /'

    if echo "$result" | grep -q '"success": true'; then
        success "LLM analysis completed"
    else
        error "LLM analysis failed"
    fi
    footer
}

test_classify() {
    local code="${1:-import asyncio\nfrom fastapi import FastAPI\napp = FastAPI()}"
    local file_path="${2:-main.py}"

    header "ClassifyCode"

    local request="{\"code\": \"$code\", \"filePath\": \"$file_path\"}"
    subheader "Request: $request"
    echo -e "${BLUE}│${NC}"
    subheader "Response:"

    result=$(grpc_call "ClassifyCode" "$request")
    echo "$result" | sed 's/^/│   /'

    if echo "$result" | grep -q '"recommendedFrames"'; then
        success "Code classification completed"
    else
        error "Code classification failed"
    fi
    footer
}

list_services() {
    header "List Services (via Reflection)"
    subheader "Available services:"

    grpcurl -plaintext "$HOST:$PORT" list | sed 's/^/│   /'

    echo -e "${BLUE}│${NC}"
    subheader "Service methods:"

    grpcurl -plaintext "$HOST:$PORT" describe warden.WardenService | sed 's/^/│   /'

    footer
}

# ============================================================================
# RUN ALL TESTS
# ============================================================================

run_all() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║           WARDEN gRPC TEST SUITE                           ║${NC}"
    echo -e "${MAGENTA}╠════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${MAGENTA}║  Server: $HOST:$PORT                                       ${NC}"
    echo -e "${MAGENTA}║  Mode:   Server Reflection (auto-discovery)                ║${NC}"
    echo -e "${MAGENTA}╚════════════════════════════════════════════════════════════╝${NC}"

    if ! check_server; then
        exit 1
    fi

    test_health
    test_status
    test_frames
    test_providers
    test_config
    test_pipeline

    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✓ All tests completed successfully                        ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
}

# ============================================================================
# INTERACTIVE MENU
# ============================================================================

show_menu() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║           WARDEN gRPC TEST MENU                            ║${NC}"
    echo -e "${MAGENTA}╠════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${MAGENTA}║  Server: $HOST:$PORT                                       ${NC}"
    echo -e "${MAGENTA}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BOLD}Health & Status${NC}"
    echo "  1) HealthCheck          - Check server health"
    echo "  2) GetStatus            - Get runtime status"
    echo ""
    echo -e "${BOLD}Configuration${NC}"
    echo "  3) GetAvailableFrames   - List validation frames"
    echo "  4) GetAvailableProviders - List LLM providers"
    echo "  5) GetConfiguration     - Get full configuration"
    echo ""
    echo -e "${BOLD}Pipeline Operations${NC}"
    echo "  6) ExecutePipeline      - Run pipeline (sync)"
    echo "  7) ExecutePipelineStream - Run pipeline (streaming)"
    echo ""
    echo -e "${BOLD}LLM Operations${NC}"
    echo "  8) AnalyzeWithLlm       - Analyze code with LLM"
    echo "  9) ClassifyCode         - Classify code"
    echo ""
    echo -e "${BOLD}Other${NC}"
    echo "  l) List services        - List all gRPC services"
    echo "  a) Run all tests        - Run complete test suite"
    echo "  q) Quit"
    echo ""
    read -p "Select option: " choice

    case "$choice" in
        1) test_health ;;
        2) test_status ;;
        3) test_frames ;;
        4) test_providers ;;
        5) test_config ;;
        6) test_pipeline ;;
        7) test_pipeline_stream ;;
        8) test_llm ;;
        9) test_classify ;;
        l|L) list_services ;;
        a|A) run_all ;;
        q|Q) echo "Bye!"; exit 0 ;;
        *) echo -e "${RED}Invalid option${NC}" ;;
    esac

    echo ""
    read -p "Press Enter to continue..."
    show_menu
}

# ============================================================================
# HELP
# ============================================================================

show_help() {
    echo ""
    echo -e "${BOLD}Warden gRPC Test Script${NC}"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo -e "${BOLD}Commands:${NC}"
    echo "  (none)        Interactive menu"
    echo "  health        HealthCheck"
    echo "  status        GetStatus"
    echo "  frames        GetAvailableFrames"
    echo "  providers     GetAvailableProviders"
    echo "  config        GetConfiguration"
    echo "  pipeline      ExecutePipeline [path] [frame]"
    echo "  stream        ExecutePipelineStream [path] [frame]"
    echo "  llm           AnalyzeWithLlm"
    echo "  classify      ClassifyCode"
    echo "  list          List gRPC services"
    echo "  all           Run all tests"
    echo "  --help, -h    Show this help"
    echo ""
    echo -e "${BOLD}Examples:${NC}"
    echo "  $0                        # Interactive menu"
    echo "  $0 health                 # Quick health check"
    echo "  $0 pipeline ./src security"
    echo "  $0 all                    # Full test suite"
    echo ""
    echo -e "${BOLD}Environment:${NC}"
    echo "  GRPC_HOST       Server host (default: localhost)"
    echo "  GRPC_PORT       Server port (default: 50051)"
    echo "  USE_REFLECTION  Use server reflection (default: true)"
    echo ""
    echo -e "${BOLD}Requirements:${NC}"
    echo "  - grpcurl: brew install grpcurl"
    echo "  - Server:  python start_grpc_server.py --port 50051"
    echo ""
    echo -e "${BOLD}Server Reflection:${NC}"
    echo "  Server reflection is enabled by default."
    echo "  No proto file import needed - methods auto-discovered!"
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    # Show help without checking grpcurl
    case "${1:-menu}" in
        --help|-h)  show_help; exit 0 ;;
    esac

    check_grpcurl

    case "${1:-menu}" in
        health)     check_server && test_health ;;
        status)     check_server && test_status ;;
        frames)     check_server && test_frames ;;
        providers)  check_server && test_providers ;;
        config)     check_server && test_config ;;
        pipeline)   check_server && test_pipeline "${2:-./src}" "${3:-security}" ;;
        stream)     check_server && test_pipeline_stream "${2:-./src}" "${3:-security}" ;;
        llm)        check_server && test_llm ;;
        classify)   check_server && test_classify ;;
        list)       check_server && list_services ;;
        all)        run_all ;;
        menu)       check_server && show_menu ;;
        *)
            echo -e "${RED}Unknown command: $1${NC}"
            show_help
            exit 1
            ;;
    esac
}

main "$@"

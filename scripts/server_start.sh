#!/bin/bash
# ============================================================================
# Warden gRPC Server Starter
#
# Usage:
#   ./scripts/server_start.sh              # Start on default port 50051
#   ./scripts/server_start.sh 50052        # Start on custom port
#   ./scripts/server_start.sh --help       # Show help
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${1:-50051}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

show_help() {
    echo "Warden gRPC Server"
    echo ""
    echo "Usage: $0 [port]"
    echo ""
    echo "Arguments:"
    echo "  port    Server port (default: 50051)"
    echo ""
    echo "Examples:"
    echo "  $0              # Start on port 50051"
    echo "  $0 50052        # Start on port 50052"
    echo ""
    echo "Features:"
    echo "  - Server Reflection enabled (Postman auto-discovery)"
    echo "  - Async gRPC server"
    echo "  - All Warden services available"
}

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
    exit 0
fi

cd "$PROJECT_ROOT"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Warden gRPC Server${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Port:       ${GREEN}$PORT${NC}"
echo -e "  Reflection: ${GREEN}Enabled${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}Postman:${NC} New → gRPC Request → localhost:$PORT"
echo -e "${YELLOW}         Select 'Using server reflection'${NC}"
echo ""

# Activate venv if exists
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
fi

# Start server
export PYTHONPATH=$PYTHONPATH:$(pwd)/src
exec python -m warden.services.grpc_entry --port "$PORT"

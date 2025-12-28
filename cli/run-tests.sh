#!/bin/bash

# Warden CLI Test Runner
# Run before every deployment

set -e

echo "═══════════════════════════════════════════════════════════"
echo "            WARDEN CLI TEST RUNNER"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Change to CLI directory
cd "$(dirname "$0")"

# Step 1: Clean and build
echo -e "${BLUE}📦 Building CLI...${NC}"
npm run clean
npm run build

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Build failed!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Build successful${NC}"
echo ""

# Step 2: Run integration tests
echo -e "${BLUE}🧪 Running integration tests...${NC}"
npm run test:quick

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Integration tests failed!${NC}"
    echo -e "${RED}CLI is NOT ready for deployment.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✅ All tests passed!${NC}"
echo ""

# Step 3: Optional - Run in CI mode
if [ "$1" == "--ci" ]; then
    echo -e "${BLUE}🤖 Running CI validation...${NC}"

    # Check for uncommitted changes
    if [[ -n $(git status -s) ]]; then
        echo -e "${YELLOW}⚠️  Warning: Uncommitted changes detected${NC}"
    fi

    # Check Node version
    NODE_VERSION=$(node -v | cut -d'v' -f2)
    REQUIRED_VERSION="18.0.0"

    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$NODE_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
        echo -e "${RED}❌ Node version $NODE_VERSION is below required $REQUIRED_VERSION${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ CI validation passed${NC}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo -e "${GREEN}🚀 CLI IS READY FOR DEPLOYMENT! 🚀${NC}"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Commit your changes: git add . && git commit -m 'message'"
echo "  2. Push to repository: git push"
echo "  3. Deploy or publish: npm publish"
echo ""
#!/bin/bash

# Warden CLI Setup Verification Script
# Checks all required files and dependencies

set -e

echo "============================================"
echo "Warden CLI Setup Verification"
echo "============================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0

# Check function
check() {
    local name=$1
    local command=$2

    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $name"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} $name"
        ((FAILED++))
    fi
}

# Check file exists
check_file() {
    local name=$1
    local file=$2

    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $name"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} $name (missing: $file)"
        ((FAILED++))
    fi
}

# Check directory exists
check_dir() {
    local name=$1
    local dir=$2

    if [ -d "$dir" ]; then
        echo -e "${GREEN}✓${NC} $name"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} $name (missing: $dir)"
        ((FAILED++))
    fi
}

echo "Checking Prerequisites..."
echo "------------------------"
check "Node.js installed" "which node"
check "npm installed" "which npm"
check "Node.js version >= 18" "node -v | grep -E 'v(18|19|20|21|22)'"
echo ""

echo "Checking Project Structure..."
echo "-----------------------------"
check_file "package.json" "package.json"
check_file "tsconfig.json" "tsconfig.json"
check_file ".eslintrc.json" ".eslintrc.json"
check_file ".gitignore" ".gitignore"
check_file ".env.example" ".env.example"
check_file "README.md" "README.md"
echo ""

echo "Checking Source Files..."
echo "------------------------"
check_file "Entry point" "src/index.tsx"
check_file "Main app" "src/App.tsx"
check_file "Type definitions" "src/types/warden.d.ts"
check_file "API client" "src/api/client.ts"
check_file "Configuration" "src/config/index.ts"
echo ""

echo "Checking Components..."
echo "----------------------"
check_file "Header component" "src/components/Header.tsx"
check_file "ChatArea component" "src/components/ChatArea.tsx"
check_file "InputBox component" "src/components/InputBox.tsx"
check_file "Component exports" "src/components/index.ts"
echo ""

echo "Checking Utilities..."
echo "---------------------"
check_file "Logger" "src/utils/logger.ts"
check_file "Validation" "src/utils/validation.ts"
check_file "Utility exports" "src/utils/index.ts"
echo ""

echo "Checking Documentation..."
echo "-------------------------"
check_file "README" "README.md"
check_file "Quick Start" "QUICKSTART.md"
check_file "Contributing" "CONTRIBUTING.md"
check_file "Changelog" "CHANGELOG.md"
check_file "Project Summary" "PROJECT_SUMMARY.md"
echo ""

echo "Checking Scripts..."
echo "-------------------"
check_file "Dev script" "dev.sh"
check "Dev script executable" "test -x dev.sh"
echo ""

echo "Checking Dependencies..."
echo "------------------------"
if [ -f "package.json" ]; then
    check "Ink dependency" "grep -q '\"ink\"' package.json"
    check "React dependency" "grep -q '\"react\"' package.json"
    check "TypeScript dependency" "grep -q '\"typescript\"' package.json"
    check "Axios dependency" "grep -q '\"axios\"' package.json"
    check "Zod dependency" "grep -q '\"zod\"' package.json"
else
    echo -e "${RED}✗${NC} package.json not found"
    ((FAILED+=5))
fi
echo ""

echo "Checking Configuration Files..."
echo "-------------------------------"
if [ -f "tsconfig.json" ]; then
    check "TypeScript ES2022 target" "grep -q '\"target\": \"ES2022\"' tsconfig.json"
    check "TypeScript strict mode" "grep -q '\"strict\": true' tsconfig.json"
    check "TypeScript JSX react" "grep -q '\"jsx\": \"react\"' tsconfig.json"
else
    echo -e "${RED}✗${NC} tsconfig.json not found"
    ((FAILED+=3))
fi
echo ""

echo "Optional Checks..."
echo "------------------"
if [ -f ".env" ]; then
    echo -e "${GREEN}✓${NC} .env file exists"
else
    echo -e "${YELLOW}○${NC} .env file not created (use .env.example as template)"
fi

if [ -d "node_modules" ]; then
    echo -e "${GREEN}✓${NC} Dependencies installed"
else
    echo -e "${YELLOW}○${NC} Dependencies not installed (run: npm install)"
fi

if [ -d "dist" ]; then
    echo -e "${GREEN}✓${NC} Build output exists"
else
    echo -e "${YELLOW}○${NC} Project not built (run: npm run build)"
fi
echo ""

# Summary
echo "============================================"
echo "Summary"
echo "============================================"
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Copy .env.example to .env and configure"
    echo "2. Run: npm install"
    echo "3. Run: npm run build"
    echo "4. Run: npm start"
    echo ""
    exit 0
else
    echo -e "${RED}Some checks failed. Please review the errors above.${NC}"
    echo ""
    exit 1
fi

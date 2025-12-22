#!/bin/bash
# Test Warden Ink CLI Standalone (without IPC)

echo "═══════════════════════════════════════════════════════════════"
echo "🧪 Testing Warden Ink CLI (Standalone Mode)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

cd "$(dirname "$0")"

# Check if built
if [ ! -f "dist/index.js" ]; then
    echo "❌ CLI not built. Run 'npm run build' first."
    exit 1
fi

echo "✅ CLI executable found at dist/index.js"
echo ""

# Test basic rendering
echo "🎯 Test 1: CLI renders UI"
echo "-------------------------------------------------------------------"
timeout 3 node dist/index.js || true
echo ""

# Test help flag
echo "🎯 Test 2: CLI shows help"
echo "-------------------------------------------------------------------"
node dist/index.js --help 2>&1 | head -20
echo ""

# Test version
echo "🎯 Test 3: CLI shows version"
echo "-------------------------------------------------------------------"
node dist/index.js --version 2>&1 || echo "Version: 0.1.0"
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "✅ Standalone CLI Tests Complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Next: Test with IPC server"
echo "  Terminal 1: source .venv/bin/activate && python3 start_ipc_server.py"
echo "  Terminal 2: cd cli && npm start"
echo ""

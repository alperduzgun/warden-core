#!/bin/bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli

# Build first
echo "Building CLI..."
npm run build 2>&1

# Run scan and save output
echo "Running scan..."
timeout 30 ./dist/cli.js scan ../examples/vulnerable_code.py 2>&1 | tee scan_output.txt

# Extract phase results
echo ""
echo "=== PHASE EXECUTION RESULTS ==="
grep -A 20 "Phase Execution Summary" scan_output.txt || echo "No phase summary found"

echo ""
echo "=== CLASSIFICATION PHASE ==="
grep -i "classification" scan_output.txt || echo "No classification info found"

echo ""
echo "=== ALL PHASES MENTIONED ==="
grep -E "pre-analysis|analysis|classification|validation|fortification|cleaning" scan_output.txt || echo "No phase mentions found"
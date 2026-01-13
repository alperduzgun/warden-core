#!/bin/bash
# Code complexity validation script
#
# This script checks if a file has too many lines (simple complexity check).
#
# Usage: ./check_complexity.sh <file_path>
# Exit codes:
#   0 - Complexity is acceptable
#   1 - File is too complex

FILE="$1"
MAX_LINES=1000  # Max lines per file

if [ ! -f "$FILE" ]; then
    echo "File not found: $FILE"
    exit 1
fi

# Count lines (excluding blank lines)
LINE_COUNT=$(grep -cv '^[[:space:]]*$' "$FILE" || true)

if [ "$LINE_COUNT" -gt "$MAX_LINES" ]; then
    echo "File too complex: ${LINE_COUNT} lines (max ${MAX_LINES}). Consider refactoring into smaller modules."
    exit 1
fi

exit 0

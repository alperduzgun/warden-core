#!/bin/bash
# TODO/FIXME validation script
#
# This script checks if a file contains TODO or FIXME comments.
# Useful for blocking deployments when unfinished work exists.
#
# Usage: ./check_no_todos.sh <file_path>
# Exit codes:
#   0 - No TODO/FIXME found
#   1 - TODO/FIXME found

FILE="$1"

if [ ! -f "$FILE" ]; then
    echo "File not found: $FILE"
    exit 1
fi

# Search for TODO or FIXME (case insensitive)
TODO_COUNT=$(grep -ci -E "TODO|FIXME" "$FILE" || true)

if [ "$TODO_COUNT" -gt 0 ]; then
    echo "Found ${TODO_COUNT} TODO/FIXME comment(s). Complete or remove before deployment."
    # Show the first TODO/FIXME
    FIRST_TODO=$(grep -in -E "TODO|FIXME" "$FILE" | head -1)
    echo "First occurrence: $FIRST_TODO"
    exit 1
fi

exit 0

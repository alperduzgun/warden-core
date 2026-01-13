#!/bin/bash
# File size validation script
#
# This script checks if a file exceeds a maximum size limit.
#
# Usage: ./check_file_size.sh <file_path>
# Exit codes:
#   0 - File size is acceptable
#   1 - File size exceeds limit

FILE="$1"
MAX_SIZE_KB=500  # 500 KB max

if [ ! -f "$FILE" ]; then
    echo "File not found: $FILE"
    exit 1
fi

# Get file size in KB
FILE_SIZE=$(du -k "$FILE" | cut -f1)

if [ "$FILE_SIZE" -gt "$MAX_SIZE_KB" ]; then
    echo "File too large: ${FILE_SIZE}KB (max ${MAX_SIZE_KB}KB). Consider splitting or optimizing."
    exit 1
fi

exit 0

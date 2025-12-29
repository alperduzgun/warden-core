#!/bin/bash
# Test interactive scan command
cd /Users/alper/Documents/Development/Personal/warden-core

# Start warden in interactive mode and send scan command
echo -e "/scan examples/vulnerable_code.py\n" | timeout 10 warden-cli 2>&1 | head -100
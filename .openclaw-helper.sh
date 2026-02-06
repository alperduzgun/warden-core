#!/bin/bash
# OpenClaw Helper Script for Warden Core
# Ensures OpenClaw runs with correct Node version

# Direct path to OpenClaw with Node 22
NODE22="/opt/homebrew/opt/node@22/bin/node"
OPENCLAW_SCRIPT="/Users/alper/.nvm/versions/node/v20.19.5/lib/node_modules/openclaw/openclaw.mjs"

# Run openclaw with all arguments
"$NODE22" "$OPENCLAW_SCRIPT" "$@"

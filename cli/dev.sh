#!/bin/bash

# Warden CLI Development Runner
# This script sets up the development environment and runs the CLI

set -e

echo "Starting Warden CLI in development mode..."

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Copy .env.example if .env doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Please configure .env with your settings"
fi

# Run the CLI
npm run dev

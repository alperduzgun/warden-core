#!/bin/bash
set -e

echo "🦀 Setting up Warden Core Development Environment..."

# 1. Check for Rust
if ! command -v cargo &> /dev/null; then
    echo "❌ Rust toolchain not found!"
    echo "👉 Please install it: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi

echo "✅ Rust toolchain found."

# 2. Check for Python venv
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "⚠️  No virtual environment found. Creating one..."
    python3 -m venv .venv
    source .venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    source venv/bin/activate
fi

# 3. Upgrade pip and build tools
echo "📦 Upgrading pip and build tools..."
pip install --upgrade pip setuptools wheel setuptools-rust

# 4. Install Warden in Editable Mode
echo "🚀 Installing Warden Core (with Rust extension)..."
pip install -e ".[dev]"

echo "✅ Installation Complete!"
echo "👉 Run 'warden scan' to test."

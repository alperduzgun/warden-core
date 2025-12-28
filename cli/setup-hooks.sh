#!/bin/bash

# Setup git hooks for Warden CLI

echo "🔧 Setting up git hooks for Warden CLI..."

# Get the git directory
GIT_DIR=$(git rev-parse --git-dir)

# Create symlink to pre-commit hook
ln -sf "../../cli/.git-hooks/pre-commit" "$GIT_DIR/hooks/pre-commit"

echo "✅ Git hooks installed successfully!"
echo ""
echo "Pre-commit hook will now:"
echo "  • Run integration tests when CLI files are changed"
echo "  • Prevent commits if tests fail"
echo ""
echo "To skip hooks (not recommended):"
echo "  git commit --no-verify"
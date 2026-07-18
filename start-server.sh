#!/bin/bash
# LLM Keypool startup script
# Run this to start the server in the background

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if frontend is built
if [ ! -d "web/dist" ]; then
    echo "Building frontend..."
    cd frontend
    npm run build
    cd ..
fi

# Start server
echo "Starting LLM Keypool server..."
exec llm-apipool proxy --port 8000 --host 0.0.0.0

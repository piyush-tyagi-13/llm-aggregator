#!/usr/bin/env bash
set -euo pipefail

# llm-apipool — one-line install script
# Usage: curl -fsSL https://raw.githubusercontent.com/GFardad/llm-apipool/main/install.sh | bash
#
# Sets up ~/.llm-apipool, generates an encryption key, and starts the container.

REPO="GFardad/llm-apipool"
DIR="${FREELLMAPI_DIR:-$HOME/.llm-apipool}"
PORT="${PORT:-8000}"
HOST_BIND="${HOST_BIND:-127.0.0.1}"

echo "==> llm-apipool installer"
echo "    Directory: $DIR"
echo "    Port:      $PORT"
echo "    Bind:      $HOST_BIND"

# Create directory structure
mkdir -p "$DIR"

# Generate encryption key if not present
ENCRYPTION_KEY_FILE="$DIR/encryption.key"
if [ ! -f "$ENCRYPTION_KEY_FILE" ]; then
    echo "==> Generating encryption key..."
    openssl rand -hex 32 > "$ENCRYPTION_KEY_FILE"
    chmod 600 "$ENCRYPTION_KEY_FILE"
    echo "    Key saved to $ENCRYPTION_KEY_FILE"
fi

ENCRYPTION_KEY=$(cat "$ENCRYPTION_KEY_FILE")

# Pull and run with Docker
if command -v docker &> /dev/null; then
    echo "==> Pulling latest image..."
    docker pull "ghcr.io/$REPO:latest"

    echo "==> Starting container..."
    docker run -d \
        --name llm-apipool \
        --restart unless-stopped \
        -p "$HOST_BIND:$PORT:8000" \
        -e LLM_APIPOOL_ENCRYPTION_KEY="$ENCRYPTION_KEY" \
        -e LLM_APIPOOL_API_KEY="${LLM_APIPOOL_API_KEY:-}" \
        -v "$DIR:/data" \
        "ghcr.io/$REPO:latest"

    echo "==> llm-apipool is running at http://$HOST_BIND:$PORT"
    echo "    Open the dashboard in your browser and register your API keys."
    echo "    To view logs: docker logs -f llm-apipool"
    echo "    To stop:      docker stop llm-apipool"
else
    echo "==> Docker not found. Install with pip instead:"
    echo "    pip install llm-apipool[all]"
    echo "    llm-apipool proxy --port $PORT"
fi

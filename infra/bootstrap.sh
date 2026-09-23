#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if ! command -v git >/dev/null 2>&1; then
  echo "[ERROR] git is required."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] Docker is required."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[ERROR] Docker Compose v2 is required."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[INFO] Created infra/local/.env from .env.example"
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

SKYVERN_VERSION="${SKYVERN_VERSION:-v1.0.48}"
RUNTIME_DIR="$HERE/.runtime/skyvern"

mkdir -p "$HERE/.runtime"

if [[ ! -d "$RUNTIME_DIR/.git" ]]; then
  echo "[INFO] Cloning Skyvern ${SKYVERN_VERSION}..."
  git clone \
    --depth 1 \
    --branch "$SKYVERN_VERSION" \
    https://github.com/Skyvern-AI/skyvern.git \
    "$RUNTIME_DIR"
else
  echo "[INFO] Skyvern checkout already exists."
  current="$(git -C "$RUNTIME_DIR" describe --tags --exact-match 2>/dev/null || true)"

  if [[ "$current" != "$SKYVERN_VERSION" ]]; then
    echo "[INFO] Switching Skyvern checkout to ${SKYVERN_VERSION}..."
    git -C "$RUNTIME_DIR" fetch --depth 1 origin "refs/tags/${SKYVERN_VERSION}:refs/tags/${SKYVERN_VERSION}"
    git -C "$RUNTIME_DIR" checkout --detach "$SKYVERN_VERSION"
  fi
fi

mkdir -p \
  artifacts \
  videos \
  har \
  log \
  downloads \
  browser_sessions \
  credential_vault \
  .skyvern

echo "[INFO] Skyvern source: $RUNTIME_DIR"
echo "[INFO] Skyvern version: $(git -C "$RUNTIME_DIR" describe --tags --always)"
echo "[INFO] Ollama model: ${OLLAMA_MODEL:-gemma4:e4b}"

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "[INFO] NVIDIA GPU detected on host:"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true

  if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -qi nvidia; then
    echo "[INFO] NVIDIA Docker runtime detected."
  else
    echo "[WARN] NVIDIA Docker runtime was not detected."
    echo "       Install/configure NVIDIA Container Toolkit before starting Ollama with GPU."
  fi
else
  echo "[WARN] nvidia-smi not found. Ollama GPU acceleration will not be available."
fi

echo
echo "Bootstrap complete."
echo "Next:"
echo "  make up"

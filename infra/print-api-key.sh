#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDENTIALS="$HERE/.skyvern/credentials.toml"

if [[ ! -f "$CREDENTIALS" ]]; then
  echo "[ERROR] $CREDENTIALS does not exist yet."
  echo "Start Skyvern first with: make up"
  exit 1
fi

key="$(sed -n 's/.*cred[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$CREDENTIALS" | head -n 1)"

if [[ -z "$key" ]]; then
  echo "[ERROR] No generated API key found in $CREDENTIALS"
  exit 1
fi

echo "$key"

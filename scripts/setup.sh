#!/usr/bin/env bash
# One-time local setup (Git Bash on Windows). Keeps everything inside the repo:
# uv cache -> tools/uv-cache (pyproject [tool.uv]), downloaded Pythons -> tools/python.
set -euo pipefail
cd "$(dirname "$0")/.."

export UV_PYTHON_INSTALL_DIR="$PWD/tools/python"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; installing into ./tools/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=./tools/bin UV_NO_MODIFY_PATH=1 sh
  export PATH="$PWD/tools/bin:$PATH"
fi

uv venv .venv --python 3.12 --allow-existing
uv sync

[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example; fill in MONGODB_URI."; }
echo "Done. Run: uv run uvicorn backend.app.main:app --reload"

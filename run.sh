#!/usr/bin/env bash
# Jalankan Netflix NFToken Generator
set -e
cd "$(dirname "$0")"
PORT="${1:-8899}"
echo "🎬 Netflix NFToken Generator -> http://0.0.0.0:${PORT}"
exec python3 -m uvicorn app:app --host 0.0.0.0 --port "${PORT}"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
python3 -m uvicorn main:app --host 127.0.0.1 --port 8100 --reload

#!/bin/sh
set -eu

export TEACHAGENT_HOST="${TEACHAGENT_HOST:-0.0.0.0}"
export TEACHAGENT_PORT="${TEACHAGENT_PORT:-8000}"

python app/server.py

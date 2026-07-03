#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m pip install -r app/requirements-desktop.txt

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name TeachAgent \
  --paths "$ROOT" \
  --paths "$ROOT/app" \
  --add-data "app/static:app/static" \
  --add-data "app/data:app/data" \
  --add-data "docs/rag_inventory:docs/rag_inventory" \
  --add-data "docs/rag_samples:docs/rag_samples" \
  --add-data "scratch/student_annotation_merged:scratch/student_annotation_merged" \
  --add-data "scratch/teachagent_system_overview:scratch/teachagent_system_overview" \
  app/desktop_app.py

echo
echo "Build complete:"
echo "  dist/TeachAgent.app"

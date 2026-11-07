#!/usr/bin/env bash
# ==============================================================================
# ChromaDB Installation & Vector Database Setup Script (saved at src/chromadb/)
# Installs chromadb if missing and initializes the vector database at
# src/chromadb/chroma_data, ingesting 2025 and 2026 fraud policy documents.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${SCRIPT_DIR}/chroma_data"
POLICY_DIR="${PROJECT_ROOT}/docs/policy-docs"

echo "🔧 Checking ChromaDB installation..."
if ! python3 -c "import chromadb" >/dev/null 2>&1; then
  echo "📥 Installing chromadb package..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install "chromadb>=0.5.0"
  else
    python3 -m pip install "chromadb>=0.5.0"
  fi
fi

if python3 -c "import chromadb" >/dev/null 2>&1; then
  CHROMA_VER=$(python3 -c "import chromadb; print(chromadb.__version__)")
  echo "✅ ChromaDB package verified (version: ${CHROMA_VER})"
fi

echo "🗄️  Initializing ChromaDB Vector Database at ${DATA_DIR}..."
PYTHONPATH="${PROJECT_ROOT}/src" python3 "${SCRIPT_DIR}/install_chromadb.py" \
  --persist-dir "${DATA_DIR}" \
  --policy-dir "${POLICY_DIR}"

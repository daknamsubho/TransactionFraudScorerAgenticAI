#!/usr/bin/env bash
# ==============================================================================
# SQLite Installation & Database Setup Script (saved at src/sqllite/)
# Installs sqlite3 CLI if missing (e.g. in Google Colab / Ubuntu) and initializes
# the RDBMS schema at src/sqllite/fraud_scorer.db from docs/rdbms-model-schema/schema.sql
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SCHEMA_FILE="${PROJECT_ROOT}/docs/rdbms-model-schema/schema.sql"
DB_FILE="${SCRIPT_DIR}/fraud_scorer.db"

echo "🔧 Checking SQLite installation..."
if ! command -v sqlite3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "📥 Installing sqlite3 and libsqlite3-dev..."
    apt-get update -qq && apt-get install -y -qq sqlite3 libsqlite3-dev
  fi
fi

if command -v sqlite3 >/dev/null 2>&1; then
  echo "✅ sqlite3 CLI version: $(sqlite3 --version)"
fi

echo "🗄️  Initializing SQLite database at ${DB_FILE} using ${SCHEMA_FILE}..."
PYTHONPATH="${PROJECT_ROOT}/src" python3 -m sqllite.install_sqlite --db-path "${DB_FILE}"

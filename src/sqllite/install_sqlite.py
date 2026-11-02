"""SQLite installation and database initialization helper under src/sqllite."""

import argparse
import platform
import shutil
import sqlite3
import subprocess
from pathlib import Path

from sqllite.database import DEFAULT_DB_PATH, SCHEMA_SQL_PATH, get_connection, init_db


def install_and_setup_sqlite(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, object]:
    """Ensure SQLite is installed and initialize the RDBMS schema at src/sqllite/fraud_scorer.db.

    Args:
        db_path: Target path for the SQLite database file (defaults to src/sqllite/fraud_scorer.db).

    Returns:
        Dictionary containing SQLite version, database path, schema path, and created table names.
    """
    if shutil.which("sqlite3") is None and platform.system().lower() == "linux" and shutil.which("apt-get"):
        subprocess.run(
            ["apt-get", "update", "-qq"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["apt-get", "install", "-y", "-qq", "sqlite3", "libsqlite3-dev"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    resolved_db = init_db(db_path)

    with get_connection(resolved_db) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        tables = [str(row["name"]) for row in cursor.fetchall()]

    return {
        "sqlite_version": sqlite3.sqlite_version,
        "db_path": str(resolved_db),
        "schema_path": str(SCHEMA_SQL_PATH),
        "tables": tables,
    }


def main() -> None:
    """CLI entrypoint for initializing the SQLite RDBMS database."""
    parser = argparse.ArgumentParser(description="Install & initialize SQLite RDBMS for Fraud Scorer.")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to SQLite DB file (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    info = install_and_setup_sqlite(args.db_path)
    print(f"✅ SQLite {info['sqlite_version']} initialized at: {info['db_path']}")
    print(f"📋 Tables created: {', '.join(info['tables']) if isinstance(info['tables'], list) else info['tables']}")


if __name__ == "__main__":
    main()

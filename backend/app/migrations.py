from __future__ import annotations

from pathlib import Path

from .database import connect


DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def run_migrations(migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR) -> list[str]:
    directory = Path(migrations_dir)
    if not directory.exists():
        return []

    applied: list[str] = []
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        known = {str(row["version"]) for row in rows}

        for path in sorted(directory.glob("*.sql")):
            version = path.name
            if version in known:
                continue
            sql = path.read_text(encoding="utf-8").strip()
            if sql:
                conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(version)
    return applied


if __name__ == "__main__":
    from .database import init_schema

    init_schema()
    applied_versions = run_migrations()
    if applied_versions:
        print("Applied migrations: " + ", ".join(applied_versions))
    else:
        print("No pending migrations.")

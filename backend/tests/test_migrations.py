from pathlib import Path

from backend.app import migrations


class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, applied=None):
        self.applied = applied or []
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append({"sql": sql, "params": params})
        if "SELECT version FROM schema_migrations" in sql:
            return _FakeCursor([{"version": version} for version in self.applied])
        return _FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_run_migrations_applies_only_new_sql_files(monkeypatch, tmp_path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_existing.sql").write_text("SELECT 1;", encoding="utf-8")
    (migrations_dir / "0002_new.sql").write_text("ALTER TABLE example ADD COLUMN name TEXT;", encoding="utf-8")
    conn = _FakeConn(applied=["0001_existing.sql"])
    monkeypatch.setattr(migrations, "connect", lambda: conn)

    applied = migrations.run_migrations(migrations_dir=migrations_dir)

    assert applied == ["0002_new.sql"]
    sql_text = "\n".join(call["sql"] for call in conn.executed)
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in sql_text
    assert "ALTER TABLE example ADD COLUMN name TEXT;" in sql_text
    assert any(call["params"] == ("0002_new.sql",) for call in conn.executed)


def test_run_migrations_is_noop_when_all_versions_are_recorded(monkeypatch, tmp_path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_existing.sql").write_text("SELECT 1;", encoding="utf-8")
    conn = _FakeConn(applied=["0001_existing.sql"])
    monkeypatch.setattr(migrations, "connect", lambda: conn)

    applied = migrations.run_migrations(migrations_dir=migrations_dir)

    assert applied == []
    assert not any(call["sql"] == "SELECT 1;" for call in conn.executed)

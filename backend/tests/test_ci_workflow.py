from pathlib import Path


def test_ci_workflow_runs_backend_and_frontend_checks():
    workflow = Path(".github/workflows/ci.yml")

    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")

    assert "python -m backend.app.migrations" in content
    assert "python -m pytest backend/tests -q" in content
    assert "python -m compileall -q backend tools" in content
    assert "npm run build" in content
    assert "postgres:" in content
    assert "redis:" in content

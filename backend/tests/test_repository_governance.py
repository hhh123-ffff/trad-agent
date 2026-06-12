from pathlib import Path


def test_repository_governance_docs_cover_pr_and_branch_protection():
    pr_template = Path(".github/pull_request_template.md")
    branch_protection = Path("docs/operations/branch-protection.md")

    assert pr_template.exists()
    assert branch_protection.exists()

    pr_text = pr_template.read_text(encoding="utf-8")
    branch_text = branch_protection.read_text(encoding="utf-8")

    assert "## Summary" in pr_text
    assert "## Validation" in pr_text
    assert "## Compliance Boundary" in pr_text
    assert "python -m pytest backend/tests -q" in pr_text
    assert "npm run build" in pr_text

    assert "Require a pull request before merging" in branch_text
    assert "Require status checks to pass before merging" in branch_text
    assert "Backend and frontend checks" in branch_text
    assert "Block force pushes" in branch_text

from pathlib import Path


def test_repository_governance_docs_cover_pr_and_branch_protection():
    pr_template = Path(".github/pull_request_template.md")
    branch_protection = Path("docs/operations/branch-protection.md")

    assert pr_template.exists()
    assert branch_protection.exists()

    pr_text = pr_template.read_text(encoding="utf-8")
    branch_text = branch_protection.read_text(encoding="utf-8")

    assert "## 变更摘要" in pr_text
    assert "## 验证" in pr_text
    assert "## 合规边界" in pr_text
    assert "python -m pytest backend/tests -q" in pr_text
    assert "npm run build" in pr_text

    assert "合并前必须创建 Pull Request" in branch_text
    assert "合并前必须通过状态检查" in branch_text
    assert "后端与前端检查" in branch_text
    assert "禁止强制推送" in branch_text

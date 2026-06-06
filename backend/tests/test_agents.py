from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from backend.app.agent_service import LLMCompletion, PostMarketAgentService
from backend.app.agent_context import build_post_market_agent_context
from backend.app.agent_repository import PostgresAgentRepository, apply_agent_action
from backend.app.llm_client import OpenAICompatibleClient
from backend.app import main as main_module
from backend.app.database import connect
from backend.app.main import app
from backend.app.models import AgentAction, AgentArtifact, AgentRun, AgentStep, LLMUsage
from backend.app.research_agent import create_research_answer


def _context() -> dict[str, Any]:
    return {
        "trading_day": "2026-06-05",
        "data_quality": {"warnings": [], "snapshot_count": 3},
        "information": {"announcement_count": 2, "news_count": 1, "warnings": []},
        "candidates": [
            {
                "symbol": "600000.SH",
                "name": "Test Bank",
                "stage": "launch",
                "total_score": 82,
                "evidence": ["volume expanded"],
                "risks": [],
                "source_ids": ["src-test"],
            }
        ],
        "observations": [{"symbol": "000001.SZ", "status": "watching"}],
        "report": {
            "headline": "Daily market analysis",
            "summary": "Structured deterministic summary.",
            "sections": [],
        },
        "source_ids": ["src-test"],
    }


class MemoryRepository:
    def __init__(self, daily_calls: int = 0):
        self.daily_calls = daily_calls
        self.runs: list[AgentRun] = []
        self.steps: list[AgentStep] = []
        self.artifacts: list[AgentArtifact] = []
        self.actions: list[AgentAction] = []
        self.usage: list[LLMUsage] = []

    def create_run(self, workflow: str, trigger: str) -> AgentRun:
        now = datetime.now(timezone.utc)
        run = AgentRun(
            id=f"run-{len(self.runs) + 1}",
            workflow=workflow,
            status="running",
            trigger=trigger,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.runs.append(run)
        return run

    def finish_run(self, run_id: str, status: str, summary: str, error: str | None, calls_used: int, tokens_used: int) -> AgentRun:
        current = next(run for run in self.runs if run.id == run_id)
        finished = current.model_copy(
            update={
                "status": status,
                "summary": summary,
                "error": error,
                "calls_used": calls_used,
                "tokens_used": tokens_used,
                "finished_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.runs[self.runs.index(current)] = finished
        return finished

    def save_step(self, step: AgentStep) -> AgentStep:
        self.steps.append(step)
        return step

    def save_artifact(self, artifact: AgentArtifact) -> AgentArtifact:
        self.artifacts.append(artifact)
        return artifact

    def create_action(self, action: AgentAction) -> AgentAction:
        self.actions.append(action)
        return action

    def save_usage(self, usage: LLMUsage) -> LLMUsage:
        self.usage.append(usage)
        return usage

    def daily_calls_used(self) -> int:
        return self.daily_calls + len(self.usage)


class FakeLLM:
    def __init__(self, responses: dict[str, dict[str, Any]] | None = None, *, configured: bool = True):
        self.configured = configured
        self.responses = responses or {}
        self.calls: list[str] = []

    def complete(self, agent_name: str, payload: dict[str, Any]) -> LLMCompletion:
        self.calls.append(agent_name)
        response = self.responses.get(agent_name)
        if response is None:
            raise ValueError(f"missing fake response for {agent_name}")
        return LLMCompletion(
            data=response,
            model="fake-model",
            prompt_tokens=30,
            completion_tokens=20,
            latency_ms=5,
        )


def _valid_responses() -> dict[str, dict[str, Any]]:
    return {
        "AnnouncementAnalystAgent": {
            "summary": "Announcements were grouped by symbol and importance.",
            "evidence": ["2 announcements"],
            "warnings": [],
        },
        "CandidateResearchAgent": {
            "summary": "One candidate retained deterministic rule support.",
            "evidence": ["600000.SH score 82"],
            "warnings": [],
        },
        "ObservationManagerAgent": {
            "summary": "Observation changes prepared.",
            "actions": [
                {
                    "type": "upsert_observation",
                    "symbol": "600000.SH",
                    "reason": "Rule score remains supported.",
                    "next_focus": "Review next close.",
                },
                {
                    "type": "remove_observation",
                    "symbol": "000001.SZ",
                    "reason": "No longer in current candidates.",
                },
            ],
        },
        "ReportEditorAgent": {
            "title": "Post-market research brief",
            "summary": "Facts, candidates, and data gaps were consolidated.",
            "sections": [{"title": "Candidates", "summary": "One candidate requires follow-up."}],
            "warnings": [],
        },
    }


def test_workflow_degrades_to_deterministic_artifact_without_llm():
    repository = MemoryRepository()
    service = PostMarketAgentService(repository, FakeLLM(configured=False), _context)

    run = service.run(trigger="test")

    assert run.status == "degraded"
    assert run.calls_used == 0
    assert repository.artifacts[-1].artifact_type == "deterministic_fallback"
    assert repository.artifacts[-1].content["report"]["headline"] == "Daily market analysis"


def test_workflow_records_steps_usage_artifact_and_controlled_actions():
    repository = MemoryRepository()
    observed: list[dict[str, str]] = []
    service = PostMarketAgentService(
        repository,
        FakeLLM(_valid_responses()),
        _context,
        observation_writer=lambda **payload: observed.append(payload),
    )

    run = service.run(trigger="test")

    assert run.status == "completed"
    assert run.calls_used == 4
    assert len(repository.usage) == 4
    assert repository.artifacts[-1].artifact_type == "post_market_brief"
    assert {step.agent_name for step in repository.steps} == {
        "DataQualityAgent",
        "AnnouncementAnalystAgent",
        "CandidateResearchAgent",
        "ObservationManagerAgent",
        "ReportEditorAgent",
        "ComplianceGuard",
    }
    assert observed == [
        {
            "symbol": "600000.SH",
            "reason": "Rule score remains supported.",
            "next_focus": "Review next close.",
        }
    ]
    assert repository.actions[-1].action_type == "remove_observation"
    assert repository.actions[-1].status == "pending"


def test_workflow_degrades_when_model_output_is_invalid():
    responses = _valid_responses()
    responses.pop("ReportEditorAgent")
    repository = MemoryRepository()
    service = PostMarketAgentService(repository, FakeLLM(responses), _context)

    run = service.run(trigger="test")

    assert run.status == "degraded"
    assert run.calls_used == 4
    assert len(repository.usage) == 4
    assert repository.usage[-1].success is False
    assert repository.artifacts[-1].artifact_type == "deterministic_fallback"
    assert "ReportEditorAgent" in (run.error or "")


def test_workflow_stops_before_call_when_daily_budget_is_exhausted():
    repository = MemoryRepository(daily_calls=20)
    llm = FakeLLM(_valid_responses())
    service = PostMarketAgentService(repository, llm, _context, daily_call_limit=20)

    run = service.run(trigger="test")

    assert run.status == "degraded"
    assert llm.calls == []
    assert run.calls_used == 0


def test_compliance_guard_replaces_non_compliant_model_brief():
    responses = _valid_responses()
    responses["ReportEditorAgent"]["summary"] = "建议买入并设置目标价。"
    repository = MemoryRepository()
    service = PostMarketAgentService(repository, FakeLLM(responses), _context)

    run = service.run(trigger="test")

    assert run.status == "degraded"
    assert repository.artifacts[-1].artifact_type == "deterministic_fallback"
    assert "compliance" in (run.error or "").lower()


def test_compliance_guard_blocks_observation_actions_before_they_are_applied():
    responses = _valid_responses()
    responses["ObservationManagerAgent"]["actions"][0]["reason"] = "建议买入并加仓。"
    repository = MemoryRepository()
    observed: list[dict[str, str]] = []
    service = PostMarketAgentService(
        repository,
        FakeLLM(responses),
        _context,
        observation_writer=lambda **payload: observed.append(payload),
    )

    run = service.run(trigger="test")

    assert run.status == "degraded"
    assert observed == []
    assert repository.actions == []


def test_openai_compatible_client_parses_fenced_json(monkeypatch):
    captured: dict[str, Any] = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "```json\n{\"summary\":\"ok\",\"evidence\":[]}\n```"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                "model": "compatible-model",
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return Response()

    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    client = OpenAICompatibleClient(base_url="http://model.local/v1", api_key="secret", model="compatible-model")

    result = client.complete("CandidateResearchAgent", {"candidates": [{"symbol": "600000.SH"}]})

    assert result.data["summary"] == "ok"
    assert result.prompt_tokens == 12
    assert captured["url"] == "http://model.local/v1/chat/completions"
    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_openai_compatible_client_rejects_non_json_content(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "not-json"}}], "model": "compatible-model"}

    monkeypatch.setattr("backend.app.llm_client.requests.post", lambda *args, **kwargs: Response())
    client = OpenAICompatibleClient(base_url="http://model.local/v1", api_key="secret", model="compatible-model")

    try:
        client.complete("ReportEditorAgent", {"report": {}})
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("non-JSON model output must be rejected")


def test_agent_context_exposes_only_bounded_structured_facts(monkeypatch):
    class Dumpable:
        def __init__(self, **values):
            self.values = values

        def model_dump(self, mode="json"):
            return self.values

    report = Dumpable(
        trading_day="2026-06-05",
        headline="Daily analysis",
        summary="Deterministic summary",
        sections=[{"title": "Market", "summary": "Balanced", "evidence": ["snapshot"], "warnings": []}],
        source_ids=["src-report"],
    )
    information = Dumpable(
        announcement_count=1,
        news_count=1,
        by_importance={"high": 1},
        by_symbol=[{"symbol": "600000.SH", "total": 2}],
        latest_items=[
            {
                "id": "item-1",
                "symbol": "600000.SH",
                "title": "Structured title",
                "summary": "full summary must not be sent",
                "source_url": "https://private.example/full",
                "event_type": "announcement",
                "importance": "high",
                "source_id": "src-info",
            }
        ],
        warnings=[],
        source_ids=["src-info"],
    )
    candidate = Dumpable(
        symbol="600000.SH",
        name="Test Bank",
        stage="launch",
        total_score=82,
        accumulation_score=80,
        launch_score=84,
        theme_score=60,
        risk_penalty=5,
        evidence=["volume expanded"],
        risks=[],
        metrics={"volume_ratio": 1.6},
        themes=["bank"],
        source_ids=["src-candidate"],
    )
    observation = Dumpable(
        symbol="600000.SH",
        status="watching",
        reason="rule support",
        invalidation_rule="structure changes",
        next_focus="next close",
        days_observed=1,
    )
    quality = Dumpable(
        latest_trade_date="2026-06-05",
        universe_symbols=5000,
        latest_bar_symbols=4800,
        stale_symbols=20,
        zero_amount_symbols=0,
        short_history_symbols=10,
        checked_at="2026-06-05T16:00:00Z",
    )
    monkeypatch.setattr("backend.app.agent_context.tracking_daily_report", lambda: report)
    monkeypatch.setattr("backend.app.agent_context.build_information_summary", lambda: information)
    monkeypatch.setattr("backend.app.agent_context.list_candidates", lambda **kwargs: [candidate] * 30)
    monkeypatch.setattr("backend.app.agent_context.list_observations", lambda: [observation])
    monkeypatch.setattr("backend.app.agent_context.build_data_quality_summary", lambda: quality)

    context = build_post_market_agent_context()

    assert len(context["candidates"]) == 12
    assert context["information"]["latest_items"][0]["title"] == "Structured title"
    assert "summary" not in context["information"]["latest_items"][0]
    assert "source_url" not in context["information"]["latest_items"][0]
    assert context["source_ids"] == ["src-candidate", "src-info", "src-report"]


def test_research_agent_returns_cited_read_only_answer():
    llm = FakeLLM(
        {
            "ResearchQueryAgent": {
                "answer": "The current candidate has deterministic volume and moving-average support.",
                "evidence": ["600000.SH score 82", "volume expanded"],
                "source_ids": ["src-test"],
                "missing_information": ["minute-line confirmation is unavailable"],
                "confidence": "medium",
            }
        }
    )

    answer, completion = create_research_answer("Explain the candidate facts.", _context(), llm)

    assert completion is not None
    assert answer is not None
    assert answer.blocked_by_compliance is False
    assert answer.evidence == ["600000.SH score 82", "volume expanded"]
    assert answer.missing_information == ["minute-line confirmation is unavailable"]


def test_research_agent_rejects_non_compliant_answer():
    llm = FakeLLM(
        {
            "ResearchQueryAgent": {
                "answer": "建议买入并设置目标价。",
                "evidence": [],
                "source_ids": ["src-test"],
                "missing_information": [],
                "confidence": "high",
            }
        }
    )

    answer, completion = create_research_answer("Explain the candidate facts.", _context(), llm)

    assert answer is None
    assert completion is not None


def test_research_agent_ignores_model_citations_outside_context():
    context = _context()
    context["source_ids"] = ["src-cninfo-announcement"]
    llm = FakeLLM(
        {
            "ResearchQueryAgent": {
                "answer": "The answer uses only the supplied structured facts.",
                "evidence": ["market snapshot"],
                "source_ids": ["src-fabricated"],
                "missing_information": [],
                "confidence": "medium",
            }
        }
    )

    answer, _ = create_research_answer("Explain the facts.", context, llm)

    assert answer is not None
    assert [citation.id for citation in answer.citations] == ["src-cninfo-announcement"]


def test_approve_remove_action_requires_route_then_applies_deletion(monkeypatch):
    now = datetime.now(timezone.utc)
    action = AgentAction(
        id="action-1",
        run_id="run-1",
        action_type="remove_observation",
        symbol="000001.SZ",
        status="pending",
        rationale="No longer in current candidates.",
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(
        main_module,
        "apply_agent_action",
        lambda action_id: action.model_copy(update={"status": "applied"}),
    )

    result = main_module.approve_agent_action("action-1")

    assert result.status == "applied"


def test_reject_action_does_not_touch_observation(monkeypatch):
    now = datetime.now(timezone.utc)
    action = AgentAction(
        id="action-2",
        run_id="run-1",
        action_type="remove_observation",
        symbol="000001.SZ",
        status="pending",
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(
        main_module,
        "set_agent_action_status",
        lambda action_id, status: action.model_copy(update={"status": status}),
    )

    result = main_module.reject_agent_action("action-2")

    assert result.status == "rejected"


def test_agent_api_runs_degraded_workflow_without_model_configuration(monkeypatch):
    monkeypatch.delenv("MARKETLENS_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MARKETLENS_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MARKETLENS_LLM_MODEL", raising=False)
    agent_run_id = ""
    job_run_id = ""
    try:
        with TestClient(app) as client:
            job = client.post("/api/admin/jobs/run/agent_post_market")
            assert job.status_code == 200
            job_payload = job.json()
            job_run_id = job_payload["id"]
            agent_run_id = job_payload["affected_scope"]["agent_run_id"]

            detail = client.get(f"/api/agents/runs/{agent_run_id}")
            actions = client.get("/api/agents/actions?status=pending")
            usage = client.get("/api/agents/usage")

        assert job_payload["status"] == "completed"
        assert job_payload["affected_scope"]["agent_status"] == "degraded"
        assert detail.status_code == 200
        assert detail.json()["artifacts"][0]["artifact_type"] == "deterministic_fallback"
        assert actions.status_code == 200
        assert usage.status_code == 200
        assert usage.json()["configured"] is False
    finally:
        with connect() as conn:
            if agent_run_id:
                conn.execute("DELETE FROM agent_runs WHERE id = %s", (agent_run_id,))
            if job_run_id:
                conn.execute("DELETE FROM job_runs WHERE id = %s", (job_run_id,))


def test_apply_remove_action_updates_status_and_observation_in_one_operation():
    repository = PostgresAgentRepository()
    run = repository.create_run("test_action", "test")
    action_id = "action-integration-remove"
    symbol = "TEST-ACTION"
    now = datetime.now(timezone.utc)
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO observation_list (user_id, symbol, reason, status)
                VALUES ('local-user', %s, 'test', 'watching')
                ON CONFLICT (user_id, symbol) DO UPDATE SET reason = 'test', status = 'watching'
                """,
                (symbol,),
            )
        repository.create_action(
            AgentAction(
                id=action_id,
                run_id=run.id,
                action_type="remove_observation",
                symbol=symbol,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )

        updated = apply_agent_action(action_id)

        assert updated is not None
        assert updated.status == "applied"
        with connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM observation_list WHERE user_id = 'local-user' AND symbol = %s",
                (symbol,),
            ).fetchone()
        assert row["count"] == 0
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM observation_list WHERE user_id = 'local-user' AND symbol = %s", (symbol,))
            conn.execute("DELETE FROM agent_runs WHERE id = %s", (run.id,))

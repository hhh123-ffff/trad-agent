from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import uuid4

from .compliance import check_text
from .models import AgentAction, AgentArtifact, AgentRun, AgentStep, LLMUsage


@dataclass(frozen=True)
class LLMCompletion:
    data: dict[str, Any]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class LLMClient(Protocol):
    configured: bool

    def complete(self, agent_name: str, payload: dict[str, Any]) -> LLMCompletion: ...


class AgentRepository(Protocol):
    def create_run(self, workflow: str, trigger: str) -> AgentRun: ...

    def finish_run(
        self,
        run_id: str,
        status: str,
        summary: str,
        error: str | None,
        calls_used: int,
        tokens_used: int,
    ) -> AgentRun: ...

    def save_step(self, step: AgentStep) -> AgentStep: ...

    def save_artifact(self, artifact: AgentArtifact) -> AgentArtifact: ...

    def create_action(self, action: AgentAction) -> AgentAction: ...

    def save_usage(self, usage: LLMUsage) -> LLMUsage: ...

    def daily_calls_used(self) -> int: ...


ContextLoader = Callable[[], dict[str, Any]]
ObservationWriter = Callable[..., Any]

MODEL_AGENTS = (
    "AnnouncementAnalystAgent",
    "CandidateResearchAgent",
    "ObservationManagerAgent",
    "ReportEditorAgent",
)


class PostMarketAgentService:
    def __init__(
        self,
        repository: AgentRepository,
        llm_client: LLMClient,
        context_loader: ContextLoader,
        *,
        observation_writer: ObservationWriter | None = None,
        daily_call_limit: int | None = None,
        workflow_call_limit: int | None = None,
    ):
        self.repository = repository
        self.llm_client = llm_client
        self.context_loader = context_loader
        self.observation_writer = observation_writer
        self.daily_call_limit = daily_call_limit or _positive_env_int("MARKETLENS_AGENT_DAILY_CALL_LIMIT", 20)
        self.workflow_call_limit = workflow_call_limit or _positive_env_int("MARKETLENS_AGENT_WORKFLOW_CALL_LIMIT", 12)

    def run(self, trigger: str = "manual") -> AgentRun:
        run = self.repository.create_run("post_market", trigger)
        calls_used = 0
        tokens_used = 0
        context: dict[str, Any] = {}
        try:
            context = self.context_loader()
            source_ids = _string_list(context.get("source_ids"))
            self._save_step(
                run.id,
                "DataQualityAgent",
                "completed",
                output=_data_quality_output(context),
                source_ids=source_ids,
                tool_calls=["load_structured_context"],
            )
            if not self.llm_client.configured:
                return self._degrade(
                    run.id,
                    context,
                    "LLM is not configured; deterministic fallback was saved.",
                    calls_used,
                    tokens_used,
                )

            outputs: dict[str, dict[str, Any]] = {}
            for agent_name in MODEL_AGENTS:
                if calls_used >= self.workflow_call_limit or self.repository.daily_calls_used() >= self.daily_call_limit:
                    return self._degrade(
                        run.id,
                        context,
                        "LLM call budget exhausted; deterministic fallback was saved.",
                        calls_used,
                        tokens_used,
                    )
                payload = _payload_for_agent(agent_name, context, outputs)
                calls_used += 1
                completion: LLMCompletion | None = None
                try:
                    completion = self.llm_client.complete(agent_name, payload)
                    completion_tokens = completion.prompt_tokens + completion.completion_tokens
                    tokens_used += completion_tokens
                    output = _validate_output(agent_name, completion.data)
                except Exception as exc:
                    failed_prompt_tokens = completion.prompt_tokens if completion else 0
                    failed_completion_tokens = completion.completion_tokens if completion else 0
                    self.repository.save_usage(
                        LLMUsage(
                            id=_id("usage"),
                            run_id=run.id,
                            agent_name=agent_name,
                            model=completion.model if completion else str(getattr(self.llm_client, "model", "unknown")),
                            prompt_tokens=failed_prompt_tokens,
                            completion_tokens=failed_completion_tokens,
                            total_tokens=failed_prompt_tokens + failed_completion_tokens,
                            latency_ms=completion.latency_ms if completion else 0,
                            success=False,
                            created_at=_now(),
                        )
                    )
                    self._save_step(
                        run.id,
                        agent_name,
                        "failed",
                        output={},
                        source_ids=source_ids,
                        error=str(exc),
                    )
                    return self._degrade(
                        run.id,
                        context,
                        f"{agent_name} failed: {exc}",
                        calls_used,
                        tokens_used,
                    )
                self.repository.save_usage(
                    LLMUsage(
                        id=_id("usage"),
                        run_id=run.id,
                        agent_name=agent_name,
                        model=completion.model,
                        prompt_tokens=completion.prompt_tokens,
                        completion_tokens=completion.completion_tokens,
                        total_tokens=completion_tokens,
                        latency_ms=completion.latency_ms,
                        success=True,
                        created_at=_now(),
                    )
                )
                outputs[agent_name] = output
                self._save_step(
                    run.id,
                    agent_name,
                    "completed",
                    output=output,
                    source_ids=source_ids,
                    tool_calls=["structured_context"],
                )

            brief = outputs["ReportEditorAgent"]
            compliance = check_text(json.dumps(outputs, ensure_ascii=False))
            if not compliance.allowed:
                self._save_step(
                    run.id,
                    "ComplianceGuard",
                    "failed",
                    output={"blocked_terms": compliance.blocked_terms},
                    source_ids=source_ids,
                    error="Non-compliant model output.",
                )
                return self._degrade(
                    run.id,
                    context,
                    "Compliance guard blocked model output; deterministic fallback was saved.",
                    calls_used,
                    tokens_used,
                )

            self._save_step(
                run.id,
                "ComplianceGuard",
                "completed",
                output={"allowed": True, "blocked_terms": []},
                source_ids=source_ids,
                tool_calls=["compliance_check"],
            )
            self.repository.save_artifact(
                AgentArtifact(
                    id=_id("artifact"),
                    run_id=run.id,
                    artifact_type="post_market_brief",
                    title=str(brief.get("title") or "Post-market research brief"),
                    content=brief,
                    source_ids=source_ids,
                    created_at=_now(),
                )
            )
            finished = self.repository.finish_run(
                run.id,
                "completed",
                str(brief.get("summary") or "Post-market Agent workflow completed."),
                None,
                calls_used,
                tokens_used,
            )
            try:
                self._apply_observation_actions(run.id, context, outputs["ObservationManagerAgent"], source_ids)
            except Exception as exc:
                self._save_step(
                    run.id,
                    "ObservationActionWriter",
                    "failed",
                    output={},
                    source_ids=source_ids,
                    error=f"Post-completion observation action failed: {exc}",
                )
            return finished
        except Exception as exc:
            return self._degrade(run.id, context, f"Agent workflow failed: {exc}", calls_used, tokens_used)

    def _apply_observation_actions(
        self,
        run_id: str,
        context: dict[str, Any],
        output: dict[str, Any],
        source_ids: list[str],
    ) -> None:
        candidate_symbols = {
            str(candidate.get("symbol") or "").upper()
            for candidate in context.get("candidates", [])
            if isinstance(candidate, dict)
        }
        for raw_action in output.get("actions", []):
            if not isinstance(raw_action, dict):
                continue
            action_type = str(raw_action.get("type") or "")
            symbol = str(raw_action.get("symbol") or "").upper()
            reason = str(raw_action.get("reason") or "")
            if action_type == "upsert_observation" and symbol in candidate_symbols and self.observation_writer:
                payload = {
                    "symbol": symbol,
                    "reason": reason,
                    "next_focus": str(raw_action.get("next_focus") or ""),
                }
                self.observation_writer(**payload)
                continue
            if action_type == "remove_observation" and symbol:
                self.repository.create_action(
                    AgentAction(
                        id=_id("action"),
                        run_id=run_id,
                        action_type=action_type,
                        symbol=symbol,
                        status="pending",
                        payload=raw_action,
                        rationale=reason,
                        source_ids=source_ids,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )

    def _save_step(
        self,
        run_id: str,
        agent_name: str,
        status: str,
        *,
        output: dict[str, Any],
        source_ids: list[str],
        tool_calls: list[str] | None = None,
        error: str | None = None,
    ) -> AgentStep:
        now = _now()
        return self.repository.save_step(
            AgentStep(
                id=_id("step"),
                run_id=run_id,
                agent_name=agent_name,
                status=status,
                tool_calls=tool_calls or [],
                source_ids=source_ids,
                output=output,
                error=error,
                started_at=now,
                finished_at=now,
                created_at=now,
            )
        )

    def _degrade(
        self,
        run_id: str,
        context: dict[str, Any],
        error: str,
        calls_used: int,
        tokens_used: int,
    ) -> AgentRun:
        source_ids = _string_list(context.get("source_ids"))
        report = context.get("report") if isinstance(context.get("report"), dict) else {}
        self.repository.save_artifact(
            AgentArtifact(
                id=_id("artifact"),
                run_id=run_id,
                artifact_type="deterministic_fallback",
                title="Deterministic post-market fallback",
                content={
                    "summary": "Model analysis was unavailable or blocked. The deterministic daily report remains authoritative.",
                    "report": report,
                    "warnings": [error],
                },
                source_ids=source_ids,
                created_at=_now(),
            )
        )
        return self.repository.finish_run(
            run_id,
            "degraded",
            "Deterministic post-market fallback saved.",
            error,
            calls_used,
            tokens_used,
        )


def _payload_for_agent(agent_name: str, context: dict[str, Any], outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = {
        "trading_day": context.get("trading_day"),
        "data_quality": context.get("data_quality", {}),
        "source_ids": _string_list(context.get("source_ids")),
        "rules": {
            "facts_only": True,
            "no_investment_advice": True,
            "return_json_object": True,
        },
    }
    if agent_name == "AnnouncementAnalystAgent":
        base["information"] = context.get("information", {})
    elif agent_name == "CandidateResearchAgent":
        base["candidates"] = context.get("candidates", [])
    elif agent_name == "ObservationManagerAgent":
        base["candidates"] = context.get("candidates", [])
        base["observations"] = context.get("observations", [])
    elif agent_name == "ReportEditorAgent":
        base["deterministic_report"] = context.get("report", {})
        base["agent_outputs"] = outputs
    return base


def _validate_output(agent_name: str, output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        raise ValueError("model output must be a JSON object")
    if agent_name == "ReportEditorAgent":
        if not str(output.get("title") or "").strip() or not str(output.get("summary") or "").strip():
            raise ValueError("report output requires title and summary")
    elif not str(output.get("summary") or "").strip():
        raise ValueError(f"{agent_name} output requires summary")
    if agent_name == "ObservationManagerAgent" and not isinstance(output.get("actions", []), list):
        raise ValueError("observation actions must be a list")
    return output


def _data_quality_output(context: dict[str, Any]) -> dict[str, Any]:
    quality = context.get("data_quality")
    return quality if isinstance(quality, dict) else {"warnings": ["Structured data quality context is missing."]}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item).strip()})


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _now() -> datetime:
    return datetime.now(timezone.utc)

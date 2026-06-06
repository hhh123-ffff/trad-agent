from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

from .agent_context import build_post_market_agent_context
from .agent_repository import PostgresAgentRepository
from .agent_service import PostMarketAgentService
from .llm_client import OpenAICompatibleClient
from .models import AgentArtifact, AgentRun, AgentStep, AgentUsageSummary, AssistantAnswer, LLMUsage
from .research_agent import create_research_answer
from .stealth_repository import observe_symbol


def run_post_market_agent_workflow(trigger: str = "manual") -> AgentRun:
    return PostMarketAgentService(
        PostgresAgentRepository(),
        OpenAICompatibleClient(),
        build_post_market_agent_context,
        observation_writer=observe_symbol,
    ).run(trigger=trigger)


def agent_usage_summary() -> AgentUsageSummary:
    repository = PostgresAgentRepository()
    client = OpenAICompatibleClient()
    daily_limit = _positive_env_int("MARKETLENS_AGENT_DAILY_CALL_LIMIT", 20)
    used = repository.daily_calls_used()
    return AgentUsageSummary(
        configured=client.configured,
        model=client.model,
        daily_call_limit=daily_limit,
        calls_used_today=used,
        calls_remaining_today=max(0, daily_limit - used),
    )


def run_research_query_agent(query: str) -> AssistantAnswer | None:
    repository = PostgresAgentRepository()
    client = OpenAICompatibleClient()
    daily_limit = _positive_env_int("MARKETLENS_AGENT_DAILY_CALL_LIMIT", 20)
    if not client.configured or repository.daily_calls_used() >= daily_limit:
        return None
    run = repository.create_run("research_query", "assistant_query")
    context = build_post_market_agent_context()
    source_ids = context.get("source_ids", [])
    started = datetime.now(timezone.utc)
    try:
        answer, completion = create_research_answer(query, context, client)
        if completion is None:
            repository.finish_run(run.id, "degraded", "Research Agent unavailable.", "LLM is not configured.", 0, 0)
            return None
        tokens = completion.prompt_tokens + completion.completion_tokens
        repository.save_usage(
            LLMUsage(
                id=f"usage-{uuid4().hex}",
                run_id=run.id,
                agent_name="ResearchQueryAgent",
                model=completion.model,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                total_tokens=tokens,
                latency_ms=completion.latency_ms,
                success=answer is not None,
                created_at=datetime.now(timezone.utc),
            )
        )
        repository.save_step(
            AgentStep(
                id=f"step-{uuid4().hex}",
                run_id=run.id,
                agent_name="ResearchQueryAgent",
                status="completed" if answer is not None else "failed",
                tool_calls=["structured_context"],
                source_ids=source_ids,
                output={"answer": answer.answer, "evidence": answer.evidence} if answer else {},
                error=None if answer else "Model answer was empty or blocked by compliance.",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                created_at=started,
            )
        )
        if answer is None:
            repository.finish_run(
                run.id,
                "degraded",
                "Research Agent answer blocked; deterministic answer used.",
                "Model answer was empty or blocked by compliance.",
                1,
                tokens,
            )
            return None
        repository.save_artifact(
            AgentArtifact(
                id=f"artifact-{uuid4().hex}",
                run_id=run.id,
                artifact_type="research_answer",
                title="Read-only research answer",
                content={
                    "query": query,
                    "answer": answer.answer,
                    "evidence": answer.evidence,
                    "missing_information": answer.missing_information,
                },
                source_ids=source_ids,
                created_at=datetime.now(timezone.utc),
            )
        )
        repository.finish_run(run.id, "completed", "Read-only research answer generated.", None, 1, tokens)
        return answer
    except Exception as exc:
        repository.save_usage(
            LLMUsage(
                id=f"usage-{uuid4().hex}",
                run_id=run.id,
                agent_name="ResearchQueryAgent",
                model=client.model or "unknown",
                success=False,
                created_at=datetime.now(timezone.utc),
            )
        )
        repository.finish_run(run.id, "degraded", "Research Agent failed; deterministic answer used.", str(exc), 1, 0)
        return None


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default

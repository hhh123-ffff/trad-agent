from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from .database import connect
from .models import AgentAction, AgentArtifact, AgentRun, AgentRunDetail, AgentStep, LLMUsage


class PostgresAgentRepository:
    def create_run(self, workflow: str, trigger: str) -> AgentRun:
        now = datetime.now(timezone.utc)
        run = AgentRun(
            id=f"agent-run-{uuid4().hex}",
            workflow=workflow,
            status="running",
            trigger=trigger,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        with connect() as conn:
            row = conn.execute(
                """
                INSERT INTO agent_runs (id, workflow, status, trigger, started_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (run.id, run.workflow, run.status, run.trigger, run.started_at, run.created_at, run.updated_at),
            ).fetchone()
        return _run(row)

    def finish_run(
        self,
        run_id: str,
        status: str,
        summary: str,
        error: str | None,
        calls_used: int,
        tokens_used: int,
    ) -> AgentRun:
        with connect() as conn:
            row = conn.execute(
                """
                UPDATE agent_runs
                SET status = %s, summary = %s, error = %s, calls_used = %s, tokens_used = %s,
                    finished_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (status, summary, error, calls_used, tokens_used, run_id),
            ).fetchone()
        if not row:
            raise KeyError(run_id)
        return _run(row)

    def save_step(self, step: AgentStep) -> AgentStep:
        with connect() as conn:
            row = conn.execute(
                """
                INSERT INTO agent_steps (
                    id, run_id, agent_name, status, tool_calls, source_ids, output, error,
                    started_at, finished_at, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    step.id,
                    step.run_id,
                    step.agent_name,
                    step.status,
                    Jsonb(step.tool_calls),
                    Jsonb(step.source_ids),
                    Jsonb(step.output),
                    step.error,
                    step.started_at,
                    step.finished_at,
                    step.created_at,
                ),
            ).fetchone()
        return _step(row)

    def save_artifact(self, artifact: AgentArtifact) -> AgentArtifact:
        with connect() as conn:
            row = conn.execute(
                """
                INSERT INTO agent_artifacts (id, run_id, artifact_type, title, content, source_ids, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    artifact.id,
                    artifact.run_id,
                    artifact.artifact_type,
                    artifact.title,
                    Jsonb(artifact.content),
                    Jsonb(artifact.source_ids),
                    artifact.created_at,
                ),
            ).fetchone()
        return _artifact(row)

    def create_action(self, action: AgentAction) -> AgentAction:
        with connect() as conn:
            row = conn.execute(
                """
                INSERT INTO agent_actions (
                    id, run_id, action_type, symbol, status, payload, rationale, source_ids, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    action.id,
                    action.run_id,
                    action.action_type,
                    action.symbol,
                    action.status,
                    Jsonb(action.payload),
                    action.rationale,
                    Jsonb(action.source_ids),
                    action.created_at,
                    action.updated_at,
                ),
            ).fetchone()
        return _action(row)

    def save_usage(self, usage: LLMUsage) -> LLMUsage:
        with connect() as conn:
            row = conn.execute(
                """
                INSERT INTO llm_usage (
                    id, run_id, agent_name, model, prompt_tokens, completion_tokens,
                    total_tokens, latency_ms, success, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    usage.id,
                    usage.run_id,
                    usage.agent_name,
                    usage.model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                    usage.latency_ms,
                    usage.success,
                    usage.created_at,
                ),
            ).fetchone()
        return _usage(row)

    def daily_calls_used(self) -> int:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM llm_usage
                WHERE (created_at AT TIME ZONE 'Asia/Shanghai')::date =
                      (NOW() AT TIME ZONE 'Asia/Shanghai')::date
                """
            ).fetchone()
        return int(row["count"] or 0) if row else 0


def list_agent_runs(limit: int = 30, workflow: str | None = None) -> list[AgentRun]:
    with connect() as conn:
        if workflow:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE workflow = %s ORDER BY started_at DESC LIMIT %s",
                (workflow, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT %s", (limit,)).fetchall()
    return [_run(row) for row in rows]


def get_agent_run_detail(run_id: str) -> AgentRunDetail | None:
    with connect() as conn:
        run_row = conn.execute("SELECT * FROM agent_runs WHERE id = %s", (run_id,)).fetchone()
        if not run_row:
            return None
        step_rows = conn.execute("SELECT * FROM agent_steps WHERE run_id = %s ORDER BY created_at ASC", (run_id,)).fetchall()
        artifact_rows = conn.execute("SELECT * FROM agent_artifacts WHERE run_id = %s ORDER BY created_at DESC", (run_id,)).fetchall()
        action_rows = conn.execute("SELECT * FROM agent_actions WHERE run_id = %s ORDER BY created_at DESC", (run_id,)).fetchall()
    return AgentRunDetail(
        run=_run(run_row),
        steps=[_step(row) for row in step_rows],
        artifacts=[_artifact(row) for row in artifact_rows],
        actions=[_action(row) for row in action_rows],
    )


def list_agent_actions(status: str | None = None, limit: int = 100) -> list[AgentAction]:
    with connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM agent_actions WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return [_action(row) for row in rows]


def get_agent_action(action_id: str) -> AgentAction | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM agent_actions WHERE id = %s", (action_id,)).fetchone()
    return _action(row) if row else None


def apply_agent_action(action_id: str, user_id: str = "local-user") -> AgentAction | None:
    with connect() as conn:
        action = conn.execute(
            "SELECT * FROM agent_actions WHERE id = %s AND status = 'pending' FOR UPDATE",
            (action_id,),
        ).fetchone()
        if not action:
            return None
        status = "approved"
        if action["action_type"] == "remove_observation" and action["symbol"]:
            conn.execute(
                "DELETE FROM observation_list WHERE user_id = %s AND symbol = %s",
                (user_id, action["symbol"]),
            )
            status = "applied"
        row = conn.execute(
            "UPDATE agent_actions SET status = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (status, action_id),
        ).fetchone()
    return _action(row)


def set_agent_action_status(action_id: str, status: str) -> AgentAction | None:
    if status not in {"approved", "rejected", "applied"}:
        raise ValueError(status)
    with connect() as conn:
        row = conn.execute(
            "UPDATE agent_actions SET status = %s, updated_at = NOW() WHERE id = %s AND status = 'pending' RETURNING *",
            (status, action_id),
        ).fetchone()
    return _action(row) if row else None


def _run(row: dict[str, Any]) -> AgentRun:
    return AgentRun(**row)


def _step(row: dict[str, Any]) -> AgentStep:
    return AgentStep(**row)


def _artifact(row: dict[str, Any]) -> AgentArtifact:
    return AgentArtifact(**row)


def _action(row: dict[str, Any]) -> AgentAction:
    return AgentAction(**row)


def _usage(row: dict[str, Any]) -> LLMUsage:
    return LLMUsage(**row)

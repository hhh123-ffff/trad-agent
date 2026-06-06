from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import JobRunStatus, JobRunStep
from .tracking_repository import create_job_run_step, finish_job_run_step


class TemporaryProviderStepError(RuntimeError):
    pass


class RateLimitStepError(RuntimeError):
    pass


class MissingCredentialsStepError(RuntimeError):
    pass


class ConfigurationStepError(RuntimeError):
    pass


class DataContractStepError(RuntimeError):
    pass


class StorageStepError(RuntimeError):
    pass


class StepOutcome(BaseModel):
    status: Literal["completed", "degraded", "skipped"] = "completed"
    result_scope: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ClassifiedStepError(BaseModel):
    code: str
    retryable: bool
    action: str


def classify_step_error(exc: Exception) -> ClassifiedStepError:
    if isinstance(exc, MissingCredentialsStepError):
        return ClassifiedStepError(code="missing_credentials", retryable=False, action="Configure the required provider credentials.")
    if isinstance(exc, ConfigurationStepError):
        return ClassifiedStepError(code="configuration_error", retryable=False, action="Check the application configuration.")
    if isinstance(exc, DataContractStepError):
        return ClassifiedStepError(code="data_contract_error", retryable=False, action="Inspect the provider payload contract.")
    if isinstance(exc, RateLimitStepError):
        return ClassifiedStepError(code="rate_limit", retryable=True, action="Wait briefly and retry.")
    if isinstance(exc, StorageStepError):
        return ClassifiedStepError(code="storage_error", retryable=True, action="Check PostgreSQL and Redis availability.")
    if isinstance(exc, (TemporaryProviderStepError, TimeoutError, ConnectionError)):
        return ClassifiedStepError(code="temporary_provider_error", retryable=True, action="Retry after the provider recovers.")

    message = str(exc).lower()
    if any(fragment in message for fragment in ("token missing", "token is required", "credentials", "未配置", "缺少 token")):
        return ClassifiedStepError(code="missing_credentials", retryable=False, action="Configure the required provider credentials.")
    if any(fragment in message for fragment in ("rate limit", "too many requests", "429", "限流")):
        return ClassifiedStepError(code="rate_limit", retryable=True, action="Wait briefly and retry.")
    if any(fragment in message for fragment in ("database", "postgres", "redis", "storage", "存储")):
        return ClassifiedStepError(code="storage_error", retryable=True, action="Check PostgreSQL and Redis availability.")
    if any(fragment in message for fragment in ("timeout", "timed out", "connection", "503", "502", "504", "暂时")):
        return ClassifiedStepError(code="temporary_provider_error", retryable=True, action="Retry after the provider recovers.")
    return ClassifiedStepError(code="unknown_error", retryable=False, action="Inspect the error before retrying.")


def run_pipeline_step(
    job_run_id: str,
    step_name: str,
    handler: Callable[[], StepOutcome],
    *,
    max_attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> JobRunStep:
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        step = create_job_run_step(job_run_id, step_name, attempt=attempt)
        try:
            outcome = handler()
            result_scope = dict(outcome.result_scope)
            if outcome.warnings:
                result_scope["warnings"] = outcome.warnings
            return finish_job_run_step(step.id, outcome.status, result_scope=result_scope)
        except Exception as exc:
            classified = classify_step_error(exc)
            failed = finish_job_run_step(
                step.id,
                "failed",
                result_scope={"action": classified.action},
                error_code=classified.code,
                error=str(exc),
                retryable=classified.retryable,
            )
            if not classified.retryable or attempt >= attempts:
                return failed
            sleep(min(0.25 * attempt, 1.0))
    raise RuntimeError("pipeline step ended without a result")


def aggregate_pipeline_status(steps: Sequence[JobRunStep]) -> JobRunStatus:
    latest_by_name: dict[str, JobRunStep] = {}
    for step in steps:
        current = latest_by_name.get(step.step_name)
        if current is None or step.attempt >= current.attempt:
            latest_by_name[step.step_name] = step

    report = latest_by_name.get("daily_report")
    if report is not None and report.status == "failed":
        return "failed"
    if any(step.status == "running" for step in latest_by_name.values()):
        return "running"
    if any(step.status in {"failed", "degraded", "skipped"} for step in latest_by_name.values()):
        return "degraded"
    return "completed"

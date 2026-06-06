from __future__ import annotations

from .data_freshness import DataFreshnessResult
from .models import AppNotification, JobRun
from .tracking_repository import create_app_notification


def create_pipeline_notification(run: JobRun) -> AppNotification:
    notification_type = {
        "completed": "pipeline_completed",
        "degraded": "pipeline_degraded",
        "failed": "pipeline_failed",
    }.get(run.status, "pipeline_degraded")
    severity = {"completed": "info", "degraded": "warning", "failed": "critical"}.get(run.status, "warning")
    title = {
        "completed": "盘后闭环已完成",
        "degraded": "盘后闭环已降级完成",
        "failed": "盘后闭环执行失败",
    }.get(run.status, "盘后闭环状态已更新")
    return create_app_notification(
        notification_type=notification_type,
        severity=severity,
        title=title,
        message=run.message or "盘后闭环状态已更新，请查看步骤详情。",
        related_job_run_id=run.id,
        metadata={"status": run.status, "affected_scope": run.affected_scope},
    )


def create_freshness_notification(job_run_id: str, freshness: DataFreshnessResult) -> AppNotification | None:
    if freshness.status == "fresh":
        return None
    affected = [check.scope for check in freshness.checks if check.status != "fresh"]
    return create_app_notification(
        notification_type="data_stale",
        severity="warning" if freshness.status == "stale" else "critical",
        title="盘后数据存在缺口",
        message="部分盘后数据不是目标交易日数据，请查看新鲜度明细后决定是否补跑。",
        related_job_run_id=job_run_id,
        metadata={"freshness": freshness.model_dump(mode="json"), "affected_scopes": affected},
    )

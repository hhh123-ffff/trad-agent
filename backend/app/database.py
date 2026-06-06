from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from redis import Redis

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://qrant:qrant_dev@127.0.0.1:5432/qrant_agent")
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6380/0")
DB_CONNECT_TIMEOUT_SECONDS = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5"))
REDIS_TIMEOUT_SECONDS = float(os.getenv("REDIS_TIMEOUT_SECONDS", "3"))


@contextmanager
def connect() -> Iterator[Connection]:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=DB_CONNECT_TIMEOUT_SECONDS) as conn:
        yield conn


def get_redis() -> Redis:
    return Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
    )


def init_schema() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS data_sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                as_of TIMESTAMPTZ NOT NULL,
                license TEXT NOT NULL,
                freshness TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist_items (
                user_id TEXT NOT NULL DEFAULT 'local-user',
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                group_name TEXT NOT NULL,
                price NUMERIC(18, 4) NOT NULL DEFAULT 0,
                change_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
                volume_ratio NUMERIC(10, 4) NOT NULL DEFAULT 1,
                tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                attention_reason TEXT NOT NULL DEFAULT '',
                latest_event TEXT NOT NULL DEFAULT '',
                risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_id TEXT NOT NULL REFERENCES data_sources(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, symbol)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_events (
                id TEXT PRIMARY KEY,
                occurred_at TIMESTAMPTZ NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                affected_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
                affected_sectors JSONB NOT NULL DEFAULT '[]'::jsonb,
                importance TEXT NOT NULL,
                fact_basis JSONB NOT NULL DEFAULT '[]'::jsonb,
                inference TEXT,
                confidence TEXT NOT NULL,
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                compliance_label TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                report_type TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                generated_at TIMESTAMPTZ NOT NULL,
                title TEXT NOT NULL,
                payload JSONB NOT NULL,
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assistant_queries (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'local-user',
                query TEXT NOT NULL,
                answer TEXT NOT NULL,
                confidence TEXT NOT NULL,
                blocked_by_compliance BOOLEAN NOT NULL,
                evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
                citation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                missing_information JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_universe (
                symbol TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_st BOOLEAN NOT NULL DEFAULT FALSE,
                listed_days INTEGER NOT NULL DEFAULT 0,
                market TEXT NOT NULL DEFAULT 'A股',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_bars (
                symbol TEXT NOT NULL,
                trade_date DATE NOT NULL,
                open NUMERIC(18, 4) NOT NULL,
                high NUMERIC(18, 4) NOT NULL,
                low NUMERIC(18, 4) NOT NULL,
                close NUMERIC(18, 4) NOT NULL,
                volume NUMERIC(24, 4) NOT NULL DEFAULT 0,
                amount NUMERIC(24, 4) NOT NULL DEFAULT 0,
                change_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
                turnover_rate NUMERIC(10, 4) NOT NULL DEFAULT 0,
                adjust TEXT NOT NULL DEFAULT 'qfq',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (symbol, trade_date, adjust)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS theme_memberships (
                symbol TEXT NOT NULL,
                theme_name TEXT NOT NULL,
                theme_type TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (symbol, theme_name, theme_type)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stealth_scan_results (
                trading_day DATE NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                stage TEXT NOT NULL,
                total_score NUMERIC(10, 4) NOT NULL,
                accumulation_score NUMERIC(10, 4) NOT NULL,
                launch_score NUMERIC(10, 4) NOT NULL,
                theme_score NUMERIC(10, 4) NOT NULL,
                risk_penalty NUMERIC(10, 4) NOT NULL,
                evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
                risks JSONB NOT NULL DEFAULT '[]'::jsonb,
                metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (trading_day, symbol)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stealth_scan_tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                requested_limit INTEGER,
                requested_offset INTEGER NOT NULL DEFAULT 0,
                requested_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
                active_themes JSONB NOT NULL DEFAULT '[]'::jsonb,
                total INTEGER NOT NULL DEFAULT 0,
                scanned INTEGER NOT NULL DEFAULT 0,
                saved INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                stages JSONB NOT NULL DEFAULT '{}'::jsonb,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute("ALTER TABLE stealth_scan_tasks ADD COLUMN IF NOT EXISTS requested_offset INTEGER NOT NULL DEFAULT 0;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stealth_scan_failures (
                id BIGSERIAL PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES stealth_scan_tasks(id) ON DELETE CASCADE,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'history',
                error TEXT NOT NULL DEFAULT '',
                retry_count INTEGER NOT NULL DEFAULT 0,
                resolved BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (task_id, symbol, stage)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observation_list (
                user_id TEXT NOT NULL DEFAULT 'local-user',
                symbol TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '观察中',
                note TEXT NOT NULL DEFAULT '',
                invalidation_rule TEXT NOT NULL DEFAULT '',
                next_focus TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, symbol)
            );
            """
        )
        conn.execute("ALTER TABLE observation_list ADD COLUMN IF NOT EXISTS invalidation_rule TEXT NOT NULL DEFAULT '';")
        conn.execute("ALTER TABLE observation_list ADD COLUMN IF NOT EXISTS next_focus TEXT NOT NULL DEFAULT '';")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observation_journal (
                user_id TEXT NOT NULL DEFAULT 'local-user',
                symbol TEXT NOT NULL,
                trading_day DATE NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                bucket_key TEXT NOT NULL,
                bucket_label TEXT NOT NULL,
                previous_bucket_key TEXT,
                transition_label TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT '',
                total_score NUMERIC(10, 4),
                accumulation_score NUMERIC(10, 4),
                launch_score NUMERIC(10, 4),
                theme_score NUMERIC(10, 4),
                risk_penalty NUMERIC(10, 4),
                decision_summary TEXT NOT NULL DEFAULT '',
                observation_reason TEXT NOT NULL DEFAULT '',
                manual_invalidation_rule TEXT NOT NULL DEFAULT '',
                next_focus TEXT NOT NULL DEFAULT '',
                evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
                risks JSONB NOT NULL DEFAULT '[]'::jsonb,
                invalidation_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, symbol, trading_day)
            );
            """
        )
        conn.execute("ALTER TABLE observation_journal ADD COLUMN IF NOT EXISTS observation_reason TEXT NOT NULL DEFAULT '';")
        conn.execute("ALTER TABLE observation_journal ADD COLUMN IF NOT EXISTS manual_invalidation_rule TEXT NOT NULL DEFAULT '';")
        conn.execute("ALTER TABLE observation_journal ADD COLUMN IF NOT EXISTS next_focus TEXT NOT NULL DEFAULT '';")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_runs (
                id TEXT PRIMARY KEY,
                job_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                affected_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_run_steps (
                id TEXT PRIMARY KEY,
                job_run_id TEXT NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE,
                step_name TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 1,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                result_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_code TEXT,
                error TEXT,
                retryable BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_notifications (
                id TEXT PRIMARY KEY,
                notification_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                related_job_run_id TEXT REFERENCES job_runs(id) ON DELETE SET NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                read_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id TEXT PRIMARY KEY,
                captured_at TIMESTAMPTZ NOT NULL,
                interval TEXT NOT NULL DEFAULT '5m',
                provider TEXT NOT NULL,
                source_id TEXT NOT NULL,
                license_note TEXT NOT NULL DEFAULT '',
                market_temperature JSONB NOT NULL DEFAULT '{}'::jsonb,
                indexes JSONB NOT NULL DEFAULT '[]'::jsonb,
                sectors JSONB NOT NULL DEFAULT '[]'::jsonb,
                watchlist JSONB NOT NULL DEFAULT '[]'::jsonb,
                event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS intraday_event_rules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                threshold JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TIMESTAMPTZ NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'news',
                importance TEXT NOT NULL DEFAULT 'medium',
                provider TEXT NOT NULL DEFAULT 'dev',
                source_id TEXT NOT NULL DEFAULT 'src-dev-news',
                license_note TEXT NOT NULL DEFAULT '研发源，仅保存标题摘要和链接',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS announcement_items (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TIMESTAMPTZ NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'announcement',
                importance TEXT NOT NULL DEFAULT 'medium',
                provider TEXT NOT NULL DEFAULT 'dev',
                source_id TEXT NOT NULL DEFAULT 'src-dev-announcement',
                license_note TEXT NOT NULL DEFAULT '研发源，仅保存标题摘要和链接',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_tracking_reports (
                trading_day DATE PRIMARY KEY,
                generated_at TIMESTAMPTZ NOT NULL,
                headline TEXT NOT NULL,
                summary TEXT NOT NULL,
                sections JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                workflow TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL DEFAULT 'manual',
                summary TEXT NOT NULL DEFAULT '',
                error TEXT,
                calls_used INTEGER NOT NULL DEFAULT 0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_steps (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                agent_name TEXT NOT NULL,
                status TEXT NOT NULL,
                tool_calls JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                output JSONB NOT NULL DEFAULT '{}'::jsonb,
                error TEXT,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_actions (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                action_type TEXT NOT NULL,
                symbol TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                rationale TEXT NOT NULL DEFAULT '',
                source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_usage (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                agent_name TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                success BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_market_events_occurred_at ON market_events (occurred_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_type_day ON reports (report_type, trading_day);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assistant_queries_created_at ON assistant_queries (created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_bars_symbol_date ON daily_bars (symbol, trade_date DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stealth_results_score ON stealth_scan_results (trading_day DESC, total_score DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stealth_scan_tasks_updated ON stealth_scan_tasks (updated_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stealth_scan_failures_task ON stealth_scan_failures (task_id, resolved, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stealth_scan_failures_symbol ON stealth_scan_failures (symbol, resolved);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observation_user ON observation_list (user_id, updated_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observation_journal_user_day ON observation_journal (user_id, trading_day DESC, updated_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observation_journal_symbol_day ON observation_journal (symbol, trading_day DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_name_started ON job_runs (job_name, started_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_run_steps_run ON job_run_steps (job_run_id, created_at ASC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_run_steps_name ON job_run_steps (job_run_id, step_name, attempt DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_notifications_created ON app_notifications (created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_notifications_read ON app_notifications (read_at, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_market_snapshots_captured ON market_snapshots (captured_at DESC, interval);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_items_symbol_day ON news_items (symbol, published_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_announcement_items_symbol_day ON announcement_items (symbol, published_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs (started_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON agent_steps (run_id, created_at ASC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_artifacts_run ON agent_artifacts (run_id, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_actions_status ON agent_actions (status, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage (created_at DESC);")


def check_postgres() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def check_redis() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False

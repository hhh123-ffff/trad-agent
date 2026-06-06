from __future__ import annotations

from typing import Any

from .agent_service import LLMClient, LLMCompletion
from .compliance import check_text
from .data_providers import source_ref_for_id
from .market_provider import DISCLAIMER
from .models import AssistantAnswer, Confidence


def create_research_answer(
    query: str,
    context: dict[str, Any],
    llm_client: LLMClient,
) -> tuple[AssistantAnswer | None, LLMCompletion | None]:
    if not llm_client.configured:
        return None, None
    completion = llm_client.complete(
        "ResearchQueryAgent",
        {
            "query": query,
            "research_context": context,
            "rules": {
                "facts_only": True,
                "read_only": True,
                "no_investment_advice": True,
                "return_json_object": True,
            },
        },
    )
    output = completion.data
    answer_text = str(output.get("answer") or "").strip()
    if not answer_text or not check_text(answer_text).allowed:
        return None, completion
    evidence = _strings(output.get("evidence"))[:12]
    allowed_source_ids = _strings(context.get("source_ids"))
    source_ids = [source_id for source_id in _strings(output.get("source_ids")) if source_id in allowed_source_ids][:12]
    if not source_ids:
        source_ids = allowed_source_ids[:6]
    confidence_raw = str(output.get("confidence") or "low").lower()
    confidence = Confidence(confidence_raw) if confidence_raw in {"high", "medium", "low"} else Confidence.low
    return (
        AssistantAnswer(
            answer=answer_text,
            citations=[source_ref_for_id(source_id) for source_id in source_ids],
            evidence=evidence,
            confidence=confidence,
            blocked_by_compliance=False,
            missing_information=_strings(output.get("missing_information"))[:12],
            disclaimer=DISCLAIMER,
        ),
        completion,
    )


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]

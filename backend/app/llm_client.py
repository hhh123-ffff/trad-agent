from __future__ import annotations

import json
import os
from time import monotonic
from typing import Any

import requests

from .agent_service import LLMCompletion


AGENT_INSTRUCTIONS = {
    "AnnouncementAnalystAgent": "Group structured announcement and news facts. Identify data gaps. Do not give investment advice.",
    "CandidateResearchAgent": "Explain which deterministic strategy facts support each candidate and which risks remain.",
    "ObservationManagerAgent": "Propose observation upserts only for current candidates. Removal requests require human approval.",
    "ReportEditorAgent": "Produce a concise post-market research brief from deterministic facts and prior Agent outputs.",
    "ResearchQueryAgent": "Answer from the supplied structured research context with evidence and explicit missing information.",
}


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.base_url = (base_url if base_url is not None else os.getenv("MARKETLENS_LLM_BASE_URL", "")).strip().rstrip("/")
        self.api_key = (api_key if api_key is not None else os.getenv("MARKETLENS_LLM_API_KEY", "")).strip()
        self.model = (model if model is not None else os.getenv("MARKETLENS_LLM_MODEL", "")).strip()
        self.timeout_seconds = timeout_seconds or _timeout_from_env()
        self.configured = bool(self.base_url and self.api_key and self.model)

    def complete(self, agent_name: str, payload: dict[str, Any]) -> LLMCompletion:
        if not self.configured:
            raise RuntimeError("OpenAI-compatible model is not configured.")
        started = monotonic()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a read-only A-share post-market research Agent. "
                            "Use only the supplied structured facts, return one JSON object, cite source_ids, "
                            "and never provide buy, sell, position, target-price, or return promises. "
                            + AGENT_INSTRUCTIONS.get(agent_name, AGENT_INSTRUCTIONS["ResearchQueryAgent"])
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    },
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        content = _message_content(body)
        data = _parse_json_object(content)
        usage = body.get("usage") if isinstance(body, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        return LLMCompletion(
            data=data,
            model=str(body.get("model") or self.model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=round((monotonic() - started) * 1000),
        )


def _message_content(body: Any) -> str:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Model response is missing message content.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model response message content is empty.")
    return content.strip()


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        raise ValueError("Model response must contain a valid JSON object.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object.")
    return parsed


def _timeout_from_env() -> float:
    try:
        return max(1.0, float(os.getenv("MARKETLENS_LLM_TIMEOUT_SECONDS", "20")))
    except ValueError:
        return 20.0

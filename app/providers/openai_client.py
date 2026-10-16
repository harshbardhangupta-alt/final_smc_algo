"""OpenAI structured-research client.

OpenAI is used ONLY to interpret evidence (news items, fundamental figures) into
a validated JSON assessment. It never produces prices or overrides risk rules —
those are owned by the deterministic engine. Responses are parsed and validated;
malformed / timed-out responses fall back to an explicit "uncertain" result so
the caller can apply the fail-closed policy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Config, get_config
from . import ProviderUnavailable

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a cautious equity research assistant for Indian (NSE) stocks. "
    "You classify evidence; you do NOT predict prices or invent facts. "
    "Only use the provided evidence. If evidence is weak or missing, say so and "
    "lower your confidence. Treat allegations as unverified unless the source "
    "confirms an established fact. Respond ONLY with a single JSON object."
)

# Allowed classification values for validation.
_SENTIMENTS = {"positive", "neutral", "negative", "critical", "uncertain"}


@dataclass
class ResearchAssessment:
    sentiment: str = "uncertain"
    confidence: float = 0.0
    thesis_support: str = "uncertain"   # supports | neutral | undermines | uncertain
    material_negative: bool = False
    critical_flag: bool = False
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    model: str = ""
    available: bool = False
    error: str = ""

    @classmethod
    def unavailable(cls, reason: str) -> "ResearchAssessment":
        return cls(available=False, error=reason)


class OpenAIResearcher:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()

    @property
    def configured(self) -> bool:
        return self.config.openai_configured

    def assess(self, symbol: str, direction: str, evidence: dict) -> ResearchAssessment:
        """Assess news + fundamentals for a candidate.

        ``evidence`` carries ``news`` (list of items), ``fundamentals`` (dict)
        and the deterministic ``technical_summary`` for context.
        """
        if not self.configured:
            return ResearchAssessment.unavailable("OpenAI not configured")

        user_prompt = _build_prompt(symbol, direction, evidence)
        try:
            raw = self._chat(user_prompt)
        except ProviderUnavailable as exc:
            return ResearchAssessment.unavailable(str(exc))
        except Exception as exc:  # noqa: BLE001  (timeouts, transport, HTTP)
            log.warning("OpenAI assess failed for %s: %s", symbol, exc)
            return ResearchAssessment.unavailable(f"request failed: {exc}")

        return _validate(raw, self.config.openai_model)

    def _chat(self, user_prompt: str) -> dict:
        url = f"{self.config.openai_api_base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        body = {
            "model": self.config.openai_model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        with httpx.Client(timeout=self.config.openai_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


def _build_prompt(symbol: str, direction: str, evidence: dict) -> str:
    return (
        f"Stock: {symbol}\nProposed direction: {direction}\n\n"
        f"News items (JSON):\n{json.dumps(evidence.get('news', []), default=str)[:6000]}\n\n"
        f"Fundamentals (JSON):\n{json.dumps(evidence.get('fundamentals', {}), default=str)[:3000]}\n\n"
        f"Technical summary:\n{json.dumps(evidence.get('technical_summary', {}), default=str)[:1500]}\n\n"
        "Return JSON with exactly these keys: "
        '{"sentiment": one of ["positive","neutral","negative","critical","uncertain"], '
        '"confidence": 0..1, '
        '"thesis_support": one of ["supports","neutral","undermines","uncertain"], '
        '"material_negative": boolean, "critical_flag": boolean, '
        '"summary": string, "key_points": [string, ...]}'
    )


def _validate(raw: Any, model: str) -> ResearchAssessment:
    if not isinstance(raw, dict):
        return ResearchAssessment.unavailable("non-object response")
    sentiment = str(raw.get("sentiment", "uncertain")).lower()
    if sentiment not in _SENTIMENTS:
        sentiment = "uncertain"
    thesis = str(raw.get("thesis_support", "uncertain")).lower()
    if thesis not in {"supports", "neutral", "undermines", "uncertain"}:
        thesis = "uncertain"
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    key_points = raw.get("key_points", [])
    if not isinstance(key_points, list):
        key_points = []
    return ResearchAssessment(
        sentiment=sentiment,
        confidence=confidence,
        thesis_support=thesis,
        material_negative=bool(raw.get("material_negative", False)),
        critical_flag=bool(raw.get("critical_flag", False)),
        summary=str(raw.get("summary", ""))[:2000],
        key_points=[str(p)[:300] for p in key_points][:10],
        model=model,
        available=True,
    )

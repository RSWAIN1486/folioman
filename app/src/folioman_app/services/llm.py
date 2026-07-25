"""Optional external AI provider adapter for portfolio explanations.

Deterministic calculations stay in ``services.agent``. This module receives only
the identity-free overview plus a redacted question and never reads ORM objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import httpx

from folioman_app._env import env

ProviderName = Literal["openai", "openrouter"]

_PROVIDER_URLS: dict[ProviderName, str] = {
    "openai": "https://api.openai.com/v1/responses",
    "openrouter": "https://openrouter.ai/api/v1/responses",
}
_CONTEXT_FIELDS = (
    "data_as_of",
    "navs_as_of",
    "health_score",
    "health_label",
    "findings",
    "daily_brief",
    "metrics",
    "allocation",
    "top_holdings",
    "formula_notes",
    "assumptions",
)
_INSTRUCTIONS = """\
You are Folioman's analysis-only portfolio explainer.
Use the supplied deterministic portfolio context for any personalized statement.
Do not recalculate or contradict supplied amounts, returns, scores, dates, or formulas.
General investing education is allowed, but identify it as general information when it
is not derived from the portfolio context. Do not invent current NAVs, market news, fund
facts, or tax rules. Do not recommend or execute a specific buy, sell, or switch.
Never request or infer names, PANs, emails, phone numbers, folio/account identifiers, or
raw CAS data. State the data date, relevant formula, and assumptions when they matter.
Keep the answer concise and explicitly distinguish observations from assumptions.
"""


@dataclass(frozen=True)
class ProviderConfig:
    provider: ProviderName
    model: str
    api_key: str


@dataclass(frozen=True)
class ProviderAnswer:
    text: str
    provider: ProviderName
    model: str


class ProviderError(RuntimeError):
    """An external provider request could not produce a usable answer."""


def configured_provider() -> ProviderConfig | None:
    """Return a complete provider configuration, otherwise keep chat local."""
    provider = env.str("FOLIOMAN_AI_PROVIDER", "local").strip().lower()
    model = env.str("FOLIOMAN_AI_MODEL", "").strip()
    if provider == "openai":
        api_key = env.str("OPENAI_API_KEY", "").strip()
    elif provider == "openrouter":
        api_key = env.str("OPENROUTER_API_KEY", "").strip()
    else:
        return None
    if not api_key or not model:
        return None
    return ProviderConfig(provider=provider, model=model, api_key=api_key)


def build_provider_context(overview: dict) -> dict:
    """Copy only approved, identity-free fields into the outbound payload."""
    return {field: overview[field] for field in _CONTEXT_FIELDS}


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported context value: {type(value).__name__}")


def _extract_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if (
                isinstance(content, dict)
                and content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
                and content["text"].strip()
            ):
                return content["text"].strip()
    raise ProviderError("Provider returned no text")


def answer_with_provider(
    config: ProviderConfig,
    overview: dict,
    question: str,
) -> ProviderAnswer:
    """Request an explanation from a fixed, server-side provider endpoint."""
    context = json.dumps(
        build_provider_context(overview),
        default=_json_default,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    request_body: dict = {
        "model": config.model,
        "instructions": _INSTRUCTIONS,
        "input": f"Portfolio context:\n{context}\n\nUser question:\n{question}",
        "max_output_tokens": 800,
        "store": False,
    }
    if config.provider == "openrouter":
        request_body["provider"] = {
            "zdr": True,
            "data_collection": "deny",
        }

    try:
        response = httpx.post(
            _PROVIDER_URLS[config.provider],
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError("External AI request failed") from exc

    return ProviderAnswer(
        text=_extract_output_text(payload),
        provider=config.provider,
        model=config.model,
    )

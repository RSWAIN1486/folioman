"""Investor-scoped AI workspace API.

The initial release is deterministic and local-only. It establishes a PII-safe
context boundary for a future external model adapter without transmitting data.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from django.utils import timezone
from ninja import Router, Schema
from pydantic import Field

from folioman_app.api.auth import get_owned_investor
from folioman_app.services.agent import (
    answer_portfolio_question,
    build_agent_overview,
    redact_known_pii,
    redact_pii,
)
from folioman_app.services.llm import ProviderError, answer_with_provider, configured_provider

router = Router(tags=["AI workspace"])
logger = logging.getLogger(__name__)


class AgentPrivacyOut(Schema):
    mode: str
    external_transmission: bool
    excluded_fields: list[str]


class AgentFindingOut(Schema):
    severity: Literal["info", "warning", "critical"]
    title: str
    detail: str
    metric: str | None = None


class AgentMetricsOut(Schema):
    total_inr: Decimal
    day_change_inr: Decimal | None = None
    xirr: float | None = None
    holdings_count: int
    tax_ready_count: int
    integrity_unit_count: int


class AgentAllocationOut(Schema):
    label: str
    value_inr: Decimal
    share_pct: float


class AgentHoldingOut(Schema):
    label: str
    security_name: str
    value_inr: Decimal | None = None
    share_pct: float
    day_change_inr: Decimal | None = None


class AgentOverviewOut(Schema):
    generated_at: datetime
    data_as_of: date
    navs_as_of: date | None = None
    privacy: AgentPrivacyOut
    health_score: int
    health_label: str
    findings: list[AgentFindingOut]
    daily_brief: list[str]
    metrics: AgentMetricsOut
    allocation: list[AgentAllocationOut]
    top_holdings: list[AgentHoldingOut]
    formula_notes: list[str]
    assumptions: list[str]


class AgentChatIn(Schema):
    message: str = Field(min_length=1, max_length=2000)


class AgentChatOut(Schema):
    answer: str
    mode: Literal["local-deterministic", "external-ai"]
    provider: Literal["local", "openai", "openrouter"]
    model: str | None = None
    data_as_of: date
    pii_redactions: int
    external_transmission: bool
    sources: list[str]
    assumptions: list[str]


@router.get("/{investor_id}/agent/overview", response=AgentOverviewOut)
def agent_overview(request, investor_id: int):
    investor = get_owned_investor(request, investor_id)
    return {"generated_at": timezone.now(), **build_agent_overview(investor)}


@router.post("/{investor_id}/agent/chat", response=AgentChatOut)
def agent_chat(request, investor_id: int, payload: AgentChatIn):
    investor = get_owned_investor(request, investor_id)
    safe_message, redactions = redact_pii(payload.message)
    known_values = [
        investor.name,
        *investor.name.split(),
        investor.email,
        investor.get_pan(),
        getattr(request.user, "email", ""),
        *investor.folios.values_list("number", flat=True),
    ]
    safe_message, known_redactions = redact_known_pii(safe_message, known_values)
    redactions += known_redactions
    overview = build_agent_overview(investor)
    config = configured_provider()
    if config is not None:
        try:
            provider_answer = answer_with_provider(config, overview, safe_message)
        except ProviderError:
            logger.warning("External AI request failed; using local fallback")
        else:
            return {
                "answer": provider_answer.text,
                "mode": "external-ai",
                "provider": provider_answer.provider,
                "model": provider_answer.model,
                "data_as_of": overview["data_as_of"],
                "pii_redactions": redactions,
                "external_transmission": True,
                "sources": [
                    "Folioman deterministic portfolio context",
                    f"{provider_answer.provider} model response",
                ],
                "assumptions": overview["assumptions"],
            }
    return {
        "answer": answer_portfolio_question(overview, safe_message),
        "mode": "local-deterministic",
        "provider": "local",
        "model": None,
        "data_as_of": overview["data_as_of"],
        "pii_redactions": redactions,
        "external_transmission": False,
        "sources": ["Folioman holdings", "Folioman NAV history", "Folioman transaction ledger"],
        "assumptions": overview["assumptions"],
    }

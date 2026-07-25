"""Investor-scoped AI workspace and encrypted chat-session API."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema, Status
from pydantic import Field

from folioman_app.api.auth import get_owned_investor
from folioman_app.models import AgentChatMessage, AgentChatSession
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
    session_id: int | None = None


class AgentChatSessionIn(Schema):
    title: str | None = Field(default=None, min_length=1, max_length=80)


class AgentChatSessionUpdate(Schema):
    title: str = Field(min_length=1, max_length=80)


class AgentChatSessionOut(Schema):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class AgentChatMessageOut(Schema):
    id: int
    role: Literal["user", "assistant"]
    content: str
    provider: Literal["local", "openai", "openrouter"]
    model: str | None = None
    data_as_of: date | None = None
    pii_redactions: int
    external_transmission: bool
    created_at: datetime


class AgentChatSessionDetailOut(AgentChatSessionOut):
    messages: list[AgentChatMessageOut]


class AgentChatOut(Schema):
    session_id: int
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


def _owned_session(request, investor, session_id: int) -> AgentChatSession:
    return get_object_or_404(
        AgentChatSession,
        id=session_id,
        owned_by=request.auth,
        investor=investor,
    )


def _session_out(session: AgentChatSession) -> dict:
    return {
        "id": session.id,
        "title": session.get_title(),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _message_out(message: AgentChatMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.get_content(),
        "provider": message.provider,
        "model": message.model or None,
        "data_as_of": message.data_as_of,
        "pii_redactions": message.pii_redactions,
        "external_transmission": message.external_transmission,
        "created_at": message.created_at,
    }


def _generic_session_title() -> str:
    return timezone.localtime().strftime("Chat %d %b %Y, %H:%M")


@router.get("/{investor_id}/agent/sessions", response=list[AgentChatSessionOut])
def list_agent_chat_sessions(request, investor_id: int):
    investor = get_owned_investor(request, investor_id)
    sessions = AgentChatSession.objects.filter(owned_by=request.auth, investor=investor)
    return [_session_out(session) for session in sessions]


@router.post("/{investor_id}/agent/sessions", response={201: AgentChatSessionOut})
def create_agent_chat_session(request, investor_id: int, payload: AgentChatSessionIn):
    investor = get_owned_investor(request, investor_id)
    session = AgentChatSession(owned_by=request.auth, investor=investor)
    session.set_title(payload.title.strip() if payload.title else _generic_session_title())
    session.save()
    return Status(201, _session_out(session))


@router.get(
    "/{investor_id}/agent/sessions/{session_id}",
    response=AgentChatSessionDetailOut,
)
def get_agent_chat_session(request, investor_id: int, session_id: int):
    investor = get_owned_investor(request, investor_id)
    session = _owned_session(request, investor, session_id)
    return {
        **_session_out(session),
        "messages": [_message_out(message) for message in session.messages.all()],
    }


@router.patch(
    "/{investor_id}/agent/sessions/{session_id}",
    response=AgentChatSessionOut,
)
def update_agent_chat_session(
    request,
    investor_id: int,
    session_id: int,
    payload: AgentChatSessionUpdate,
):
    investor = get_owned_investor(request, investor_id)
    session = _owned_session(request, investor, session_id)
    session.set_title(payload.title.strip())
    session.save(update_fields=["title_encrypted", "updated_at"])
    return _session_out(session)


@router.delete(
    "/{investor_id}/agent/sessions/{session_id}",
    response={204: None},
)
def delete_agent_chat_session(request, investor_id: int, session_id: int):
    investor = get_owned_investor(request, investor_id)
    _owned_session(request, investor, session_id).delete()
    return Status(204, None)


@router.post("/{investor_id}/agent/chat", response=AgentChatOut)
def agent_chat(request, investor_id: int, payload: AgentChatIn):
    investor = get_owned_investor(request, investor_id)
    session = (
        _owned_session(request, investor, payload.session_id)
        if payload.session_id is not None
        else None
    )
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
    prior_messages = []
    if session is not None:
        recent = list(session.messages.order_by("-created_at", "-id")[:12])
        prior_messages = [
            {"role": message.role, "content": message.get_content()} for message in reversed(recent)
        ]

    config = configured_provider()
    answer = ""
    mode: Literal["local-deterministic", "external-ai"] = "local-deterministic"
    provider: Literal["local", "openai", "openrouter"] = "local"
    model: str | None = None
    external_transmission = False
    if config is not None:
        try:
            provider_answer = answer_with_provider(
                config,
                overview,
                safe_message,
                history=prior_messages,
            )
        except ProviderError:
            logger.warning("External AI request failed; using local fallback")
        else:
            answer = provider_answer.text
            mode = "external-ai"
            provider = provider_answer.provider
            model = provider_answer.model
            external_transmission = True
    if not answer:
        answer = answer_portfolio_question(overview, safe_message)

    with transaction.atomic():
        if session is None:
            session = AgentChatSession(owned_by=request.auth, investor=investor)
            session.set_title(_generic_session_title())
            session.save()
        user_message = AgentChatMessage(
            session=session,
            role=AgentChatMessage.Role.USER,
            provider="local",
            data_as_of=overview["data_as_of"],
            pii_redactions=redactions,
        )
        user_message.set_content(safe_message)
        user_message.save()
        assistant_message = AgentChatMessage(
            session=session,
            role=AgentChatMessage.Role.ASSISTANT,
            provider=provider,
            model=model or "",
            data_as_of=overview["data_as_of"],
            pii_redactions=redactions,
            external_transmission=external_transmission,
        )
        assistant_message.set_content(answer)
        assistant_message.save()
        session.updated_at = timezone.now()
        session.save(update_fields=["updated_at"])

    sources = ["Folioman holdings", "Folioman NAV history", "Folioman transaction ledger"]
    if external_transmission:
        sources = [
            "Folioman deterministic portfolio context",
            f"{provider} model response",
        ]
    return {
        "session_id": session.id,
        "answer": answer,
        "mode": mode,
        "provider": provider,
        "model": model,
        "data_as_of": overview["data_as_of"],
        "pii_redactions": redactions,
        "external_transmission": external_transmission,
        "sources": sources,
        "assumptions": overview["assumptions"],
    }

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from folioman_app.api import agent as agent_api
from folioman_app.models import Folio, NAVHistory
from folioman_app.services.llm import ProviderAnswer, ProviderConfig
from folioman_core.models import FolioType

pytestmark = pytest.mark.django_db


def test_agent_overview_is_deterministic_and_excludes_investor_pii(
    client, make_investor, make_security, make_holding
):
    investor = make_investor(name="Private Person", email="private@example.com")
    investor.set_pan("ABCDE1234F")
    investor.save()
    security = make_security(name="Example Equity Fund")
    make_holding(
        investor=investor,
        security=security,
        units=Decimal("100"),
        as_of_date=dt.date(2026, 7, 23),
    )
    NAVHistory.objects.create(
        security=security,
        date=dt.date(2026, 7, 23),
        nav=Decimal("50"),
    )

    response = client.get(f"/api/investors/{investor.id}/agent/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["privacy"]["external_transmission"] is False
    assert body["privacy"]["mode"] == "local-deterministic"
    assert Decimal(body["metrics"]["total_inr"]) == Decimal("5000")
    serialized = response.content.decode()
    assert "Private Person" not in serialized
    assert "private@example.com" not in serialized
    assert "ABCDE1234F" not in serialized


def test_agent_chat_redacts_explicit_pii_and_stays_local(client, make_investor):
    investor = make_investor()

    response = client.post(
        f"/api/investors/{investor.id}/agent/chat",
        data={
            "message": (
                "My PAN is ABCDE1234F, email me@example.com, "
                "phone 9876543210. What is my portfolio value?"
            )
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "local-deterministic"
    assert body["external_transmission"] is False
    assert body["pii_redactions"] == 3
    serialized = response.content.decode()
    assert "ABCDE1234F" not in serialized
    assert "me@example.com" not in serialized
    assert "9876543210" not in serialized


def test_agent_health_flags_concentrated_single_holding(
    client, make_investor, make_security, make_holding
):
    investor = make_investor()
    security = make_security(name="Only Fund")
    make_holding(investor=investor, security=security, units=Decimal("10"))
    NAVHistory.objects.create(
        security=security,
        date=dt.date.today(),
        nav=Decimal("100"),
    )

    body = client.get(f"/api/investors/{investor.id}/agent/overview").json()

    assert body["health_score"] < 100
    assert any(item["title"] == "Largest holding is concentrated" for item in body["findings"])


def test_external_chat_redacts_known_investor_identifiers(client, make_investor, monkeypatch):
    investor = make_investor(name="Private Person", email="private@example.com")
    investor.set_pan("ABCDE1234F")
    investor.save()
    Folio.objects.create(
        investor=investor,
        folio_type=FolioType.MF.value,
        number="123456789",
    )
    captured = {}
    config = ProviderConfig(
        provider="openrouter",
        model="example/model",
        api_key="secret",
    )
    monkeypatch.setattr(agent_api, "configured_provider", lambda: config)

    def fake_answer(_config, _overview, question):
        captured["question"] = question
        return ProviderAnswer(
            text="External explanation",
            provider="openrouter",
            model="example/model",
        )

    monkeypatch.setattr(agent_api, "answer_with_provider", fake_answer)

    response = client.post(
        f"/api/investors/{investor.id}/agent/chat",
        data={
            "message": (
                "Private Person private@example.com ABCDE1234F "
                "folio 123456789: explain my allocation"
            )
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "external-ai"
    assert body["provider"] == "openrouter"
    assert body["model"] == "example/model"
    assert body["external_transmission"] is True
    assert body["pii_redactions"] >= 4
    assert "Private Person" not in captured["question"]
    assert "private@example.com" not in captured["question"]
    assert "ABCDE1234F" not in captured["question"]
    assert "123456789" not in captured["question"]

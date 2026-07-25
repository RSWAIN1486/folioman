from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from folioman_app.api import agent as agent_api
from folioman_app.models import AgentChatMessage, AgentChatSession, Folio, NAVHistory
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
    assert body["session_id"]
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

    def fake_answer(_config, _overview, question, history=None):
        captured["question"] = question
        captured["history"] = history
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


def test_chat_persists_only_encrypted_redacted_content_and_reloads(client, make_investor):
    investor = make_investor(name="Private Person")

    chat_response = client.post(
        f"/api/investors/{investor.id}/agent/chat",
        data={"message": "My PAN is ABCDE1234F. What is my portfolio value?"},
        content_type="application/json",
    )

    assert chat_response.status_code == 200
    session_id = chat_response.json()["session_id"]
    session = AgentChatSession.objects.get(id=session_id)
    stored_messages = list(session.messages.all())
    assert len(stored_messages) == 2
    assert b"ABCDE1234F" not in bytes(stored_messages[0].content_encrypted)
    assert b"portfolio value" not in bytes(stored_messages[0].content_encrypted)
    assert b"Chat " not in bytes(session.title_encrypted)

    loaded = client.get(f"/api/investors/{investor.id}/agent/sessions/{session_id}")

    assert loaded.status_code == 200
    body = loaded.json()
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert "[PAN REDACTED]" in body["messages"][0]["content"]
    assert "ABCDE1234F" not in loaded.content.decode()


def test_chat_session_can_be_renamed_listed_and_deleted(client, make_investor):
    investor = make_investor()
    created = client.post(
        f"/api/investors/{investor.id}/agent/sessions",
        data={"title": "Retirement review"},
        content_type="application/json",
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    listed = client.get(f"/api/investors/{investor.id}/agent/sessions")
    assert [item["title"] for item in listed.json()] == ["Retirement review"]

    renamed = client.patch(
        f"/api/investors/{investor.id}/agent/sessions/{session_id}",
        data={"title": "Goal planning"},
        content_type="application/json",
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Goal planning"

    deleted = client.delete(f"/api/investors/{investor.id}/agent/sessions/{session_id}")
    assert deleted.status_code == 204
    assert not AgentChatSession.objects.filter(id=session_id).exists()


def test_chat_session_lookup_is_scoped_to_owner(client, make_investor):
    investor = make_investor()
    other_user = get_user_model().objects.create_user(username="other-advisor")
    session = AgentChatSession(owned_by=other_user, investor=investor)
    session.set_title("Other owner's chat")
    session.save()

    response = client.get(f"/api/investors/{investor.id}/agent/sessions/{session.id}")

    assert response.status_code == 404


def test_external_chat_receives_only_twelve_recent_redacted_messages(
    client,
    make_investor,
    monkeypatch,
):
    investor = make_investor()
    session = AgentChatSession(owned_by=investor.owned_by, investor=investor)
    session.set_title("History test")
    session.save()
    for index in range(14):
        message = AgentChatMessage(
            session=session,
            role=AgentChatMessage.Role.USER if index % 2 == 0 else AgentChatMessage.Role.ASSISTANT,
        )
        message.set_content(f"message-{index}")
        message.save()

    captured = {}
    config = ProviderConfig(provider="openrouter", model="example/model", api_key="secret")
    monkeypatch.setattr(agent_api, "configured_provider", lambda: config)

    def fake_answer(_config, _overview, _question, history=None):
        captured["history"] = history
        return ProviderAnswer(
            text="External explanation",
            provider="openrouter",
            model="example/model",
        )

    monkeypatch.setattr(agent_api, "answer_with_provider", fake_answer)

    response = client.post(
        f"/api/investors/{investor.id}/agent/chat",
        data={"message": "Continue", "session_id": session.id},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert len(captured["history"]) == 12
    assert captured["history"][0]["content"] == "message-2"
    assert captured["history"][-1]["content"] == "message-13"

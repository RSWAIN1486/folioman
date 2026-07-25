from __future__ import annotations

import datetime as dt
from decimal import Decimal

from folioman_app.services import llm


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "The portfolio is concentrated.",
                        }
                    ]
                }
            ]
        }


def test_openrouter_uses_fixed_endpoint_privacy_controls_and_allowlisted_context(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    config = llm.ProviderConfig(
        provider="openrouter",
        model="example/model",
        api_key="secret-key",
    )
    overview = {
        "data_as_of": dt.date(2026, 7, 25),
        "navs_as_of": dt.date(2026, 7, 24),
        "health_score": 70,
        "health_label": "Watch",
        "findings": [],
        "daily_brief": [],
        "metrics": {"total_inr": Decimal("1000")},
        "allocation": [],
        "top_holdings": [],
        "formula_notes": [],
        "assumptions": [],
        "investor_name": "Private Person",
        "email": "private@example.com",
        "raw_cas": "must never leave",
    }

    answer = llm.answer_with_provider(config, overview, "Explain the health score")

    assert answer.provider == "openrouter"
    assert captured["url"] == "https://openrouter.ai/api/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["store"] is False
    assert captured["json"]["provider"] == {
        "zdr": True,
        "data_collection": "deny",
    }
    outbound = captured["json"]["input"]
    assert "Private Person" not in outbound
    assert "private@example.com" not in outbound
    assert "must never leave" not in outbound


def test_provider_requires_matching_key_and_model(monkeypatch):
    monkeypatch.setenv("FOLIOMAN_AI_PROVIDER", "openrouter")
    monkeypatch.setenv("FOLIOMAN_AI_MODEL", "example/model")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert llm.configured_provider() is None

    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")

    assert llm.configured_provider() == llm.ProviderConfig(
        provider="openrouter",
        model="example/model",
        api_key="router-key",
    )


def test_openai_uses_responses_endpoint_without_openrouter_routing(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    config = llm.ProviderConfig(
        provider="openai",
        model="example-openai-model",
        api_key="openai-key",
    )
    overview = {
        "data_as_of": dt.date(2026, 7, 25),
        "navs_as_of": None,
        "health_score": 100,
        "health_label": "Strong",
        "findings": [],
        "daily_brief": [],
        "metrics": {"total_inr": Decimal("0")},
        "allocation": [],
        "top_holdings": [],
        "formula_notes": [],
        "assumptions": [],
    }

    answer = llm.answer_with_provider(config, overview, "Explain")

    assert answer.provider == "openai"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["json"]["store"] is False
    assert "provider" not in captured["json"]

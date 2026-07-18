"""NAV freshness API: per-security lag classification + refresh schedule."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from folioman_app.models import NAVHistory

pytestmark = pytest.mark.django_db


# 2025-06-04 is a Wednesday: the last *completed* trading day (the freshness
# baseline — NAVs for day T publish after T ends) is Tuesday 2025-06-03.
_TODAY = dt.date(2025, 6, 4)
_BASELINE = dt.date(2025, 6, 3)


@pytest.fixture
def freeze_today(monkeypatch):
    """Pin the freshness service's "today" (no freeze lib in the dep set)."""
    monkeypatch.setattr(
        "folioman_app.services.navs.timezone",
        SimpleNamespace(
            localdate=lambda: _TODAY,
            localtime=lambda: timezone.make_aware(dt.datetime.combine(_TODAY, dt.time(10, 0))),
            make_aware=timezone.make_aware,
        ),
    )


def _nav(security, on):
    NAVHistory.objects.create(security=security, date=on, nav=Decimal("10"))


def test_freshness_measures_lag_against_completed_trading_day(
    client, make_investor, make_security, make_holding, freeze_today
):
    """Tuesday's NAV is the freshest possible on a Wednesday — it must read
    "fresh", not "1 day behind" (NAVs publish after the trading day ends)."""
    inv = make_investor()
    fresh = make_security(name="Fresh Fund")
    grace = make_security(name="Grace Fund")
    stale = make_security(name="Stale Fund")
    pending = make_security(name="Pending Fund")  # amfi_code, no NAV yet
    closed = make_security(name="Closed Fund", nav_feed_closed=True)
    unmapped = make_security(name="Unmapped Fund", amfi_code="", isin="INF000000001")
    for s in (fresh, grace, stale, pending, closed, unmapped):
        make_holding(investor=inv, security=s)
    _nav(fresh, _BASELINE)  # Tuesday — the last completed trading day
    _nav(grace, _BASELINE - dt.timedelta(days=1))  # Monday → 1 trading day behind
    _nav(stale, _BASELINE - dt.timedelta(days=7))  # previous Tuesday → 5 behind
    _nav(closed, _BASELINE - dt.timedelta(days=30))

    body = client.get("/api/navs/freshness").json()

    assert body["as_of"] == _BASELINE.isoformat()
    by_name = {r["name"]: r for r in body["securities"]}
    assert by_name["Fresh Fund"]["status"] == "fresh"
    assert by_name["Fresh Fund"]["lag_trading_days"] == 0
    assert by_name["Grace Fund"]["status"] == "grace"
    assert by_name["Grace Fund"]["lag_trading_days"] == 1
    assert by_name["Stale Fund"]["status"] == "stale"
    assert by_name["Stale Fund"]["lag_trading_days"] == 5
    assert by_name["Pending Fund"]["status"] == "pending"
    assert by_name["Pending Fund"]["latest_nav_date"] is None
    assert by_name["Closed Fund"]["status"] == "closed"
    assert by_name["Unmapped Fund"]["status"] == "no_feed"
    # Worst first: the stale row leads, fresh trails.
    assert body["securities"][0]["name"] == "Stale Fund"
    assert body["securities"][-1]["name"] == "Fresh Fund"


def test_freshness_baseline_rolls_weekends_back_to_friday(
    client, make_investor, make_security, make_holding, monkeypatch
):
    # On a Monday the last completed trading day is the previous Friday.
    monday = dt.date(2025, 6, 2)
    monkeypatch.setattr(
        "folioman_app.services.navs.timezone",
        SimpleNamespace(
            localdate=lambda: monday,
            localtime=lambda: timezone.make_aware(dt.datetime.combine(monday, dt.time(10, 0))),
            make_aware=timezone.make_aware,
        ),
    )
    inv = make_investor()
    fund = make_security(name="Weekend Fund")
    make_holding(investor=inv, security=fund)
    _nav(fund, dt.date(2025, 5, 30))  # Friday

    body = client.get("/api/navs/freshness").json()

    assert body["as_of"] == "2025-05-30"
    assert body["securities"][0]["status"] == "fresh"


def test_freshness_scopes_to_advisors_book(
    client, make_investor, make_security, make_holding, freeze_today
):
    inv = make_investor()
    held = make_security(name="Held Fund")
    make_security(name="Unheld Fund")  # in master data, in nobody's book
    make_holding(investor=inv, security=held)

    body = client.get("/api/navs/freshness").json()

    assert [r["name"] for r in body["securities"]] == ["Held Fund"]


def test_freshness_reports_history_range_and_refresh_schedule(
    client, make_investor, make_security, make_holding, freeze_today
):
    inv = make_investor()
    fund = make_security(name="Ranged Fund")
    make_holding(investor=inv, security=fund)
    _nav(fund, dt.date(2024, 1, 1))
    _nav(fund, dt.date(2025, 3, 1))
    _nav(fund, _BASELINE)

    body = client.get("/api/navs/freshness").json()

    row = body["securities"][0]
    assert row["first_nav_date"] == "2024-01-01"
    assert row["latest_nav_date"] == _BASELINE.isoformat()
    assert row["points"] == 3
    # Schedule: frozen "now" is 10:00 sharp, so the next 04/10/16/22 pass is 16:00
    # today (a run scheduled for the current hour has already fired).
    assert body["next_refresh_at"].startswith("2025-06-04T16:00:00")
    assert body["last_refreshed_at"] is not None


def test_manual_refresh_scopes_to_the_advisors_book_and_returns_updated_freshness(
    client, make_investor, make_security, make_holding, freeze_today, monkeypatch
):
    inv = make_investor()
    owned = make_security(name="Owned Fund")
    make_holding(investor=inv, security=owned)

    other_user = get_user_model().objects.create_user(username="other")
    other_inv = make_investor(name="Other Investor", owned_by=other_user)
    other_sec = make_security(name="Other Fund")
    make_holding(investor=other_inv, security=other_sec)

    calls: dict[str, list] = {"mf": [], "eq": [], "refresh": [], "recompute": []}

    def _ids(securities) -> list[int]:
        return list(securities.values_list("id", flat=True))

    monkeypatch.setattr(
        "folioman_app.api.navs.backfill_missing_history",
        lambda *, securities: calls["mf"].append(_ids(securities)) or {"points": 0},
    )
    monkeypatch.setattr(
        "folioman_app.api.navs.backfill_missing_equity_history",
        lambda *, securities: calls["eq"].append(_ids(securities)) or {"points": 0},
    )

    def fake_refresh_navs(*, securities):
        sec_ids = _ids(securities)
        calls["refresh"].append(sec_ids)
        assert other_sec.id not in sec_ids
        NAVHistory.objects.create(security=owned, date=_BASELINE, nav=Decimal("42"))
        return {"updated": 1, "skipped": 0, "errors": 0}

    monkeypatch.setattr("folioman_app.api.navs.refresh_navs", fake_refresh_navs)
    monkeypatch.setattr(
        "folioman_app.api.navs.recompute_investor_valuation",
        lambda investor_id, prime_navs=False: (
            calls["recompute"].append((investor_id, prime_navs)) or "ready"
        ),
    )

    body = client.post("/api/navs/refresh").json()

    assert body["updated"] == 1
    assert body["skipped"] == 0
    assert body["errors"] == 0
    assert [row["name"] for row in body["freshness"]["securities"]] == ["Owned Fund"]
    assert body["freshness"]["securities"][0]["status"] == "fresh"
    assert calls["mf"] == [[owned.id]]
    assert calls["eq"] == [[]]
    assert calls["refresh"] == [[owned.id]]
    assert calls["recompute"] == [(inv.id, False)]

"""NAVs router: per-security freshness plus a bounded manual refresh.

The GET endpoint powers the Settings panel's per-security freshness view. The
POST endpoint is the user-triggered counterpart to the 6-hour scheduler pass:
it refreshes only the authenticated advisor's book, then recomputes those
investors' day-wise values synchronously so the UI sees updated totals
immediately instead of waiting for the next pending-valuation tick.
"""

from __future__ import annotations

from folioman_core.models import SecurityType
from ninja import Router

from folioman_app.api.auth import investors_for
from folioman_app.api.schemas import NavFreshnessOut, NavRefreshOut
from folioman_app.models import Security
from folioman_app.services.navs import build_nav_freshness
from folioman_app.tasks.refresh_navs import (
    backfill_missing_equity_history,
    backfill_missing_history,
    refresh_navs,
)
from folioman_app.tasks.valuation_jobs import recompute_investor_valuation

router = Router(tags=["navs"])

_QUOTE_TYPES = (
    SecurityType.EQUITY.value,
    SecurityType.ETF.value,
    SecurityType.BOND.value,
    SecurityType.FOREIGN_EQUITY.value,
)


def _security_ids(investors) -> set[int]:
    sec_ids: set[int] = set()
    for investor in investors:
        sec_ids.update(investor.transactions.values_list("security_id", flat=True))
        sec_ids.update(investor.holdings.values_list("security_id", flat=True))
    return sec_ids


@router.get("/navs/freshness", response=NavFreshnessOut)
def nav_freshness(request):
    """Every tracked security's latest NAV date + trading-day lag, worst first."""
    return build_nav_freshness(investors_for(request))


@router.post("/navs/refresh", response=NavRefreshOut)
def refresh_navs_now(request):
    """Refresh the caller's tracked prices now, then recompute their values."""
    investors = list(investors_for(request))
    sec_ids = _security_ids(investors)
    summary = {"updated": 0, "skipped": 0, "errors": 0}
    if sec_ids:
        securities = Security.objects.filter(id__in=sec_ids)
        backfill_missing_history(securities=securities.filter(security_type=SecurityType.MF.value))
        backfill_missing_equity_history(
            securities=securities.filter(security_type__in=sorted(_QUOTE_TYPES))
        )
        summary = refresh_navs(securities=securities)
    for investor in investors:
        recompute_investor_valuation(investor.id, prime_navs=False)
    return {**summary, "freshness": build_nav_freshness(investors)}

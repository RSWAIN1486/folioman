"""Deterministic, de-identified portfolio analysis for the AI workspace.

No investor identity, PAN, email, folio/account number, raw CAS text, or
transaction narration enters the context returned here. The same compact
context is the only payload a future external model adapter may receive.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from folioman_app.services.valuation import build_investor_summary

_ZERO = Decimal("0")
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)")
_ACCOUNT_RE = re.compile(
    r"\b(?:folio|account|a/c)\s*(?:number|no\.?|#)?\s*[:=-]?\s*[A-Z0-9/-]{5,}\b",
    re.IGNORECASE,
)

EXCLUDED_PII_FIELDS = [
    "investor name",
    "PAN",
    "email",
    "phone number",
    "folio and account numbers",
    "raw CAS text",
    "transaction narration and source references",
]


def redact_pii(text: str) -> tuple[str, int]:
    """Remove common explicit identifiers before any chat text leaves the API boundary."""
    redacted = text
    count = 0
    for pattern, label in (
        (_PAN_RE, "[PAN REDACTED]"),
        (_EMAIL_RE, "[EMAIL REDACTED]"),
        (_PHONE_RE, "[PHONE REDACTED]"),
        (_ACCOUNT_RE, "[ACCOUNT REDACTED]"),
    ):
        redacted, matches = pattern.subn(label, redacted)
        count += matches
    return redacted, count


def redact_known_pii(text: str, values: list[str | None]) -> tuple[str, int]:
    """Remove exact identifiers known locally but not reliably detected by patterns."""
    redacted = text
    count = 0
    candidates = {
        value.strip() for value in values if isinstance(value, str) and len(value.strip()) >= 3
    }
    for value in sorted(candidates, key=len, reverse=True):
        redacted, matches = re.subn(re.escape(value), "[IDENTIFIER REDACTED]", redacted, flags=re.I)
        count += matches
    return redacted, count


def _pct(value: Decimal | float | None, total: Decimal) -> float:
    if value is None or total <= _ZERO:
        return 0.0
    return round(float(Decimal(str(value)) / total * 100), 2)


def _inr(value: Decimal | float | None) -> str:
    if value is None:
        return "not available"
    return f"INR {Decimal(str(value)):,.0f}"


def _percent(value: float | None) -> str:
    if value is None:
        return "not available"
    return f"{value * 100:.2f}%"


def build_agent_overview(investor, as_of: date | None = None) -> dict:
    """Build deterministic agent modules from aggregate, identity-free portfolio data."""
    summary = build_investor_summary(investor, as_of or date.today())
    total = Decimal(str(summary["total_inr"]))
    holdings = summary["holdings"]
    findings: list[dict] = []
    score = 100

    if not holdings:
        findings.append(
            {
                "severity": "info",
                "title": "No priced holdings yet",
                "detail": "Import a CAS and refresh prices before portfolio analysis is available.",
                "metric": None,
            }
        )

    if summary["needs_attention_count"]:
        count = summary["needs_attention_count"]
        score -= min(25, count * 8)
        findings.append(
            {
                "severity": "critical",
                "title": "Ledger integrity needs attention",
                "detail": (
                    f"{count} holding reconciliation unit{'s' if count != 1 else ''} "
                    "must be resolved before relying on tax or cost-basis analysis."
                ),
                "metric": f"{count} unresolved",
            }
        )

    pricing_gaps = summary["stale_count"] + summary["unpriced_fund_count"]
    if pricing_gaps:
        score -= min(20, pricing_gaps * 5)
        findings.append(
            {
                "severity": "warning",
                "title": "Pricing coverage is incomplete",
                "detail": "Refresh NAVs before acting on current-value or one-day analysis.",
                "metric": f"{pricing_gaps} pricing gaps",
            }
        )

    if holdings and total > _ZERO:
        top = holdings[0]
        top_share = _pct(top["value_inr"], total)
        if top_share >= 20:
            score -= 15
            findings.append(
                {
                    "severity": "warning",
                    "title": "Largest holding is concentrated",
                    "detail": (
                        f"The largest scheme represents {top_share:.2f}% of current value. "
                        "Review whether this matches the intended allocation."
                    ),
                    "metric": f"{top_share:.2f}%",
                }
            )
        elif top_share >= 12:
            score -= 6
            findings.append(
                {
                    "severity": "info",
                    "title": "Largest holding is worth monitoring",
                    "detail": (f"The largest scheme represents {top_share:.2f}% of current value."),
                    "metric": f"{top_share:.2f}%",
                }
            )

    if summary["amc_mix"] and total > _ZERO:
        top_amc = summary["amc_mix"][0]
        amc_share = _pct(top_amc["value_inr"], total)
        if amc_share >= 35:
            score -= 12
            findings.append(
                {
                    "severity": "warning",
                    "title": "Fund-house concentration",
                    "detail": (
                        f"{top_amc['label']} accounts for {amc_share:.2f}% of current value."
                    ),
                    "metric": f"{amc_share:.2f}%",
                }
            )

    if summary["integrity_unit_count"]:
        tax_ready_share = round(
            summary["tax_ready_count"] / summary["integrity_unit_count"] * 100,
            2,
        )
        if tax_ready_share < 100:
            findings.append(
                {
                    "severity": "info",
                    "title": "Tax analysis has partial coverage",
                    "detail": (
                        "Only reconciled full-history holdings are safe for tax-lot calculations."
                    ),
                    "metric": f"{tax_ready_share:.2f}% tax-ready",
                }
            )

    score = max(0, min(100, score))
    health_label = "Strong" if score >= 85 else "Watch" if score >= 65 else "Needs attention"

    day_change = summary["day_change_inr"]
    brief = [
        f"Portfolio value is {_inr(total)} as of {summary['as_of'].isoformat()}.",
        (
            f"Latest trading-day change is {_inr(day_change)}."
            if day_change is not None
            else "Latest trading-day change is not available from the current price history."
        ),
        f"Lifetime money-weighted return is {_percent(summary['xirr'])}.",
        (
            f"{summary['holdings_count']} current holdings; "
            f"{summary['needs_attention_count']} integrity items need attention."
        ),
    ]

    allocation = [
        {
            "label": row["label"],
            "value_inr": row["value_inr"],
            "share_pct": _pct(row["value_inr"], total),
        }
        for row in summary["category_mix"]
    ]
    top_holdings = [
        {
            "label": f"Holding {index}",
            "security_name": row["name"],
            "value_inr": row["value_inr"],
            "share_pct": _pct(row["value_inr"], total),
            "day_change_inr": row["day_change_inr"],
        }
        for index, row in enumerate(holdings[:5], start=1)
    ]

    return {
        "data_as_of": summary["as_of"],
        "navs_as_of": summary["navs_as_of"],
        "privacy": {
            "mode": "local-deterministic",
            "external_transmission": False,
            "excluded_fields": EXCLUDED_PII_FIELDS,
        },
        "health_score": score,
        "health_label": health_label,
        "findings": findings,
        "daily_brief": brief,
        "metrics": {
            "total_inr": total,
            "day_change_inr": day_change,
            "xirr": summary["xirr"],
            "holdings_count": summary["holdings_count"],
            "tax_ready_count": summary["tax_ready_count"],
            "integrity_unit_count": summary["integrity_unit_count"],
        },
        "allocation": allocation,
        "top_holdings": top_holdings,
        "formula_notes": [
            "Holding share = holding current value / total current portfolio value.",
            "Fund-house share = fund-house current value / total current portfolio value.",
            "Health score starts at 100 and deducts explicit penalties for integrity, "
            "pricing, holding-concentration, and fund-house-concentration findings.",
            "Latest-day change uses the latest two available trading-day prices, "
            "not calendar days.",
            "XIRR is the persisted portfolio money-weighted annualised return.",
        ],
        "assumptions": [
            "Current values use the latest NAV or market price available on the data date.",
            "Concentration findings are prompts for review, not buy or sell recommendations.",
            "Tax analysis is limited to reconciled, full-history holdings.",
        ],
    }


def answer_portfolio_question(overview: dict, message: str) -> str:
    """Answer a small, transparent set of portfolio questions without an external model."""
    question = message.casefold()
    metrics = overview["metrics"]

    if any(word in question for word in ("health", "risk", "attention", "problem")):
        findings = overview["findings"]
        if not findings:
            return (
                f"The deterministic health score is {overview['health_score']}/100 "
                "and no configured checks produced a finding."
            )
        titles = "; ".join(item["title"] for item in findings[:4])
        return (
            f"The deterministic health score is {overview['health_score']}/100 "
            f"({overview['health_label']}). Current findings: {titles}."
        )
    if any(word in question for word in ("today", "1 day", "daily", "change")):
        return overview["daily_brief"][1]
    if any(word in question for word in ("xirr", "return", "performance")):
        return (
            f"Lifetime money-weighted return is {_percent(metrics['xirr'])}. "
            "This is XIRR over portfolio cashflows and the current terminal value."
        )
    if any(word in question for word in ("allocation", "equity", "debt", "category")):
        if not overview["allocation"]:
            return "Allocation is unavailable because there are no priced holdings."
        parts = [f"{row['label']} {row['share_pct']:.2f}%" for row in overview["allocation"]]
        return "Current category allocation: " + ", ".join(parts) + "."
    if any(word in question for word in ("largest", "holding", "concentration")):
        if not overview["top_holdings"]:
            return "Holding concentration is unavailable because there are no priced holdings."
        row = overview["top_holdings"][0]
        return (
            f"The largest holding is {row['security_name']} at {row['share_pct']:.2f}% "
            f"of portfolio value ({_inr(row['value_inr'])})."
        )
    if any(word in question for word in ("tax", "cost basis", "capital gain")):
        return (
            f"{metrics['tax_ready_count']} of {metrics['integrity_unit_count']} "
            "holding reconciliation units are tax-ready. Only full-history, "
            "reconciled units should feed tax-lot calculations."
        )
    if any(word in question for word in ("value", "worth", "portfolio")):
        return (
            f"Current portfolio value is {_inr(metrics['total_inr'])} as of "
            f"{overview['data_as_of'].isoformat()}."
        )
    return (
        "Local analysis mode can currently discuss portfolio value, latest-day change, "
        "XIRR, allocation, concentration, integrity, and tax readiness. An external AI "
        "provider is not configured, so no message or portfolio data was transmitted."
    )

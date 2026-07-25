## Completed
- Added an investor-scoped AI workspace to the shared web/desktop frontend with Portfolio Health, Daily Brief, Goals & SIP, Fund Research, Scheme Monitor, Tax Planner, What-If, and local portfolio Chat modules.
- Added a deterministic, owner-scoped agent API with an allow-listed portfolio context, explicit formulas/data dates, identifier redaction, and no trade execution.
- Added optional OpenAI and OpenRouter chat explanations with server-only credentials, deterministic local fallback, provider/model disclosure, and explicit external-transmission status.
- Added owner/investor-scoped AI chat sessions with Fernet-encrypted redacted messages, refresh restoration through the URL, multiple-session history, rename/delete controls, and a 12-message provider context limit.
- Added a dedicated local Caddy override for loopback HTTPS using Caddy's internal development CA; the hosted override remains public-domain-only.
- Chat now sends on Enter while retaining Shift+Enter for multi-line questions.
- Added manual price-refresh actions in the Dashboard header and Settings → NAV freshness that refresh the advisor's tracked prices and recompute values immediately in both desktop and hosted/server mode.
- Replaced the fixed dashboard 1D-return card with a return-window selector (1 day through all time) and a dedicated all-time return block in the shared web/desktop frontend.
- Enabled mouse-wheel and trackpad zoom on value charts, with Y-axis bounds that rescale to the visible period, while retaining the draggable overview slider.
- Added Buy/Sell transaction markers to portfolio, asset-class, and individual-security value charts; the dashboard value chart now opens on all-time history.
- Automatic price refresh still runs on the shared 6-hour scheduler, with optional OS-level refresh while the desktop app is closed.

## In Progress
- Planned docs called out in [README.md](./README.md) are still being filled in as their features settle.

## Decisions
- AI calculations remain deterministic and server-side; external models only explain an allow-listed context, and local deterministic chat remains the fallback when configuration is absent or a provider fails.
- Agent context excludes investor identity, PAN, email, folio/account identifiers, raw CAS text, transaction narration, and source references; exact known-identifier and pattern redaction are defence-in-depth rather than the primary privacy control.
- OpenAI chat requests use `store=false`; OpenRouter requests additionally enforce per-request ZDR routing and deny provider data collection.
- Raw chat questions are never persisted: known and pattern-based PII redaction runs first, then the redacted question, assistant response, and session title are encrypted with Folioman's Fernet key.
- Capped `cryptography` below 49 because its locked macOS wheel failed to load against the local OpenSSL runtime; 48.0.1 restores desktop tests without changing the Fernet API.
- Manual price refresh is advisor-scoped and reuses the same backfill plus valuation pipeline as the scheduled refresh path.
- The investor dashboard's return-window card is computed client-side from the persisted value series plus the investor's ledger cashflows; `1D` is a special case that uses the backend's last-trading-day delta, and all-time gain uses lifetime net cashflows so exited holdings stay reflected.
- Read-only/demo instances keep the manual refresh control hidden; the backend still enforces write locks.
- Local server-mode source runs mirror Docker's split runtime: keep `folioman_server` and `folioman_server run-scheduler` running separately, or dashboards stay provisional after imports.
- MF catch-up backfill now repairs a missing previous trading-day NAV even when the latest NAV is already present, so dashboard 1D return uses the true latest two trading days in server mode.
- Memory-constrained Docker hosts run one Gunicorn worker with two threads; the valuation scheduler remains a singleton.

## Blockers
- None currently tracked.

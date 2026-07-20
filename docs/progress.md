## Completed
- Added manual price-refresh actions in the Dashboard header and Settings → NAV freshness that refresh the advisor's tracked prices and recompute values immediately in both desktop and hosted/server mode.
- Replaced the fixed dashboard 1D-return card with a return-window selector (1 day through all time) and a dedicated all-time return block in the shared web/desktop frontend.
- Automatic price refresh still runs on the shared 6-hour scheduler, with optional OS-level refresh while the desktop app is closed.

## In Progress
- Planned docs called out in [README.md](./README.md) are still being filled in as their features settle.

## Decisions
- Manual price refresh is advisor-scoped and reuses the same backfill plus valuation pipeline as the scheduled refresh path.
- The investor dashboard's return-window card is computed client-side from the persisted value series plus the investor's ledger cashflows; `1D` is a special case that uses the backend's last-trading-day delta, and all-time gain uses lifetime net cashflows so exited holdings stay reflected.
- Read-only/demo instances keep the manual refresh control hidden; the backend still enforces write locks.
- Local server-mode source runs mirror Docker's split runtime: keep `folioman_server` and `folioman_server run-scheduler` running separately, or dashboards stay provisional after imports.
- MF catch-up backfill now repairs a missing previous trading-day NAV even when the latest NAV is already present, so dashboard 1D return uses the true latest two trading days in server mode.

## Blockers
- None currently tracked.

# AI workspace

Folioman's investor-scoped AI workspace is an analysis-only surface shared by
the desktop and hosted web apps. It does not place, queue, or expose buy/sell
orders.

## Modules

- **Portfolio Health** computes an explicit score from ledger integrity, pricing
  coverage, largest-holding concentration, and fund-house concentration.
- **Daily Brief** explains current value, the latest available trading-day
  change, lifetime XIRR, and integrity status.
- **Goals & SIP** provides a deterministic monthly-contribution projection from
  a target, horizon, expected return, and current portfolio value.
- **Fund Research** prioritises current holdings for review. External AMC/SEBI
  disclosure ingestion is not connected yet.
- **Scheme Monitor** shows NAV and integrity monitoring. Scheme disclosure
  change detection is pending.
- **Tax Planner** reports verified tax-lot coverage and links to the existing
  capital-gains worksheet.
- **What-If** applies a simple portfolio-wide drawdown sensitivity.
- **Chat** always uses deterministic server calculations as its portfolio
  context. It answers locally by default and can optionally use OpenAI or
  OpenRouter to explain that context.

Every result includes the portfolio data date, formulas, sources, assumptions,
and transmission mode.

## Privacy boundary

The backend constructs agent context from aggregate values, allocation,
security names, performance metrics, and integrity counts. It never reads the
investor's name, encrypted PAN, PAN hash, email, folio/account numbers, raw CAS
text, transaction narration, or source references into that context.

Chat applies defence-in-depth redaction for the selected investor's known name,
email, PAN and folio numbers, plus common PAN, email, Indian phone, and labelled
account/folio patterns. Messages are not persisted by Folioman.

External requests receive only an explicit allow-list: dates, deterministic
metrics, findings, allocation, current scheme names/values, formula notes, and
assumptions. They never receive an ORM object, database row, raw CAS document,
or transaction narration. OpenAI requests set `store=false`. OpenRouter
requests set `store=false`, require Zero Data Retention routing, and deny data
collection per request.

Free-form text can contain identifiers that local pattern matching does not
recognise. The UI therefore warns users not to paste personal identifiers. The
allow-listed portfolio context, exact known-identifier redaction, provider
privacy controls, and pattern redaction are separate layers; none should be
treated as sufficient alone.

## External chat providers

External chat is opt-in. With incomplete or failed configuration, the endpoint
falls back to local deterministic analysis.

| Variable | Values | Purpose |
|---|---|---|
| `FOLIOMAN_AI_PROVIDER` | `local`, `openai`, `openrouter` | Selects the server-side provider. Defaults to `local`. |
| `FOLIOMAN_AI_MODEL` | Provider model ID | Required for external chat. No model is silently selected. |
| `OPENAI_API_KEY` | OpenAI project key | Required only when provider is `openai`. |
| `OPENROUTER_API_KEY` | OpenRouter key | Required only when provider is `openrouter`. |

OpenAI example:

```dotenv
FOLIOMAN_AI_PROVIDER=openai
FOLIOMAN_AI_MODEL=your-openai-model-id
OPENAI_API_KEY=your-server-side-key
```

OpenRouter example:

```dotenv
FOLIOMAN_AI_PROVIDER=openrouter
FOLIOMAN_AI_MODEL=provider/model-id
OPENROUTER_API_KEY=your-server-side-key
```

For Docker, put the variables in git-ignored `server/.env` and recreate the
`app` service. The scheduler does not receive AI credentials. For repo-local
server or desktop source runs, put them in the git-ignored root `.env` or export
them in the launching shell. Never use a `VITE_*` variable for an AI key.

The packaged desktop app does not yet provide OS-keychain-based AI credential
storage. Do not embed a provider key in a distributable desktop build.

## API

- `GET /api/investors/{investor_id}/agent/overview`
- `POST /api/investors/{investor_id}/agent/chat`

Both routes use the existing owner-scoped investor lookup and therefore return
404 for an investor belonging to another authenticated user.

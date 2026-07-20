import { computed, getCurrentScope, onScopeDispose, ref, watch, type Ref } from 'vue'
import { api, type Schemas } from '@/api/client'
import type { AllocationSlice } from '@/components/charts/AllocationDonut.vue'
import type { ValuePoint } from '@/components/charts/PortfolioValueChart.vue'
import { toIntegrityStatus, type IntegrityStatus } from '@/integrity/status'
import { useIntegrityStore } from '@/stores/integrity'
import { useUiStore } from '@/stores/ui'
import { formatDate } from '@/utils/format'

const POLL_MS = 5000
const POLL_MAX_TICKS = 120 // ~10 min cap
import {
  ASSET_META,
  RANGES,
  assetColor,
  assetLabel,
  categoryColor,
  num,
  rampColor,
  shortAmc,
  type RangeKey,
} from '@/utils/portfolio'

export type { RangeKey }

export type ReturnWindowKey =
  | '1D'
  | '1W'
  | '1M'
  | '3M'
  | '6M'
  | '1Y'
  | '3Y'
  | '5Y'
  | '7Y'
  | '10Y'
  | 'All'

export interface ReturnWindowOption {
  label: string
  value: ReturnWindowKey
}

export interface PeriodReturn {
  amount: number
  annualizedPercent: number | null
  fromDate: string
  toDate: string
  direction: 'gain' | 'loss' | 'flat'
  isAllTime: boolean
}

const RETURN_WINDOW_OPTIONS: ReturnWindowOption[] = [
  { label: '1 day', value: '1D' },
  { label: '1 week', value: '1W' },
  { label: '1 month', value: '1M' },
  { label: '3 months', value: '3M' },
  { label: '6 months', value: '6M' },
  { label: '1 year', value: '1Y' },
  { label: '3 years', value: '3Y' },
  { label: '5 years', value: '5Y' },
  { label: '7 years', value: '7Y' },
  { label: '10 years', value: '10Y' },
  { label: 'All time', value: 'All' },
]

type ValuePointWithIso = ValuePoint
type DashboardTransaction = Schemas['TransactionOut']
type SignedFlow = { date: string; amount: number }

const _CASH_IN_TYPES = new Set(['buy', 'transfer_in'])
const _CASH_OUT_TYPES = new Set(['sell', 'transfer_out', 'dividend'])

function _parseIsoDate(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day))
}

function _toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function _addDays(iso: string, days: number): string {
  const d = _parseIsoDate(iso)
  d.setUTCDate(d.getUTCDate() + days)
  return _toIsoDate(d)
}

function _addMonths(iso: string, months: number): string {
  const d = _parseIsoDate(iso)
  const year = d.getUTCFullYear()
  const month = d.getUTCMonth()
  const day = d.getUTCDate()
  const targetMonth = month + months
  const firstOfTarget = new Date(Date.UTC(year, targetMonth, 1))
  const lastDay = new Date(Date.UTC(firstOfTarget.getUTCFullYear(), firstOfTarget.getUTCMonth() + 1, 0))
  firstOfTarget.setUTCDate(Math.min(day, lastDay.getUTCDate()))
  return _toIsoDate(firstOfTarget)
}

function _addYears(iso: string, years: number): string {
  return _addMonths(iso, years * 12)
}

function _daysBetween(startIso: string, endIso: string): number {
  return Math.round((_parseIsoDate(endIso).getTime() - _parseIsoDate(startIso).getTime()) / 86400000)
}

function _shiftReturnWindow(endIso: string, window: ReturnWindowKey): string {
  switch (window) {
    case '1D':
      return _addDays(endIso, -1)
    case '1W':
      return _addDays(endIso, -7)
    case '1M':
      return _addMonths(endIso, -1)
    case '3M':
      return _addMonths(endIso, -3)
    case '6M':
      return _addMonths(endIso, -6)
    case '1Y':
      return _addYears(endIso, -1)
    case '3Y':
      return _addYears(endIso, -3)
    case '5Y':
      return _addYears(endIso, -5)
    case '7Y':
      return _addYears(endIso, -7)
    case '10Y':
      return _addYears(endIso, -10)
    case 'All':
      return endIso
  }
}

function _transactionCash(txn: DashboardTransaction): number {
  return txn.amount == null ? num(txn.units) * num(txn.nav_or_price) : num(txn.amount)
}

function _signedFlows(transactions: DashboardTransaction[], fromDate: string, toDate: string): SignedFlow[] {
  return transactions
    .filter((txn) => txn.date > fromDate && txn.date <= toDate)
    .flatMap<SignedFlow>((txn) => {
      const cash = _transactionCash(txn)
      if (_CASH_IN_TYPES.has(txn.transaction_type)) return [{ date: txn.date, amount: cash }]
      if (_CASH_OUT_TYPES.has(txn.transaction_type) && cash) return [{ date: txn.date, amount: -cash }]
      return []
    })
}

type CashFlow = { date: string; amount: number }

function _yearFraction(startIso: string, endIso: string): number {
  return _daysBetween(startIso, endIso) / 365
}

function _npv(rate: number, flows: CashFlow[]): number {
  const startIso = flows[0]?.date
  if (!startIso) return 0
  return flows.reduce(
    (sum, flow) => sum + flow.amount / (1 + rate) ** _yearFraction(startIso, flow.date),
    0,
  )
}

function _npvDerivative(rate: number, flows: CashFlow[]): number {
  const startIso = flows[0]?.date
  if (!startIso) return 0
  return flows.reduce((sum, flow) => {
    const years = _yearFraction(startIso, flow.date)
    return sum + (-years * flow.amount) / (1 + rate) ** (years + 1)
  }, 0)
}

function _bisectXirr(flows: CashFlow[], tolerance: number, low = -0.999999, high = 100): number | null {
  let fLow = _npv(low, flows)
  let fHigh = _npv(high, flows)
  if ((fLow > 0) === (fHigh > 0)) return null
  for (let i = 0; i < 200; i += 1) {
    const mid = (low + high) / 2
    const fMid = _npv(mid, flows)
    if (Math.abs(fMid) < tolerance || (high - low) / 2 < tolerance) return mid
    if ((fMid > 0) === (fLow > 0)) {
      low = mid
      fLow = fMid
    } else {
      high = mid
      fHigh = fMid
    }
  }
  return (low + high) / 2
}

function _computeXirr(flows: CashFlow[]): number | null {
  if (flows.length < 2) return null
  const dated = [...flows].sort((a, b) => a.date.localeCompare(b.date))
  const hasInflow = dated.some((flow) => flow.amount > 0)
  const hasOutflow = dated.some((flow) => flow.amount < 0)
  if (!hasInflow || !hasOutflow) return null
  const tolerance = 1e-7
  let rate = 0.1
  for (let i = 0; i < 100; i += 1) {
    const npv = _npv(rate, dated)
    if (Math.abs(npv) < tolerance) return rate
    const derivative = _npvDerivative(rate, dated)
    if (Math.abs(derivative) < tolerance) break
    let nextRate = rate - npv / derivative
    if (nextRate <= -0.999999) nextRate = -0.999999
    if (Math.abs(nextRate - rate) < tolerance) return nextRate
    rate = nextRate
  }
  return _bisectXirr(dated, tolerance)
}

function _cashflowsFromTransactions(
  flows: SignedFlow[],
  presentDate: string,
  presentValue: number,
): CashFlow[] {
  const byDate = new Map<string, number>()
  for (const flow of [...flows].sort((a, b) => a.date.localeCompare(b.date))) {
    byDate.set(flow.date, (byDate.get(flow.date) ?? 0) + flow.amount)
  }
  const cashflows = [...byDate.entries()].map(([date, amount]) => ({ date, amount: -amount }))
  cashflows.push({ date: presentDate, amount: presentValue })
  return cashflows
}

function _direction(value: number): 'gain' | 'loss' | 'flat' {
  return value > 0 ? 'gain' : value < 0 ? 'loss' : 'flat'
}

export interface HoldingRow {
  securityId: number
  name: string
  securityType: string // 'mf' | 'equity' | 'etf' | … — the asset-class grouping key
  assetClass: string // display label for securityType (Mutual funds, Stocks, …)
  color: string // asset-class swatch colour (var(--fm-asset-*))
  value: number
  units: number
  invested: number | null // cost basis in ₹; null when unknown (eCAS snapshot)
  gain: number | null // value − invested, in ₹; null when cost basis is unknown
  returnPct: number | null // percent; null when cost basis is unknown
  integrity: IntegrityStatus
}

// A stock on the Stocks tab: a holding plus its ticker, current/average price,
// 1-day move. Mirrors FundRow but framed for equities (price instead of NAV).
export interface StockRow extends HoldingRow {
  symbol: string // exchange ticker (e.g. RELIANCE); falls back to name when empty
  price: number | null // current price the shares are valued at (latest close)
  avgCost: number | null // average cost per share = invested / units
  dayChangeAmount: number | null // 1-day INR change for this holding
  dayChangePercent: number | null // 1-day % move
}

// A fund on the MF breakdown page: a holding plus its grouping keys and XIRR.
export interface FundRow extends HoldingRow {
  amc: string
  category: string
  xirr: number | null // percent; null when not computable
  // Per-scheme secondary-line details (NAV / Avg cost-per-unit / 1-day move).
  nav: number | null // current NAV the units are valued at
  avgNav: number | null // average cost per unit = invested / units
  dayChangeAmount: number | null // 1-day INR change for this holding
  dayChangePercent: number | null // 1-day % NAV move
}

export interface DashboardSummary {
  netWorth: number
  invested: number
  totalReturnAmount: number
  totalReturnPercent: number
  dayChangeAmount: number | null // intraday INR change; null without 2 NAV points
  dayChangePercent: number | null
  xirr: number | null
  asOf: string
  // total_inr is a last-known value (statement close / last computed day), not a
  // live valuation at as_of — e.g. NAVs not fetched yet. as_of is that value's date.
  isProvisional: boolean
  // The prices backing the total are old (the feed hasn't run for >1 trading day).
  // navsAsOf is the freshest NAV date, formatted for the "NAVs as of …" subtitle.
  navsStale: boolean
  navsAsOf: string
  allocation: AllocationSlice[] // by asset class (the "All" view; MF-only for now)
  allocationByCategory: AllocationSlice[] // equity vs debt
  allocationByAmc: AllocationSlice[] // by fund house
  valueSeries: ValuePoint[]
  // Every priced holding, mapped for the asset-class summary + the asset-class page.
  holdings: HoldingRow[]
  topHoldings: HoldingRow[]
  funds: FundRow[] // priced mutual funds only, for the MF breakdown's grouped list
  // MF-only allocation for the "Mutual funds" tab (excludes stocks/other assets,
  // which we don't support yet — they stay in net worth + the All→Asset class view).
  mfByCategory: AllocationSlice[]
  mfByAmc: AllocationSlice[]
  mfTotal: number
  // Stocks tab: equity holdings + their summed value (excludes MFs/other assets).
  stocks: StockRow[]
  stockTotal: number
  holdingsCount: number // priced holdings tracked (hero KPI)
}

const EMPTY: DashboardSummary = {
  netWorth: 0,
  invested: 0,
  totalReturnAmount: 0,
  totalReturnPercent: 0,
  dayChangeAmount: null,
  dayChangePercent: null,
  xirr: null,
  asOf: '—',
  isProvisional: false,
  navsStale: false,
  navsAsOf: '',
  allocation: [],
  allocationByCategory: [],
  allocationByAmc: [],
  valueSeries: [],
  holdings: [],
  topHoldings: [],
  funds: [],
  mfByCategory: [],
  mfByAmc: [],
  mfTotal: 0,
  stocks: [],
  stockTotal: 0,
  holdingsCount: 0,
}

// Map a backend allocation breakdown into donut slices. With `cap`, keep the
// largest `cap` buckets and fold the remainder into a neutral "Others" slice so
// a long tail (many AMCs) doesn't overflow the legend.
function toSlices(
  rows: { label: string; value_inr: string }[],
  color: (label: string, index: number) => string,
  cap?: number,
  label: (raw: string) => string = (raw) => raw,
): AllocationSlice[] {
  const head = cap ? rows.slice(0, cap) : rows
  const slices = head.map<AllocationSlice>((r, i) => ({
    name: label(r.label),
    value: num(r.value_inr),
    color: color(r.label, i),
  }))
  if (cap && rows.length > cap) {
    const rest = rows.slice(cap).reduce((sum, r) => sum + num(r.value_inr), 0)
    if (rest > 0) slices.push({ name: 'Others', value: rest, color: 'var(--fm-asset-cash)' })
  }
  return slices
}

/**
 * Live per-investor dashboard data. Pulls the headline summary
 * (`GET /investors/{id}/summary`) and the net-worth series
 * (`GET /investors/{id}/value-series`); the range toggle re-fetches the series.
 * Per-holding integrity is joined from `useIntegrity`. Fails soft to zeros so the
 * shell still renders if a request errors (e.g. no backend in dev).
 */
export function useDashboard(investorId: Ref<number>) {
  const summaryData = ref<Schemas['InvestorSummaryOut'] | null>(null)
  const series = ref<Schemas['ValueSeriesPoint'][]>([])
  const transactions = ref<DashboardTransaction[]>([])
  const transactionsLoaded = ref(false)
  const range = ref<RangeKey>('1Y')
  const returnWindow = ref<ReturnWindowKey>('1D')
  const loading = ref(false)
  const refreshingPrices = ref(false)
  // Day-wise valuation readiness — gates the net-worth chart (the headline numbers
  // stay ungated, backed by the provisional value until the worker finishes).
  const valuationStatus = ref<string>('ready')
  const valuationReady = computed(() => valuationStatus.value === 'ready')
  const ui = useUiStore()
  let pollTimer: ReturnType<typeof setInterval> | null = null

  // Per-holding integrity is read from the shared integrity store, so an
  // acknowledge on the Integrity page reflects here without a refetch.
  const integrityStore = useIntegrityStore()
  const integrityBySecurity = computed(() => {
    const map = new Map<number, IntegrityStatus>()
    for (const row of integrityStore.rowsFor(investorId.value)) map.set(row.securityId, row.status)
    return map
  })
  const rollup = computed(() => integrityStore.rollupFor(investorId.value))

  async function loadSummary(): Promise<void> {
    const { data } = await api.GET('/api/investors/{investor_id}/summary', {
      params: { path: { investor_id: investorId.value } },
    })
    summaryData.value = data ?? null
  }

  // One fetch of the WHOLE trend at daily granularity. The range buttons + the
  // chart's zoom slider window it client-side, so the slider's overview always spans
  // full history and switching ranges needs no network. The chart down-samples
  // (LTTB) for render: a smoothed overview when zoomed out, finer detail on zoom in.
  async function loadSeries(): Promise<void> {
    const { data } = await api.GET('/api/investors/{investor_id}/value-series', {
      params: {
        path: { investor_id: investorId.value },
        query: { from: RANGES.All.from(), granularity: 'daily' },
      },
    })
    series.value = data?.points ?? []
  }

  async function loadTransactions(): Promise<void> {
    transactionsLoaded.value = false
    const { data } = await api.GET('/api/investors/{investor_id}/transactions', {
      params: { path: { investor_id: investorId.value } },
    })
    transactions.value = data ?? []
    transactionsLoaded.value = !!data
  }

  async function loadStatus(): Promise<void> {
    const { data } = await api.GET('/api/investors/{investor_id}/valuation-status', {
      params: { path: { investor_id: investorId.value } },
    })
    valuationStatus.value = data?.status ?? 'ready'
  }

  function stopPolling(): void {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // While valuation is computing, poll the status; when it flips to ready, reload
  // the (now precise) series + headline and toast the user.
  function startPolling(): void {
    stopPolling()
    let ticks = 0
    pollTimer = setInterval(async () => {
      ticks += 1
      await loadStatus()
      if (valuationReady.value) {
        stopPolling()
        await Promise.all([loadSummary(), loadSeries()])
        ui.notify({ severity: 'success', summary: 'Portfolio valuation ready' })
      } else if (ticks >= POLL_MAX_TICKS) {
        stopPolling()
      }
    }, POLL_MS)
  }

  async function loadAll(): Promise<void> {
    loading.value = true
    stopPolling()
    try {
      await Promise.all([
        loadSummary(),
        loadSeries(),
        loadTransactions(),
        loadStatus(),
        integrityStore.load(investorId.value),
      ])
    } finally {
      loading.value = false
    }
    if (!valuationReady.value) startPolling()
  }

  async function refreshPrices(): Promise<boolean> {
    refreshingPrices.value = true
    const wasWaiting = !valuationReady.value
    stopPolling()
    try {
      const res = await api.POST('/api/navs/refresh', {})
      if (res.error || !res.data) throw new Error('refresh failed')
      await Promise.all([loadSummary(), loadSeries(), loadStatus()])
      if (!valuationReady.value) startPolling()
      if (res.data.errors > 0) {
        ui.notify({
          severity: 'warn',
          summary: 'Price refresh finished',
          detail: `${res.data.updated} updated, ${res.data.errors} feed errors.`,
        })
      } else if (res.data.updated > 0) {
        const skipped =
          res.data.skipped > 0 ? ` ${res.data.skipped} unchanged or without a feed.` : ''
        ui.notify({
          severity: 'success',
          summary: 'Prices refreshed',
          detail: `${res.data.updated} securities updated.${skipped}`,
        })
      } else {
        ui.notify({
          severity: 'info',
          summary: 'No new prices found',
          detail:
            res.data.skipped > 0
              ? `${res.data.skipped} securities were unchanged or have no live feed.`
              : 'Your tracked prices were already current.',
        })
      }
      return true
    } catch {
      ui.notify({
        severity: 'error',
        summary: 'Refresh failed',
        detail: 'Could not fetch the latest prices right now.',
      })
      if (wasWaiting) startPolling()
      return false
    } finally {
      refreshingPrices.value = false
    }
  }

  // Range is now a client-side zoom window over the already-fetched full series —
  // no refetch. `valueWindow` (below) turns it into the chart's zoom bounds.
  function setRange(next: RangeKey): void {
    range.value = next
  }

  function setReturnWindow(next: ReturnWindowKey): void {
    returnWindow.value = next
  }

  // The [from, to] the chart should zoom to for the active preset; null = full
  // range (All), i.e. show everything with no window.
  const valueWindow = computed(() =>
    range.value === 'All'
      ? null
      : { from: RANGES[range.value].from(), to: new Date().toISOString().slice(0, 10) },
  )

  watch(investorId, () => void loadAll(), { immediate: true })
  if (getCurrentScope()) onScopeDispose(stopPolling)

  // The net-worth line; trim the leading all-zero stretch before the first holding.
  const fullValueSeries = computed<ValuePointWithIso[]>(() =>
    series.value.map((p) => ({
      date: p.date,
      current: num(p.value_inr),
      invested: num(p.invested_inr),
    })),
  )

  const valueSeries = computed<ValuePoint[]>(() => {
    const points = fullValueSeries.value
    const firstReal = points.findIndex((p) => p.current !== 0 || p.invested !== 0)
    return firstReal > 0 ? points.slice(firstReal) : points
  })

  const allTimeReturn = computed<PeriodReturn | null>(() => {
    const s = summaryData.value
    const latest = fullValueSeries.value.at(-1)
    if (!s || !latest) return null
    const invested = latest.invested
    const amount = num(s.total_inr) - invested
    return {
      amount,
      annualizedPercent: s.xirr == null ? null : s.xirr * 100,
      fromDate: fullValueSeries.value[0]?.date ?? latest.date,
      toDate: latest.date,
      direction: _direction(amount),
      isAllTime: true,
    }
  })

  const selectedReturn = computed<PeriodReturn | null>(() => {
    const latest = fullValueSeries.value.at(-1)
    if (!latest) return null
    if (returnWindow.value === 'All') return allTimeReturn.value
    if (!transactionsLoaded.value) return null

    const targetStart = _shiftReturnWindow(latest.date, returnWindow.value)
    const earliest = fullValueSeries.value[0]
    if (!earliest) return null
    if (targetStart < earliest.date) return allTimeReturn.value

    const start = [...fullValueSeries.value].reverse().find((point) => point.date <= targetStart)
    if (!start || start.date >= latest.date) return null

    const flows = _signedFlows(transactions.value, start.date, latest.date)
    const netInvested = flows.reduce((sum, flow) => sum + flow.amount, 0)
    const amount = latest.current - start.current - netInvested
    const annualizedRate = _computeXirr(
      _cashflowsFromTransactions(
        start.current > 0 ? [{ date: start.date, amount: start.current }, ...flows] : flows,
        latest.date,
        latest.current,
      ),
    )
    return {
      amount,
      annualizedPercent: annualizedRate == null ? null : annualizedRate * 100,
      fromDate: start.date,
      toDate: latest.date,
      direction: _direction(amount),
      isAllTime: false,
    }
  })

  const summary = computed<DashboardSummary>(() => {
    const s = summaryData.value
    if (!s) return { ...EMPTY, valueSeries: valueSeries.value }

    const netWorth = num(s.total_inr)
    // Invested = FIFO cost basis of held units, from the latest series point.
    const invested = valueSeries.value.at(-1)?.invested ?? 0
    const totalReturnAmount = netWorth - invested
    const totalReturnPercent = invested > 0 ? (totalReturnAmount / invested) * 100 : 0

    // Portfolio day-change: the API gives the absolute INR move; derive the
    // percent against the prior value (net worth minus today's move).
    const dayChangeAmount = s.day_change_inr == null ? null : num(s.day_change_inr)
    const priorValue = dayChangeAmount == null ? null : netWorth - dayChangeAmount
    const dayChangePercent =
      dayChangeAmount != null && priorValue ? (dayChangeAmount / priorValue) * 100 : null

    // The "Mutual funds" tab is fund-only: stocks/demat holdings (unsupported yet)
    // shouldn't sit under a fund category. Derive its list + donut from MF holdings.
    const mfHoldings = (s.holdings ?? []).filter((h) => h.security_type === 'mf')
    const mfMix = (key: (h: (typeof mfHoldings)[number]) => string | null | undefined) => {
      const m = new Map<string, number>()
      for (const h of mfHoldings) {
        if (h.value_inr == null) continue
        m.set(key(h) || 'Other', (m.get(key(h) || 'Other') ?? 0) + num(h.value_inr))
      }
      return [...m.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([label, value]) => ({ label, value_inr: String(value) }))
    }

    return {
      netWorth,
      invested,
      totalReturnAmount,
      totalReturnPercent,
      dayChangeAmount,
      dayChangePercent,
      xirr: s.xirr == null ? null : s.xirr * 100, // fraction → percent for the card
      asOf: `as of ${formatDate(s.as_of)}${s.is_provisional ? ' · provisional' : ''}`,
      isProvisional: s.is_provisional,
      navsStale: s.navs_stale ?? false,
      navsAsOf: s.navs_as_of ? formatDate(s.navs_as_of) : '',
      allocation: (s.asset_mix ?? []).map<AllocationSlice>((row) => ({
        name: assetLabel(row.security_type),
        value: num(row.value_inr),
        color: ASSET_META[row.security_type]?.color,
      })),
      allocationByCategory: toSlices(s.category_mix ?? [], categoryColor),
      // Cap fund-house slices so the donut legend stays readable; the tail rolls
      // into a neutral "Others" slice (backend already orders buckets value-desc).
      allocationByAmc: toSlices(s.amc_mix ?? [], (_label, i) => rampColor(i), 6, shortAmc),
      valueSeries: valueSeries.value,
      // Every priced holding → the asset-class summary on the dashboard and the
      // per-security list on the asset-class page. Carries cost basis for class sums.
      holdings: (s.holdings ?? []).map<HoldingRow>((h) => ({
        securityId: h.security_id,
        name: h.name,
        securityType: h.security_type,
        assetClass: assetLabel(h.security_type),
        color: assetColor(h.security_type),
        value: num(h.value_inr),
        units: num(h.units),
        invested: h.invested_inr == null ? null : num(h.invested_inr),
        gain: h.invested_inr == null ? null : num(h.value_inr) - num(h.invested_inr),
        returnPct: h.return_pct == null ? null : h.return_pct * 100,
        integrity: integrityBySecurity.value.get(h.security_id) ?? toIntegrityStatus(''),
      })),
      topHoldings: (s.top_holdings ?? []).map<HoldingRow>((h) => ({
        securityId: h.security_id,
        name: h.name,
        securityType: h.security_type,
        assetClass: assetLabel(h.security_type),
        color: assetColor(h.security_type),
        value: num(h.value_inr),
        units: num(h.units),
        invested: null,
        gain: null,
        returnPct: h.return_pct == null ? null : h.return_pct * 100,
        integrity: integrityBySecurity.value.get(h.security_id) ?? toIntegrityStatus(''),
      })),
      funds: mfHoldings.map<FundRow>((h) => ({
        securityId: h.security_id,
        name: h.name,
        securityType: h.security_type,
        assetClass: assetLabel(h.security_type),
        color: assetColor(h.security_type),
        amc: shortAmc(h.amc || 'Other'),
        category: h.category || 'Other',
        value: num(h.value_inr),
        units: num(h.units),
        invested: h.invested_inr == null ? null : num(h.invested_inr),
        returnPct: h.return_pct == null ? null : h.return_pct * 100,
        xirr: h.xirr == null ? null : h.xirr * 100,
        gain: h.invested_inr == null ? null : num(h.value_inr) - num(h.invested_inr),
        nav: h.latest_nav == null ? null : num(h.latest_nav),
        avgNav:
          h.invested_inr == null || num(h.units) === 0 ? null : num(h.invested_inr) / num(h.units),
        dayChangeAmount: h.day_change_inr == null ? null : num(h.day_change_inr),
        dayChangePercent: h.day_change_pct == null ? null : h.day_change_pct * 100,
        integrity: integrityBySecurity.value.get(h.security_id) ?? toIntegrityStatus(''),
      })),
      mfByCategory: toSlices(
        mfMix((h) => h.category),
        categoryColor,
      ),
      mfByAmc: toSlices(
        mfMix((h) => h.amc),
        (_label, i) => rampColor(i),
        6,
        shortAmc,
      ),
      mfTotal: mfHoldings.reduce((sum, h) => sum + num(h.value_inr), 0),
      stocks: (s.holdings ?? [])
        .filter((h) => h.security_type === 'equity')
        .map<StockRow>((h) => ({
          securityId: h.security_id,
          name: h.name,
          symbol: h.symbol || '',
          securityType: h.security_type,
          assetClass: assetLabel(h.security_type),
          color: assetColor(h.security_type),
          units: num(h.units),
          value: num(h.value_inr),
          invested: h.invested_inr == null ? null : num(h.invested_inr),
          price: h.latest_nav == null ? null : num(h.latest_nav),
          avgCost:
            h.invested_inr == null || num(h.units) === 0
              ? null
              : num(h.invested_inr) / num(h.units),
          returnPct: h.return_pct == null ? null : h.return_pct * 100,
          gain: h.invested_inr == null ? null : num(h.value_inr) - num(h.invested_inr),
          dayChangeAmount: h.day_change_inr == null ? null : num(h.day_change_inr),
          dayChangePercent: h.day_change_pct == null ? null : h.day_change_pct * 100,
          integrity: integrityBySecurity.value.get(h.security_id) ?? toIntegrityStatus(''),
        })),
      stockTotal: (s.holdings ?? [])
        .filter((h) => h.security_type === 'equity')
        .reduce((sum, h) => sum + num(h.value_inr), 0),
      holdingsCount: s.holdings_count ?? s.holdings?.length ?? 0,
    }
  })

  return {
    summary,
    rollup,
    loading,
    refreshingPrices,
    range,
    returnWindow,
    returnWindowOptions: RETURN_WINDOW_OPTIONS,
    selectedReturn,
    setRange,
    setReturnWindow,
    valueWindow,
    reload: loadAll,
    refreshPrices,
    valuationReady,
    valuationStatus,
  }
}

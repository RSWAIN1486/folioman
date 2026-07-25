<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import {
  deleteAgentSession,
  getAgentOverview,
  getAgentSession,
  listAgentSessions,
  renameAgentSession,
  sendAgentMessage,
  type AgentChatSessionOut,
  type AgentOverviewOut,
} from '@/api/client'
import { formatDate, formatInr, formatInrCompact, formatPercent, toNumber } from '@/utils/format'

type ModuleKey =
  | 'overview'
  | 'health'
  | 'brief'
  | 'goals'
  | 'research'
  | 'monitor'
  | 'tax'
  | 'what-if'
  | 'chat'

interface WorkspaceModule {
  key: ModuleKey
  label: string
  icon: string
  eyebrow: string
}

interface ChatMessage {
  role: 'assistant' | 'user'
  text: string
  meta?: string
}

const route = useRoute()
const router = useRouter()
const overview = ref<AgentOverviewOut | null>(null)
const loading = ref(true)
const error = ref('')
const prompt = ref('')
const sending = ref(false)
const messages = ref<ChatMessage[]>([])
const sessions = ref<AgentChatSessionOut[]>([])
const chatLoading = ref(false)
const chatError = ref('')

const goalTarget = ref(20_000_000)
const goalYears = ref(10)
const expectedReturn = ref(10)
const scenarioDrop = ref(20)

const modules: WorkspaceModule[] = [
  { key: 'overview', label: 'Overview', icon: 'pi pi-sparkles', eyebrow: 'Command centre' },
  { key: 'health', label: 'Portfolio Health', icon: 'pi pi-shield', eyebrow: 'Risk & quality' },
  { key: 'brief', label: 'Daily Brief', icon: 'pi pi-sun', eyebrow: 'Latest trading day' },
  { key: 'goals', label: 'Goals & SIP', icon: 'pi pi-flag', eyebrow: 'Funding path' },
  { key: 'research', label: 'Fund Research', icon: 'pi pi-search', eyebrow: 'Holdings review' },
  { key: 'monitor', label: 'Scheme Monitor', icon: 'pi pi-bell', eyebrow: 'Changes & alerts' },
  { key: 'tax', label: 'Tax Planner', icon: 'pi pi-calculator', eyebrow: 'Verified coverage' },
  { key: 'what-if', label: 'What-If', icon: 'pi pi-sliders-h', eyebrow: 'Scenario lab' },
  { key: 'chat', label: 'Chat', icon: 'pi pi-comments', eyebrow: 'Discuss the portfolio' },
]

const investorId = computed(() => Number(route.params.investorId))
const activeModule = computed<ModuleKey>(() => {
  const value = route.params.module
  return typeof value === 'string' && modules.some((item) => item.key === value)
    ? (value as ModuleKey)
    : 'overview'
})
const activeMeta = computed(
  () => modules.find((item) => item.key === activeModule.value) ?? modules[0]!,
)
const activeSessionId = computed(() => {
  const value = Array.isArray(route.query.session) ? route.query.session[0] : route.query.session
  const parsed = typeof value === 'string' ? Number(value) : Number.NaN
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const healthTone = computed(() => {
  const score = overview.value?.health_score ?? 0
  return score >= 85 ? 'strong' : score >= 65 ? 'watch' : 'attention'
})

const monthlySip = computed(() => {
  if (!overview.value) return 0
  const months = Math.max(1, Math.round(goalYears.value * 12))
  const monthlyRate = Math.max(0, expectedReturn.value) / 100 / 12
  const currentFutureValue =
    toNumber(overview.value.metrics.total_inr) * (1 + monthlyRate) ** months
  const gap = Math.max(0, goalTarget.value - currentFutureValue)
  if (monthlyRate === 0) return gap / months
  return gap / (((1 + monthlyRate) ** months - 1) / monthlyRate)
})

const projectedAfterDrop = computed(
  () =>
    toNumber(overview.value?.metrics.total_inr) *
    (1 - Math.min(80, Math.max(0, scenarioDrop.value)) / 100),
)

async function load(): Promise<void> {
  if (!Number.isFinite(investorId.value)) return
  loading.value = true
  error.value = ''
  try {
    overview.value = await getAgentOverview(investorId.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not load the AI workspace'
  } finally {
    loading.value = false
  }
}

function openModule(key: ModuleKey): void {
  void router.push({
    name: 'ai-workspace',
    params: { investorId: investorId.value, module: key === 'overview' ? undefined : key },
    query: key === 'chat' ? route.query : {},
  })
}

function messageMeta(message: {
  role: 'assistant' | 'user'
  provider: 'local' | 'openai' | 'openrouter'
  model?: string | null
  external_transmission: boolean
  pii_redactions: number
}): string | undefined {
  if (message.role === 'user') return undefined
  const redactions =
    message.pii_redactions > 0
      ? ` · ${message.pii_redactions} identifier${message.pii_redactions === 1 ? '' : 's'} redacted`
      : ''
  return message.external_transmission
    ? `${message.provider} · ${message.model ?? 'configured model'} · de-identified context sent externally${redactions}`
    : `Local deterministic analysis · no external transmission${redactions}`
}

async function loadChatSession(sessionId: number): Promise<void> {
  const session = await getAgentSession(investorId.value, sessionId)
  messages.value = session.messages.map((message) => ({
    role: message.role,
    text: message.content,
    meta: messageMeta(message),
  }))
}

async function loadChatWorkspace(): Promise<void> {
  if (activeModule.value !== 'chat' || !Number.isFinite(investorId.value)) return
  chatLoading.value = true
  chatError.value = ''
  try {
    sessions.value = await listAgentSessions(investorId.value)
    if (activeSessionId.value !== null) {
      await loadChatSession(activeSessionId.value)
    } else {
      messages.value = []
    }
  } catch (err) {
    chatError.value = err instanceof Error ? err.message : 'Could not load chat history'
  } finally {
    chatLoading.value = false
  }
}

async function selectSession(sessionId: number | null): Promise<void> {
  const query = { ...route.query }
  if (sessionId === null) delete query.session
  else query.session = String(sessionId)
  await router.replace({ query })
}

async function newChat(): Promise<void> {
  messages.value = []
  chatError.value = ''
  await selectSession(null)
}

async function renameSession(session: AgentChatSessionOut): Promise<void> {
  const title = window.prompt('Rename chat', session.title)?.trim()
  if (!title || title === session.title) return
  try {
    await renameAgentSession(investorId.value, session.id, title)
    sessions.value = await listAgentSessions(investorId.value)
  } catch (err) {
    chatError.value = err instanceof Error ? err.message : 'Could not rename this chat'
  }
}

async function removeSession(session: AgentChatSessionOut): Promise<void> {
  if (!window.confirm(`Delete "${session.title}" and its encrypted messages?`)) return
  try {
    await deleteAgentSession(investorId.value, session.id)
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
    if (activeSessionId.value === session.id) await newChat()
  } catch (err) {
    chatError.value = err instanceof Error ? err.message : 'Could not delete this chat'
  }
}

async function sendMessage(): Promise<void> {
  const text = prompt.value.trim()
  if (!text || sending.value) return
  messages.value.push({ role: 'user', text })
  prompt.value = ''
  sending.value = true
  try {
    const response = await sendAgentMessage(
      investorId.value,
      text,
      activeSessionId.value ?? undefined,
    )
    sessions.value = await listAgentSessions(investorId.value)
    if (activeSessionId.value === response.session_id) {
      await loadChatSession(response.session_id)
    } else {
      await selectSession(response.session_id)
    }
  } catch (err) {
    messages.value.push({
      role: 'assistant',
      text: err instanceof Error ? err.message : 'The portfolio analysis request failed.',
      meta: 'Request failed',
    })
  } finally {
    sending.value = false
  }
}

watch(investorId, () => {
  void load()
  void loadChatWorkspace()
})
watch([activeModule, () => route.query.session], () => void loadChatWorkspace())
onMounted(() => {
  void load()
  void loadChatWorkspace()
})
</script>

<template>
  <section class="agent-page">
    <header class="page-head">
      <div>
        <p class="kicker">{{ activeMeta.eyebrow }}</p>
        <h1>{{ activeMeta.label === 'Overview' ? 'AI Workspace' : activeMeta.label }}</h1>
        <p>Deterministic portfolio intelligence with an identity-free context boundary.</p>
      </div>
      <div class="privacy-seal">
        <span class="seal-icon"><i class="pi pi-lock" /></span>
        <span><strong>Private by design</strong><small>PII excluded from AI context</small></span>
      </div>
    </header>

    <nav class="module-strip" aria-label="AI workspace modules">
      <button
        v-for="item in modules"
        :key="item.key"
        type="button"
        :class="{ active: activeModule === item.key }"
        @click="openModule(item.key)"
      >
        <i :class="item.icon" />
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <div v-if="loading" class="workspace-loading">
      <span class="fm-skeleton" />
      <span class="fm-skeleton" />
      <span class="fm-skeleton wide" />
    </div>

    <article v-else-if="error" class="error-card">
      <i class="pi pi-exclamation-circle" />
      <div>
        <strong>Analysis unavailable</strong>
        <p>{{ error }}</p>
      </div>
      <Button label="Retry" icon="pi pi-refresh" size="small" @click="load" />
    </article>

    <template v-else-if="overview">
      <div class="evidence-bar">
        <span><i class="pi pi-calendar" /> Data as of {{ formatDate(overview.data_as_of) }}</span>
        <span><i class="pi pi-database" /> NAVs through {{ formatDate(overview.navs_as_of) }}</span>
        <span><i class="pi pi-shield" /> Portfolio calculations stay local</span>
      </div>

      <div v-if="activeModule === 'overview'" class="overview-grid">
        <article class="score-card" :class="healthTone">
          <div class="score-ring" :style="{ '--score': overview.health_score }">
            <span>{{ overview.health_score }}</span
            ><small>/100</small>
          </div>
          <div>
            <p class="card-label">Portfolio health</p>
            <h2>{{ overview.health_label }}</h2>
            <p>{{ overview.findings.length }} evidence-backed observations</p>
            <button type="button" class="text-action" @click="openModule('health')">
              Review findings <i class="pi pi-arrow-right" />
            </button>
          </div>
        </article>

        <article class="brief-card">
          <div class="card-title">
            <span class="title-icon sun"><i class="pi pi-sun" /></span>
            <div>
              <p class="card-label">Daily brief</p>
              <h2>What changed</h2>
            </div>
          </div>
          <ul>
            <li v-for="line in overview.daily_brief.slice(0, 3)" :key="line">{{ line }}</li>
          </ul>
          <button type="button" class="text-action" @click="openModule('brief')">
            Open full brief <i class="pi pi-arrow-right" />
          </button>
        </article>

        <article class="metric-band">
          <div>
            <span>Current value</span
            ><strong>{{ formatInrCompact(overview.metrics.total_inr) }}</strong>
          </div>
          <div>
            <span>Latest-day move</span
            ><strong>{{
              overview.metrics.day_change_inr == null
                ? '—'
                : formatInr(overview.metrics.day_change_inr)
            }}</strong>
          </div>
          <div>
            <span>Lifetime XIRR</span
            ><strong>{{
              overview.metrics.xirr == null
                ? '—'
                : formatPercent(overview.metrics.xirr * 100, false)
            }}</strong>
          </div>
          <div>
            <span>Tax-ready</span
            ><strong
              >{{ overview.metrics.tax_ready_count }}/{{
                overview.metrics.integrity_unit_count
              }}</strong
            >
          </div>
        </article>

        <article class="module-launcher">
          <button
            v-for="item in modules.filter(
              (entry) => !['overview', 'health', 'brief'].includes(entry.key),
            )"
            :key="item.key"
            type="button"
            @click="openModule(item.key)"
          >
            <span class="launch-icon"><i :class="item.icon" /></span>
            <span
              ><strong>{{ item.label }}</strong
              ><small>{{ item.eyebrow }}</small></span
            >
            <i class="pi pi-arrow-up-right" />
          </button>
        </article>
      </div>

      <div v-else-if="activeModule === 'health'" class="content-grid">
        <article class="hero-panel">
          <p class="card-label">Deterministic score</p>
          <h2>{{ overview.health_score }}/100 · {{ overview.health_label }}</h2>
          <p>
            Penalties are applied only for explicit integrity, pricing, and concentration checks.
          </p>
        </article>
        <article class="findings-panel">
          <div v-if="overview.findings.length === 0" class="empty-note">
            <i class="pi pi-check-circle" /> No configured check produced a finding.
          </div>
          <div
            v-for="finding in overview.findings"
            :key="finding.title"
            class="finding"
            :class="finding.severity"
          >
            <span class="finding-dot" />
            <div>
              <h3>{{ finding.title }}</h3>
              <p>{{ finding.detail }}</p>
            </div>
            <strong v-if="finding.metric">{{ finding.metric }}</strong>
          </div>
        </article>
        <details class="method-panel">
          <summary>Formulas and assumptions</summary>
          <ul>
            <li v-for="note in overview.formula_notes" :key="note">{{ note }}</li>
          </ul>
        </details>
      </div>

      <div v-else-if="activeModule === 'brief'" class="content-grid">
        <article class="brief-sheet">
          <div class="brief-date">{{ formatDate(overview.data_as_of) }}</div>
          <h2>Your latest portfolio brief</h2>
          <ol>
            <li v-for="line in overview.daily_brief" :key="line">{{ line }}</li>
          </ol>
          <p class="brief-foot">
            Latest-day analysis compares available trading-day prices, not calendar days.
          </p>
        </article>
      </div>

      <div v-else-if="activeModule === 'goals'" class="content-grid two-col">
        <article class="control-panel">
          <p class="card-label">Goal assumptions</p>
          <label
            >Target amount <input v-model.number="goalTarget" type="number" min="0" step="100000"
          /></label>
          <label>Years <input v-model.number="goalYears" type="number" min="1" max="50" /></label>
          <label
            >Expected annual return
            <input v-model.number="expectedReturn" type="number" min="0" max="30" step="0.5"
          /></label>
        </article>
        <article class="result-panel">
          <p class="card-label">Indicative monthly SIP</p>
          <strong>{{ formatInr(monthlySip) }}</strong>
          <p>
            Assumes the current portfolio compounds at {{ expectedReturn }}% p.a. and monthly
            contributions occur at month-end.
          </p>
          <small
            >This is a deterministic projection, not a guaranteed return or investment
            recommendation.</small
          >
        </article>
      </div>

      <div v-else-if="activeModule === 'research'" class="content-grid">
        <article class="table-panel">
          <div class="panel-head">
            <div>
              <p class="card-label">Research queue</p>
              <h2>Largest holdings first</h2>
            </div>
            <span>Portfolio data only</span>
          </div>
          <div v-for="holding in overview.top_holdings" :key="holding.label" class="holding-row">
            <div>
              <strong>{{ holding.security_name }}</strong
              ><small>{{ holding.share_pct.toFixed(2) }}% of portfolio</small>
            </div>
            <span>{{ formatInr(holding.value_inr) }}</span>
          </div>
          <p class="panel-note">
            AMC factsheets, benchmarks, expense ratios and Riskometer disclosures will plug into
            this queue without exposing investor identity.
          </p>
        </article>
      </div>

      <div v-else-if="activeModule === 'monitor'" class="content-grid">
        <article class="monitor-panel">
          <div class="monitor-status">
            <i class="pi pi-check-circle" />
            <div>
              <strong>NAV monitor active</strong
              ><span>Latest portfolio NAV date: {{ formatDate(overview.navs_as_of) }}</span>
            </div>
          </div>
          <div class="monitor-status">
            <i class="pi pi-shield" />
            <div>
              <strong>Integrity monitor active</strong
              ><span>{{ overview.findings.length }} current observations</span>
            </div>
          </div>
          <div class="monitor-status muted">
            <i class="pi pi-clock" />
            <div>
              <strong>Scheme disclosure monitor</strong
              ><span>Awaiting AMC/SEBI disclosure-source integration</span>
            </div>
          </div>
        </article>
      </div>

      <div v-else-if="activeModule === 'tax'" class="content-grid two-col">
        <article class="result-panel">
          <p class="card-label">Verified tax coverage</p>
          <strong
            >{{ overview.metrics.tax_ready_count }}/{{
              overview.metrics.integrity_unit_count
            }}</strong
          >
          <p>Only reconciled, full-history holdings are included in safe tax-lot analysis.</p>
        </article>
        <article class="hero-panel">
          <p class="card-label">Analysis-only boundary</p>
          <h2>No redemption or order actions</h2>
          <p>
            The planner will compare lots, estimated gains, holding periods and exit timing without
            placing trades.
          </p>
          <RouterLink :to="{ name: 'capital-gains', params: { investorId } }" class="text-action"
            >Open Capital Gains <i class="pi pi-arrow-right"
          /></RouterLink>
        </article>
      </div>

      <div v-else-if="activeModule === 'what-if'" class="content-grid two-col">
        <article class="control-panel">
          <p class="card-label">Market drawdown</p>
          <label class="range-label"
            ><strong>{{ scenarioDrop }}%</strong
            ><input v-model.number="scenarioDrop" type="range" min="0" max="50" step="1"
          /></label>
          <p>Applies the same shock to all current holdings. No future cashflows are included.</p>
        </article>
        <article class="result-panel loss-scenario">
          <p class="card-label">Projected portfolio value</p>
          <strong>{{ formatInrCompact(projectedAfterDrop) }}</strong>
          <p>
            Scenario change:
            {{ formatInr(projectedAfterDrop - toNumber(overview.metrics.total_inr)) }}
          </p>
          <small>Simple sensitivity test, not a forecast.</small>
        </article>
      </div>

      <div v-else-if="activeModule === 'chat'" class="chat-layout">
        <aside class="chat-sessions">
          <div class="session-head">
            <div>
              <p class="card-label">Conversations</p>
              <small>Encrypted on this server</small>
            </div>
            <Button
              icon="pi pi-plus"
              text
              rounded
              aria-label="New chat"
              title="New chat"
              @click="newChat"
            />
          </div>
          <Button
            class="new-chat-button"
            label="New chat"
            icon="pi pi-plus"
            outlined
            size="small"
            @click="newChat"
          />
          <p v-if="chatError" class="chat-error">{{ chatError }}</p>
          <div class="session-list">
            <p v-if="!chatLoading && sessions.length === 0" class="session-empty">
              Your saved chats will appear here.
            </p>
            <div
              v-for="session in sessions"
              :key="session.id"
              class="session-item"
              :class="{ active: activeSessionId === session.id }"
            >
              <button class="session-select" type="button" @click="selectSession(session.id)">
                <span>{{ session.title }}</span>
                <small>{{ new Date(session.updated_at).toLocaleDateString() }}</small>
              </button>
              <div class="session-actions">
                <button
                  type="button"
                  aria-label="Rename chat"
                  title="Rename chat"
                  @click="renameSession(session)"
                >
                  <i class="pi pi-pencil" />
                </button>
                <button
                  type="button"
                  aria-label="Delete chat"
                  title="Delete chat"
                  @click="removeSession(session)"
                >
                  <i class="pi pi-trash" />
                </button>
              </div>
            </div>
          </div>
        </aside>
        <article class="chat-panel">
          <div class="chat-head">
            <div><span class="online-dot" /><strong>Portfolio analyst</strong></div>
            <span>Server-side privacy boundary</span>
          </div>
          <div class="messages" aria-live="polite">
            <div v-if="chatLoading" class="chat-state">
              <i class="pi pi-spin pi-spinner" />
              <span>Loading encrypted chat…</span>
            </div>
            <div v-else-if="messages.length === 0" class="chat-welcome">
              <i class="pi pi-sparkles" />
              <strong>Start a portfolio conversation</strong>
              <p>
                Ask about value, latest-day change, XIRR, allocation, concentration, integrity, or
                tax readiness.
              </p>
              <small>Provider selection stays securely on the server.</small>
            </div>
            <div
              v-for="(message, index) in messages"
              :key="index"
              class="message"
              :class="message.role"
            >
              <p>{{ message.text }}</p>
              <small v-if="message.meta">{{ message.meta }}</small>
            </div>
          </div>
          <form class="composer" @submit.prevent="sendMessage">
            <textarea
              v-model="prompt"
              rows="2"
              maxlength="2000"
              placeholder="Ask about your portfolio…"
              :disabled="sending || chatLoading"
              @keydown.enter.exact.prevent="sendMessage"
              @keydown.meta.enter.prevent="sendMessage"
              @keydown.ctrl.enter.prevent="sendMessage"
            />
            <Button
              type="submit"
              icon="pi pi-arrow-up"
              rounded
              :loading="sending"
              :disabled="!prompt.trim()"
              aria-label="Send message"
            />
          </form>
          <p class="composer-note">
            <i class="pi pi-lock" /> Known investor identifiers plus common PAN, email, phone and
            account patterns are redacted before an external request. Do not paste other personal
            identifiers. Enter sends; Shift+Enter adds a new line.
          </p>
        </article>
        <aside class="chat-context">
          <p class="card-label">Allow-listed chat context</p>
          <ul>
            <li>Aggregate values and allocation</li>
            <li>Scheme names and performance metrics</li>
            <li>Data dates and integrity counts</li>
          </ul>
          <p class="card-label">Always excluded</p>
          <ul>
            <li v-for="field in overview.privacy.excluded_fields" :key="field">{{ field }}</li>
          </ul>
        </aside>
      </div>
    </template>
  </section>
</template>

<style scoped>
.agent-page {
  width: 100%;
  max-width: var(--fm-content-max);
  margin: 0 auto;
  padding: var(--fm-space-6);
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--fm-space-6);
  margin-bottom: var(--fm-space-5);
}
.kicker,
.card-label {
  margin: 0 0 0.25rem;
  color: var(--fm-text-subtle);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
h1,
h2,
h3,
p {
  margin-top: 0;
}
h1 {
  margin-bottom: 0.25rem;
  font-size: clamp(1.8rem, 3vw, 2.5rem);
  letter-spacing: -0.035em;
}
.page-head > div > p:last-child {
  margin: 0;
  color: var(--fm-text-muted);
}
.privacy-seal {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.65rem 0.85rem;
  border: 1px solid color-mix(in srgb, var(--fm-verified) 35%, var(--fm-border));
  border-radius: var(--fm-radius-md);
  background: var(--fm-verified-bg);
}
.privacy-seal span:last-child {
  display: flex;
  flex-direction: column;
}
.privacy-seal small {
  color: var(--fm-text-muted);
}
.seal-icon {
  display: grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  color: var(--fm-verified);
  background: var(--fm-surface);
}
.module-strip {
  display: flex;
  flex-direction: row;
  gap: 0.25rem;
  overflow-x: auto;
  padding: 0.3rem;
  margin-bottom: var(--fm-space-5);
  border: 1px solid var(--fm-border-subtle);
  border-radius: var(--fm-radius-md);
  background: var(--fm-surface);
  scrollbar-width: none;
}
.module-strip button {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  flex: 0 0 auto;
  padding: 0.5rem 0.65rem;
  border: 0;
  border-radius: var(--fm-radius-sm);
  color: var(--fm-text-muted);
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 0.78rem;
}
.module-strip button.active {
  color: var(--p-primary-color);
  background: color-mix(in srgb, var(--p-primary-color) 12%, transparent);
  font-weight: 600;
}
.evidence-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1.25rem;
  margin-bottom: var(--fm-space-5);
  color: var(--fm-text-muted);
  font-size: 0.75rem;
}
.evidence-bar span {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.overview-grid,
.content-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: var(--fm-space-5);
}
.score-card,
.brief-card,
.hero-panel,
.findings-panel,
.method-panel,
.brief-sheet,
.control-panel,
.result-panel,
.table-panel,
.monitor-panel,
.chat-sessions,
.chat-panel,
.chat-context {
  background: var(--fm-surface);
  border: 1px solid var(--fm-border-subtle);
  border-radius: var(--fm-radius-xl);
  box-shadow: var(--fm-shadow-sm);
}
.score-card {
  grid-column: span 5;
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: var(--fm-space-6);
  overflow: hidden;
  position: relative;
}
.score-card::after {
  content: '';
  position: absolute;
  inset: auto -3rem -4rem auto;
  width: 10rem;
  height: 10rem;
  border-radius: 50%;
  background: color-mix(in srgb, var(--fm-verified) 9%, transparent);
}
.score-ring {
  --score: 0;
  display: grid;
  place-items: center;
  flex: 0 0 7.5rem;
  width: 7.5rem;
  height: 7.5rem;
  border-radius: 50%;
  background:
    radial-gradient(circle at center, var(--fm-surface) 61%, transparent 63%),
    conic-gradient(var(--fm-verified) calc(var(--score) * 1%), var(--fm-surface-raised) 0);
}
.score-ring span {
  font-size: 2rem;
  font-weight: 700;
  line-height: 1;
}
.score-ring small {
  margin-top: -1.65rem;
  color: var(--fm-text-muted);
}
.score-card h2,
.brief-card h2 {
  margin-bottom: 0.35rem;
}
.score-card p {
  color: var(--fm-text-muted);
}
.score-card.watch .score-ring {
  background:
    radial-gradient(circle at center, var(--fm-surface) 61%, transparent 63%),
    conic-gradient(var(--fm-warn) calc(var(--score) * 1%), var(--fm-surface-raised) 0);
}
.score-card.attention .score-ring {
  background:
    radial-gradient(circle at center, var(--fm-surface) 61%, transparent 63%),
    conic-gradient(var(--fm-critical) calc(var(--score) * 1%), var(--fm-surface-raised) 0);
}
.brief-card {
  grid-column: span 7;
  padding: var(--fm-space-6);
}
.card-title {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}
.title-icon,
.launch-icon {
  display: grid;
  place-items: center;
  width: 2.35rem;
  height: 2.35rem;
  border-radius: var(--fm-radius-md);
  color: var(--p-primary-color);
  background: color-mix(in srgb, var(--p-primary-color) 12%, transparent);
}
.title-icon.sun {
  color: #b45309;
  background: #fef3c7;
}
.brief-card ul {
  padding-left: 1.15rem;
  color: var(--fm-text-muted);
}
.text-action {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 0;
  padding: 0;
  color: var(--p-primary-color);
  background: transparent;
  font: inherit;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
}
.metric-band {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border: 1px solid var(--fm-border-subtle);
  border-radius: var(--fm-radius-xl);
  background: var(--fm-surface);
  overflow: hidden;
}
.metric-band div {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  padding: 1.1rem 1.25rem;
  border-right: 1px solid var(--fm-border-subtle);
}
.metric-band div:last-child {
  border-right: 0;
}
.metric-band span {
  color: var(--fm-text-subtle);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.metric-band strong {
  font-size: 1.15rem;
}
.module-launcher {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.65rem;
}
.module-launcher button {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 0.75rem;
  padding: 0.85rem;
  text-align: left;
  border: 1px solid var(--fm-border-subtle);
  border-radius: var(--fm-radius-md);
  color: var(--fm-text);
  background: var(--fm-surface);
  cursor: pointer;
}
.module-launcher button > span:nth-child(2) {
  display: flex;
  flex-direction: column;
}
.module-launcher small {
  color: var(--fm-text-muted);
}
.module-launcher button > i {
  color: var(--fm-text-subtle);
}
.hero-panel,
.findings-panel,
.method-panel,
.brief-sheet,
.control-panel,
.result-panel,
.table-panel,
.monitor-panel {
  grid-column: 1 / -1;
  padding: var(--fm-space-6);
}
.hero-panel {
  background: linear-gradient(
    135deg,
    var(--fm-surface),
    color-mix(in srgb, var(--p-primary-color) 8%, var(--fm-surface))
  );
}
.hero-panel p,
.result-panel p,
.control-panel p {
  color: var(--fm-text-muted);
}
.finding {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.75rem;
  align-items: start;
  padding: 0.9rem 0;
  border-bottom: 1px solid var(--fm-border-subtle);
}
.finding:last-child {
  border-bottom: 0;
}
.finding h3 {
  margin-bottom: 0.2rem;
  font-size: 1rem;
}
.finding p {
  margin: 0;
  color: var(--fm-text-muted);
}
.finding-dot {
  width: 0.6rem;
  height: 0.6rem;
  margin-top: 0.35rem;
  border-radius: 50%;
  background: var(--fm-verified);
}
.finding.warning .finding-dot {
  background: var(--fm-warn);
}
.finding.critical .finding-dot {
  background: var(--fm-critical);
}
.method-panel summary {
  cursor: pointer;
  font-weight: 600;
}
.method-panel li,
.brief-sheet li {
  margin-bottom: 0.5rem;
  color: var(--fm-text-muted);
}
.brief-sheet {
  max-width: 54rem;
  background: linear-gradient(
    145deg,
    var(--fm-surface),
    color-mix(in srgb, #f59e0b 5%, var(--fm-surface))
  );
}
.brief-date {
  color: var(--fm-text-subtle);
  font-family: var(--fm-font-mono);
  font-size: 0.75rem;
}
.brief-sheet h2 {
  margin-top: 0.5rem;
}
.brief-foot,
.panel-note {
  margin: 1rem 0 0;
  padding-top: 1rem;
  border-top: 1px solid var(--fm-border-subtle);
  color: var(--fm-text-muted);
  font-size: 0.8rem;
}
.two-col > article {
  grid-column: span 6;
}
.control-panel label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-top: 0.85rem;
  color: var(--fm-text-muted);
  font-size: 0.8rem;
}
.control-panel input {
  width: 100%;
  padding: 0.65rem;
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-sm);
  color: var(--fm-text);
  background: var(--fm-ground);
  font: inherit;
}
.result-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.result-panel > strong {
  margin: 0.35rem 0 0.75rem;
  color: var(--fm-gain);
  font-size: clamp(2rem, 5vw, 3.5rem);
  letter-spacing: -0.04em;
}
.result-panel small {
  color: var(--fm-text-subtle);
}
.loss-scenario > strong {
  color: var(--fm-loss);
}
.range-label strong {
  font-size: 2.25rem;
  color: var(--fm-text);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.panel-head span {
  color: var(--fm-verified);
  font-size: 0.75rem;
}
.holding-row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.85rem 0;
  border-bottom: 1px solid var(--fm-border-subtle);
}
.holding-row div {
  display: flex;
  flex-direction: column;
}
.holding-row small {
  color: var(--fm-text-muted);
}
.monitor-status {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.9rem;
  margin-bottom: 0.65rem;
  border-radius: var(--fm-radius-md);
  background: var(--fm-verified-bg);
  color: var(--fm-verified);
}
.monitor-status div {
  display: flex;
  flex-direction: column;
}
.monitor-status span {
  color: var(--fm-text-muted);
}
.monitor-status.muted {
  background: var(--fm-surface-raised);
  color: var(--fm-text-subtle);
}
.chat-layout {
  display: grid;
  grid-template-columns: minmax(12rem, 0.55fr) minmax(0, 2fr) minmax(14rem, 0.7fr);
  gap: var(--fm-space-5);
}
.chat-sessions {
  align-self: start;
  padding: 0.8rem;
}
.session-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.65rem;
}
.session-head .card-label {
  margin-bottom: 0.1rem;
}
.session-head small,
.session-empty {
  color: var(--fm-text-subtle);
  font-size: 0.72rem;
}
.new-chat-button {
  width: 100%;
}
.session-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-top: 0.7rem;
}
.session-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  border: 1px solid transparent;
  border-radius: var(--fm-radius-md);
}
.session-item:hover,
.session-item.active {
  border-color: var(--fm-border);
  background: var(--fm-surface-raised);
}
.session-item.active {
  box-shadow: inset 3px 0 var(--p-primary-color);
}
.session-select {
  min-width: 0;
  padding: 0.65rem 0.35rem 0.65rem 0.7rem;
  border: 0;
  color: var(--fm-text);
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.session-select span,
.session-select small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-select small {
  margin-top: 0.15rem;
  color: var(--fm-text-subtle);
}
.session-actions {
  display: flex;
  padding-right: 0.3rem;
  opacity: 0;
}
.session-item:hover .session-actions,
.session-item:focus-within .session-actions,
.session-item.active .session-actions {
  opacity: 1;
}
.session-actions button {
  display: grid;
  place-items: center;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: var(--fm-text-subtle);
  background: transparent;
  cursor: pointer;
}
.session-actions button:hover {
  color: var(--fm-text);
  background: var(--fm-ground);
}
.chat-error {
  margin: 0.65rem 0 0;
  color: var(--fm-critical);
  font-size: 0.75rem;
}
.chat-panel {
  min-height: 34rem;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-head {
  display: flex;
  justify-content: space-between;
  padding: 0.9rem 1rem;
  border-bottom: 1px solid var(--fm-border-subtle);
}
.chat-head div {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.chat-head > span {
  color: var(--fm-verified);
  font-size: 0.75rem;
}
.online-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--fm-verified);
}
.messages {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
  overflow-y: auto;
}
.chat-state,
.chat-welcome {
  display: grid;
  place-items: center;
  align-content: center;
  flex: 1;
  min-height: 17rem;
  color: var(--fm-text-muted);
  text-align: center;
}
.chat-state {
  grid-template-columns: auto auto;
  gap: 0.5rem;
}
.chat-welcome > i {
  margin-bottom: 0.75rem;
  color: var(--p-primary-color);
  font-size: 1.5rem;
}
.chat-welcome strong {
  color: var(--fm-text);
}
.chat-welcome p {
  max-width: 28rem;
  margin: 0.4rem 0;
}
.message {
  max-width: 82%;
  padding: 0.75rem 0.9rem;
  border-radius: 0.9rem;
  background: var(--fm-surface-raised);
}
.message.user {
  align-self: flex-end;
  color: #fff;
  background: var(--p-primary-color);
}
.message p {
  margin: 0;
  white-space: pre-wrap;
}
.message small {
  display: block;
  margin-top: 0.4rem;
  color: var(--fm-text-subtle);
}
.message.user small {
  color: rgba(255, 255, 255, 0.75);
}
.composer {
  display: flex;
  gap: 0.6rem;
  align-items: flex-end;
  margin: 0 1rem;
  padding: 0.6rem;
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-md);
  background: var(--fm-ground);
}
.composer textarea {
  flex: 1;
  resize: none;
  border: 0;
  outline: 0;
  color: var(--fm-text);
  background: transparent;
  font: inherit;
}
.composer-note {
  margin: 0;
  padding: 0.6rem 1rem 0.9rem;
  color: var(--fm-text-subtle);
  font-size: 0.7rem;
}
.chat-context {
  padding: var(--fm-space-5);
  align-self: start;
}
.chat-context ul {
  padding-left: 1rem;
  color: var(--fm-text-muted);
  font-size: 0.8rem;
}
.workspace-loading {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--fm-space-5);
}
.workspace-loading span {
  min-height: 13rem;
}
.workspace-loading .wide {
  grid-column: 1 / -1;
  min-height: 7rem;
}
.error-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  border: 1px solid var(--fm-critical);
  border-radius: var(--fm-radius-md);
  background: var(--fm-critical-bg);
}
.error-card div {
  flex: 1;
}
.error-card p {
  margin: 0;
}
.empty-note {
  display: flex;
  gap: 0.5rem;
  color: var(--fm-verified);
}

@media (max-width: 900px) {
  .score-card,
  .brief-card {
    grid-column: 1 / -1;
  }
  .module-launcher {
    grid-template-columns: repeat(2, 1fr);
  }
  .chat-layout {
    grid-template-columns: 1fr;
  }
  .chat-sessions {
    order: 1;
  }
  .chat-panel {
    order: 2;
  }
  .chat-context {
    order: 3;
  }
  .session-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 767px) {
  .agent-page {
    padding: var(--fm-space-4);
  }
  .page-head {
    flex-direction: column;
  }
  .privacy-seal {
    width: 100%;
  }
  .metric-band {
    grid-template-columns: repeat(2, 1fr);
  }
  .metric-band div:nth-child(2) {
    border-right: 0;
  }
  .module-launcher {
    grid-template-columns: 1fr;
  }
  .two-col > article {
    grid-column: 1 / -1;
  }
  .score-card {
    flex-direction: column;
    align-items: flex-start;
  }
  .finding {
    grid-template-columns: auto 1fr;
  }
  .finding > strong {
    grid-column: 2;
  }
  .message {
    max-width: 94%;
  }
  .session-list {
    grid-template-columns: 1fr;
  }
}
</style>

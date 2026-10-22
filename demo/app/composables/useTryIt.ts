// "Try it": calls the local Python API (src/hems/demo_api.py) that runs the real systems on an entered profile.
import type { Appliance, RunResult } from '~/composables/useDemoData'

export type Housing = 'apartment' | 'house' | 'house_electric'

export interface CatalogItem {
  kind: string
  label: string
  measured: boolean
  peakKw: number
  durationMin: number
  energyKwh: number
}

/** One allowed period, "HH:MM" to "HH:MM" (or "24:00"). */
export interface PeriodInput {
  start: string
  end: string
}

export interface ApplianceInput {
  uid: number
  kind: string
  // When the cycle may run; with several periods it must start and finish inside one of them
  periods: PeriodInput[]
  powerKw?: number
  durationMin?: number
}

export interface PlanResult {
  system: string
  label: string
  starts: Record<string, number>
  costEur: number | null
  energyEur: number
  feeEur: number
  peakKw: number
  overKw: number
  feasible: boolean
  violations: string[]
  savingEur: number
  savingPct: number
  latencyS: number | null
  tokens: number
  usd: number | null
  message: string
  recommendation?: Recommendation // the comparison systems: their schedule in the agents' fixed form, no message
}

export interface BaseLoadSource { source: 'entsoe' | 'refit', label: string, day: string }

export interface ToolsResponse {
  date: string
  peakLimitKw: number
  baseLoad: BaseLoadSource
  spotEurPerKwh: number[]
  priceEurPerKwh: number[]
  baseLoadKw: number[]
  appliances: Appliance[]
  feeEurPerKw: number
  naiveCost: number
  milpCost: number
  results: PlanResult[]
  emhass: boolean
  emhassSkipped?: 'periods' | null // not run: too many combinations of periods (EMHASS takes one window each)
  emhassRuns?: number // EMHASS runs: one per combination of periods when appliances have several
}

export interface PlanRequest {
  date: string
  housing: Housing
  base_kw?: number
  peak_limit_kw: number
  fee_eur_per_kw: number
  appliances: { kind: string, periods: PeriodInput[], power_kw?: number, duration_min?: number }[]
  design?: Design
  message?: boolean // false: no household message (one model call less); default true
}

/** One event of the pipeline's live run (POST /api/plan/agent/stream, server-sent events). */
// the two agents and the two functions of the pipeline (graph nodes, see src/hems/agents/multi_agent.py)
export type AgentName = 'orchestrator' | 'profile_data' | 'scheduler' | 'verify_schedule' | 'summary'
  | 'agent' | 'explain' // the single agent in the harness: plans and fixes, then explains
  | 'retrieve_examples' // RAG: the most similar solved days, given to the acting agent as worked examples
  | 'retrieve_examples' // RAG: the most similar solved days, given to the acting agent as worked examples
/** The agent design run live: the two-agent pipeline, or one agent in the same harness. */
export type Design = 'two_agents' | 'one_agent'
export const LIVE_SYSTEMS: Record<Design, string> = { two_agents: 'multi_duo_thoughts', one_agent: 'single_harness_thoughts' }
/** The language model the live systems use (src/hems/demo_api.py LIVE_MODEL). */
export const LIVE_MODEL = 'gpt-6-luna'
export interface AgentEvent {
  type: 'start' | 'working' | 'input' | 'tool' | 'done' | 'summary_delta' | 'result' | 'error'
  agent: AgentName | null
  t: number // seconds since the run started
  name?: string // tool
  thought?: string // the agent's Thought before this tool call (explicit Thoughts, design iteration 11)
  input?: string // tool events: the call's arguments as JSON, without the Thought
  output?: string | Record<string, unknown>
  ms?: number
  turn?: number // tool events: which of the agent's model calls requested it; equal turns ran together
  tokens?: number
  errors?: string[]
  text?: string // summary_delta
  prompt?: AgentInput // input: what an agent was given
  result?: PlanResult
  recommendation?: Recommendation // with the result
  message?: string // error
}

/** An agent's input on its first model call: system prompt, message and the tools it may call. */
export interface AgentInput {
  system: string
  message: string
  tools: string[] // includes the structured answer (TaskBrief, ScheduleOutput) the agent returns through a tool
}

/** One appliance cycle of the recommendation. */
export interface ScheduleItem {
  applianceId: string
  appliance: string
  start: string // "HH:MM"
  end: string // "HH:MM", "24:00" at midnight
  period: string // allowed period it runs in, e.g. "18:00-22:00"
  energyKwh: number
  cost: number // energy cost of this cycle, in `currency`
}

/** The pipeline's recommendation in a fixed form (src/hems/demo_api.py Recommendation). Only `message` is written
 *  by the language model; `schedules` and the figures come from the verified, scored schedule. */
export interface Recommendation {
  message?: string // only when the request asks for it (message: true, the default)
  schedules: ScheduleItem[]
  cost: number // energy plus the fee above the peak limit
  currency: string // ISO code, "EUR"
  currencySymbol: string // "€"
  peakKw: number
  peakLimitKw: number
  valid: boolean
  date: string
}

/** Map an API result to the shape of the recorded results, so the existing components can show it. */
export function toRunResult(r: PlanResult): RunResult {
  return {
    system: r.system,
    label: r.label,
    model: /^(multi_|single_|oneshot)/.test(r.system) ? LIVE_MODEL : '-',
    run: 0,
    starts: r.starts,
    costEur: r.costEur,
    feasible: r.feasible,
    violations: r.violations,
    latencyS: r.latencyS,
    tokensIn: r.tokens,
    tokensOut: 0,
    usd: r.usd,
    message: r.message
  }
}

export function useTryItApi() {
  const base = useRuntimeConfig().public.apiBase as string
  // Time to wait for the API's first answer. Locally the dev proxy never answers when the API is down, so without a
  // limit the page would wait forever; the cloud API may need up to a minute to start after a quiet period.
  const answerTimeout = base ? 90_000 : 30_000
  const errorText = (e: unknown) => {
    const err = e as { data?: { detail?: unknown }, message?: string, name?: string }
    const detail = err?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(d => (d as { msg?: string }).msg ?? '').join('; ')
    const unreachable = /fetch|timeout|abort/i.test(err?.message ?? '') || err?.name === 'AbortError' || err?.name === 'TimeoutError'
    if (!unreachable) return err?.message ?? 'Request failed'
    // deployed (apiBase set): the cloud API scales to zero, so the first request after a quiet period may fail
    return base
      ? 'The live API did not answer. After a quiet period it needs up to a minute to start; please try again.'
      : 'The local API did not answer. Start it with: uv run --extra demo uvicorn hems.demo_api:app --port 8001'
  }
  return {
    catalog: () => $fetch<{ appliances: CatalogItem[], housing: Record<Housing, number>, entsoe: boolean }>(`${base}/api/catalog`, { timeout: answerTimeout }),
    tools: (body: PlanRequest) => $fetch<ToolsResponse>(`${base}/api/plan/tools`, { method: 'POST', body, timeout: answerTimeout }),
    /** The language model without tools, live (one prompt, one answer). */
    oneshot: (body: PlanRequest) => $fetch<{ result: PlanResult }>(`${base}/api/plan/oneshot`, { method: 'POST', body, timeout: 120_000 }),
    agent: (body: PlanRequest) => $fetch<{ result: PlanResult, recommendation: Recommendation }>(`${base}/api/plan/agent`, { method: 'POST', body, timeout: 180_000 }),
    /** Run the pipeline and call onEvent for each agent event as it arrives. */
    async agentStream(body: PlanRequest, onEvent: (e: AgentEvent) => void) {
      // the limit covers the wait for the first answer only; the stream itself may run longer
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), answerTimeout)
      const res = await fetch(`${base}/api/plan/agent/stream`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal
      }).finally(() => clearTimeout(timer))
      if (!res.ok || !res.body) {
        const detail = await res.json().catch(() => null) as { detail?: unknown } | null
        throw { data: detail ?? undefined, message: `Request failed (${res.status})` }
      }
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += value
        let cut
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, cut)
          buffer = buffer.slice(cut + 2)
          const data = block.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()).join('')
          if (data) onEvent(JSON.parse(data) as AgentEvent)
        }
      }
    },
    errorText
  }
}

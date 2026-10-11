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

export interface ApplianceInput {
  uid: number
  kind: string
  ready: string
  finishBy: string
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
}

export interface PlanRequest {
  date: string
  housing: Housing
  base_kw?: number
  peak_limit_kw: number
  fee_eur_per_kw: number
  appliances: { kind: string, ready: string, finish_by: string, power_kw?: number, duration_min?: number }[]
}

/** One event of the pipeline's live run (POST /api/plan/agent/stream, server-sent events). */
export type AgentName = 'orchestrator' | 'profiler' | 'scheduler' | 'resolver' | 'summary'
export interface AgentEvent {
  type: 'start' | 'working' | 'tool' | 'done' | 'summary_delta' | 'result' | 'error'
  agent: AgentName | null
  t: number // seconds since the run started
  name?: string // tool
  input?: string
  output?: string | Record<string, unknown>
  ms?: number
  tokens?: number
  errors?: string[]
  text?: string // summary_delta
  result?: PlanResult
  message?: string // error
}

/** Map an API result to the shape of the recorded results, so the existing components can show it. */
export function toRunResult(r: PlanResult): RunResult {
  return {
    system: r.system,
    label: r.label,
    model: r.system === 'multi_lean' ? 'gpt-4o-mini' : '-',
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
  const errorText = (e: unknown) => {
    const err = e as { data?: { detail?: unknown }, message?: string }
    const detail = err?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(d => (d as { msg?: string }).msg ?? '').join('; ')
    return err?.message?.includes('fetch')
      ? 'The local API is not running. Start it with: uv run --extra demo uvicorn hems.demo_api:app --port 8001'
      : err?.message ?? 'Request failed'
  }
  return {
    catalog: () => $fetch<{ appliances: CatalogItem[], housing: Record<Housing, number>, entsoe: boolean }>(`${base}/api/catalog`),
    tools: (body: PlanRequest) => $fetch<ToolsResponse>(`${base}/api/plan/tools`, { method: 'POST', body }),
    agent: (body: PlanRequest) => $fetch<{ result: PlanResult }>(`${base}/api/plan/agent`, { method: 'POST', body, timeout: 180_000 }),
    /** Run the pipeline and call onEvent for each agent event as it arrives. */
    async agentStream(body: PlanRequest, onEvent: (e: AgentEvent) => void) {
      const res = await fetch(`${base}/api/plan/agent/stream`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body)
      })
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

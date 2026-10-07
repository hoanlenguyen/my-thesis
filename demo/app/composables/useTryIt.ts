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

/** Map an API result to the shape of the recorded results, so the existing components can show it. */
export function toRunResult(r: PlanResult): RunResult {
  return {
    system: r.system,
    label: r.label,
    model: r.system === 'multi_rag_opt' ? 'gpt-4o-mini' : '-',
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
    errorText
  }
}

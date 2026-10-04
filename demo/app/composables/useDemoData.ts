// Types and loaders for the static data exported by tools/export_demo_data.py.

export interface SystemSummary {
  system: string
  label: string
  model: string
  runs: number
  feasible: number
  gapMean: number | null
  savingsCaptured: number | null
  latencyMean: number | null
  usdPerRun: number | null
  tokensIn: number | null
}

export interface ScenarioIndex {
  id: string
  type: string
  date: string
  appliances: number
  naiveCost: number
  milpCost: number
  achievableSaving: number
}

export interface Benchmark {
  id: string
  label: string
  summary: SystemSummary[]
  scenarios: ScenarioIndex[]
}

export interface Appliance {
  id: string
  kind: string
  profileKw: number[]
  earliest: number
  deadline: number
  energyKwh: number
}

export interface RunResult {
  system: string
  label: string
  model: string
  run: number
  starts: Record<string, number>
  costEur: number | null
  feasible: boolean
  violations: string[]
  latencyS: number | null
  tokensIn: number
  tokensOut: number
  usd: number | null
  message: string
}

export interface DayDetail {
  id: string
  type: string
  date: string
  peakLimitKw: number
  priceCents: number[]
  spotCents: number[]
  baseLoadKw: number[]
  appliances: Appliance[]
  plan: string
  naiveCost: number
  milpCost: number
  results: RunResult[]
}

export function useBenchmarks() {
  return useFetch<Benchmark[]>('/data/benchmarks.json', { key: 'benchmarks' })
}

export function useDay(benchmark: MaybeRefOrGetter<string>, id: MaybeRefOrGetter<string>) {
  return useFetch<DayDetail>(() => `/data/${toValue(benchmark)}/${toValue(id)}.json`, {
    key: () => `day-${toValue(benchmark)}-${toValue(id)}`
  })
}

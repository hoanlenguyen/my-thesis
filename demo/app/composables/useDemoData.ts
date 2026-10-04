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
  house: number | null
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

export interface FixedAppliance {
  id: string
  kind: string
  ratedKw: number
}

/** Typical use of one appliance from the REFIT recordings (tools/export_household_profiles.py). */
export interface ApplianceProfile {
  name: string
  kind: string
  shiftable: boolean
  scheduled: boolean
  ratedKw: number
  kwhPerDay: number
  daysUsedShare: number
  hourly: number[] // share of recorded days with use in each hour 0-23
}

/** A non-shiftable appliance row of the day timeline: rated power plus its typical use, if profiled. */
export interface FixedRow {
  id: string
  kind: string
  ratedKw: number
  hourly: number[] | null
  shiftable: boolean // marked "partly shiftable" by the viewer (display only)
}

/** A row showing when the household usually runs one of the appliances being scheduled. */
export interface UsualRow {
  name: string
  kind: string
  hourly: number[]
}

export interface Household {
  house: number
  firstDay: string
  lastDay: string
  days: number
  appliances: ApplianceProfile[]
}

export interface DayDetail {
  id: string
  type: string
  date: string
  peakLimitKw: number
  house: number | null
  fixedAppliances: FixedAppliance[]
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

export function useHouseholds() {
  return useFetch<Household[]>('/data/households.json', { key: 'households' })
}

export function useDay(benchmark: MaybeRefOrGetter<string>, id: MaybeRefOrGetter<string>) {
  return useFetch<DayDetail>(() => `/data/${toValue(benchmark)}/${toValue(id)}.json`, {
    key: () => `day-${toValue(benchmark)}-${toValue(id)}`
  })
}

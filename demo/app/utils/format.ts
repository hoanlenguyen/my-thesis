// Formatting helpers and display metadata shared by pages and components.

export const SLOTS = 96

/** Slot index (15 min each, from 00:00) -> "HH:MM". */
export function slotTime(slot: number): string {
  const minutes = slot * 15
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

export const euro = (v: number | null | undefined, digits = 2) =>
  v == null ? '–' : `€${v.toFixed(digits)}`

export const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? '–' : `${v.toFixed(digits)} %`

// Icons as in Low-carbon-alerts RecommendationCard, extended to the REFIT appliance kinds.
export const APPLIANCE_ICONS: Record<string, string> = {
  dishwasher: 'i-lucide-utensils-crossed',
  washing_machine: 'i-lucide-washing-machine',
  tumble_dryer: 'i-lucide-shirt',
  washer_dryer: 'i-lucide-washing-machine',
  fridge: 'i-lucide-refrigerator',
  freezer: 'i-lucide-snowflake',
  chest_freezer: 'i-lucide-snowflake',
  fridge_freezer: 'i-lucide-refrigerator',
  television: 'i-lucide-tv',
  computer: 'i-lucide-monitor',
  microwave: 'i-lucide-microwave',
  kettle: 'i-lucide-coffee',
  toaster: 'i-lucide-sandwich',
  electric_heater: 'i-lucide-heater',
  hifi: 'i-lucide-speaker',
  overhead_fan: 'i-lucide-fan',
  router: 'i-lucide-router',
  network_site: 'i-lucide-router',
  dehumidifier: 'i-lucide-droplets',
  games_console: 'i-lucide-gamepad-2',
  // constant-power loads of the Low-carbon-alerts catalog (Try it view)
  ev_charger: 'i-lucide-battery-charging',
  sauna: 'i-lucide-flame',
  hot_tub: 'i-lucide-bath',
  electric_oven: 'i-lucide-cooking-pot'
}

export const APPLIANCE_LABELS: Record<string, string> = {
  dishwasher: 'Dishwasher',
  washing_machine: 'Washing machine',
  tumble_dryer: 'Tumble dryer',
  washer_dryer: 'Washer-dryer',
  fridge_freezer: 'Fridge-freezer',
  hifi: 'Hi-fi',
  television: 'Television',
  ev_charger: 'EV charger',
  hot_tub: 'Hot tub',
  electric_oven: 'Electric oven'
}

const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

/** Readable name for an appliance id or REFIT name such as "tumble_dryer_2". */
export function applianceName(id: string, kind: string): string {
  const n = id.match(/_(\d+)$/)?.[1]
  return `${APPLIANCE_LABELS[kind] ?? titleCase(kind)}${n && n !== '1' ? ` ${n}` : ''}`
}

export const applianceIcon = (kind: string) => APPLIANCE_ICONS[kind] ?? 'i-lucide-plug'

// Shiftable in principle but not scheduled in the benchmark (display only; the recorded results treat
// them as part of the base load).
export const DISPLAY_SHIFTABLE = new Set(['computer', 'television', 'washer_dryer'])

export function applianceRole(a: { kind: string, scheduled?: boolean }, partlyShiftable = DISPLAY_SHIFTABLE.has(a.kind)) {
  if (a.scheduled) return { label: 'Scheduled', color: 'primary' as const }
  if (partlyShiftable) return { label: 'Partly shiftable, not scheduled', color: 'warning' as const }
  return { label: 'Not shiftable', color: 'neutral' as const }
}

/** Consumer price c/kWh from spot EUR/MWh, with the thesis tariff (src/hems/data/tariff.py). */
export function consumerCents(spotEurMwh: number): number {
  return (spotEurMwh / 10 + 0.5 + 5.0 + 2.253) * 1.255
}

/** Mean of each block of four 15-minute values, giving 24 hourly values. */
export function hourly(values: number[]): number[] {
  return Array.from({ length: 24 }, (_, h) => {
    const block = values.slice(h * 4, h * 4 + 4)
    return block.reduce((a, b) => a + b, 0) / Math.max(1, block.length)
  })
}

// One colour per appliance position (timeline blocks, legend).
export const APPLIANCE_COLORS = ['#00C16A', '#3B82F6', '#F59E0B', '#A855F7', '#EF4444', '#14B8A6']

export const SCENARIO_TYPES: Record<string, string> = {
  A: 'Stable prices, 2 appliances',
  B: 'Stable prices, 3 appliances',
  C: 'Moderate volatility',
  D: 'High volatility, winter',
  E: 'Price spike (Dec 2022 crisis)',
  F: 'Negative spot prices'
}

export const SYSTEM_GROUPS: Record<string, 'agent' | 'llm' | 'rule' | 'heuristic' | 'tool' | 'reference'> = {
  multi: 'agent',
  multi_v3: 'agent',
  multi_rag_opt: 'agent',
  multi_lean: 'agent',
  cheapest_window: 'rule',
  single: 'agent',
  oneshot: 'llm',
  timer: 'heuristic',
  cheapest_hours: 'rule',
  emhass_rest: 'tool',
  emhass_rest_nominal: 'tool',
  milp: 'reference',
  naive: 'reference'
}

export const GROUP_BADGE: Record<string, { label: string, color: 'primary' | 'warning' | 'neutral' | 'info' | 'error' }> = {
  agent: { label: 'LLM agent', color: 'primary' },
  llm: { label: 'LLM, no tools', color: 'error' },
  rule: { label: 'Rule-based', color: 'warning' },
  heuristic: { label: 'Own heuristic', color: 'neutral' },
  tool: { label: 'Real HEMS tool', color: 'info' },
  reference: { label: 'Reference', color: 'neutral' }
}

export function groupBadge(system: string) {
  return GROUP_BADGE[SYSTEM_GROUPS[system] ?? 'reference'] ?? { label: 'Reference', color: 'neutral' as const }
}

export const MODEL_LABELS: Record<string, string> = {
  '-': '',
  'gpt-4o-mini': 'GPT-4o-mini',
  'gpt-oss-20b': 'gpt-oss-20b (local)'
}

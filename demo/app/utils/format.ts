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

// Icons as in Low-carbon-alerts RecommendationCard.
export const APPLIANCE_ICONS: Record<string, string> = {
  dishwasher: 'i-lucide-utensils-crossed',
  washing_machine: 'i-lucide-washing-machine',
  tumble_dryer: 'i-lucide-shirt'
}

export const APPLIANCE_LABELS: Record<string, string> = {
  dishwasher: 'Dishwasher',
  washing_machine: 'Washing machine',
  tumble_dryer: 'Tumble dryer'
}

/** Readable name for an appliance id such as "tumble_dryer_2". */
export function applianceName(id: string, kind: string): string {
  const n = id.match(/_(\d+)$/)?.[1]
  return `${APPLIANCE_LABELS[kind] ?? kind}${n && n !== '1' ? ` ${n}` : ''}`
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

export const SYSTEM_GROUPS: Record<string, 'agent' | 'llm' | 'rule' | 'tool' | 'reference'> = {
  multi: 'agent',
  single: 'agent',
  oneshot: 'llm',
  timer: 'rule',
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

<script setup lang="ts">
// "Try it": enter a household's appliances, active hours and a day (default today); the local API fetches the
// real day-ahead prices (ENTSO-E), builds the base load from the typical REFIT household shape, and runs the
// Multi-Agent Pipeline live next to the existing home energy management tools. Exceeding the peak limit is
// allowed but pays a fee per kW.
import type { AgentEvent, ApplianceInput, CatalogItem, Housing, PeriodInput, PlanRequest, PlanResult, Recommendation, ToolsResponse } from '~/composables/useTryIt'
import { toRunResult, useTryItApi } from '~/composables/useTryIt'

const api = useTryItApi()
const catalog = ref<CatalogItem[]>([])
const apiError = ref('')

const today = new Date()
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const day = ref(iso(today))
const housing = ref<Housing>('house')
const baseKw = ref<number | undefined>(undefined)
const peakLimit = ref(8)
const fee = ref(1.97) // EUR per kW of the day's highest load above the limit
// Active hours: one or more periods, e.g. 06:00-09:00 and 18:00-22:00; "Apply to all" copies them to every appliance
const activePeriods = ref<PeriodInput[]>([{ start: '08:00', end: '10:00' }, { start: '18:00', end: '22:00' }])
const copyPeriods = (ps: PeriodInput[]) => ps.map(p => ({ ...p }))
const MAX_PERIODS = 4

let uid = 0
const appliances = ref<ApplianceInput[]>([
  { uid: ++uid, kind: 'washing_machine', periods: copyPeriods(activePeriods.value) },
  { uid: ++uid, kind: 'dishwasher', periods: copyPeriods(activePeriods.value) },
  { uid: ++uid, kind: 'tumble_dryer', periods: copyPeriods(activePeriods.value) }
])

/** Minutes since midnight; "24:00" (or "00:00" as an end) is the end of the day. */
const minutes = (clock: string, end = false) => {
  const [h, m] = clock.split(':').map(Number)
  const v = (h ?? 0) * 60 + (m ?? 0)
  return end && v === 0 ? 1440 : v
}
/** Problems with a list of periods for a cycle of the given length, shown under the row. */
function periodProblems(ps: PeriodInput[], durationMin?: number): string[] {
  const out: string[] = []
  for (const p of ps) {
    const len = minutes(p.end, true) - minutes(p.start)
    if (!p.start || !p.end) out.push('Every period needs a start and an end.')
    else if (len <= 0) out.push(`${p.start}–${p.end} ends before it starts.`)
    else if (durationMin && len < durationMin) out.push(`${p.start}–${p.end} is shorter than the ${durationMin}-minute cycle.`)
  }
  const sorted = [...ps].sort((a, b) => minutes(a.start) - minutes(b.start))
  if (sorted.some((p, i) => i > 0 && minutes(p.start) < minutes(sorted[i - 1]!.end, true)))
    out.push('Overlapping periods will be merged.')
  return out
}
const blocking = (msg: string) => !msg.startsWith('Overlapping')
const hasBlockingProblem = computed(() =>
  appliances.value.some(a => periodProblems(a.periods, a.durationMin).some(blocking)))

onMounted(async () => {
  try {
    const c = await api.catalog()
    catalog.value = c.appliances
    for (const a of appliances.value) setDefaults(a)
  } catch (e) {
    apiError.value = api.errorText(e)
  }
})

const housingItems = [
  { label: 'Apartment', value: 'apartment' },
  { label: 'House, no electric heating', value: 'house' },
  { label: 'House with electric heating', value: 'house_electric' }
]
const limitItems = [
  { label: '3.5 kW (strict)', value: 3.5 },
  { label: '8 kW (power-tariff threshold)', value: 8 },
  { label: '11 kW', value: 11 },
  { label: '17 kW (3 × 25 A main fuse)', value: 17 }
]
const kindItems = computed(() => catalog.value.map(c => ({ label: c.label, value: c.kind })))
const item = (kind: string) => catalog.value.find(c => c.kind === kind)

/** Runtime and peak power start at the appliance's catalog values (the measured REFIT cycle for the three measured kinds). */
const defaultPower = (kind: string) => {
  const c = item(kind)
  return c ? Math.round(c.peakKw * 10) / 10 : undefined
}
function setDefaults(a: ApplianceInput) {
  a.durationMin = item(a.kind)?.durationMin
  a.powerKw = defaultPower(a.kind)
}
function changeKind(a: ApplianceInput, kind: string) {
  a.kind = kind
  setDefaults(a)
}
/** Energy of one cycle: the catalog energy scaled by the runtime and power the household entered. */
function energyKwh(a: ApplianceInput) {
  const c = item(a.kind)
  const power = defaultPower(a.kind)
  if (!c || !power || !a.durationMin || !a.powerKw) return undefined
  return c.energyKwh * (a.durationMin / c.durationMin) * (a.powerKw / power)
}
function isDefault(a: ApplianceInput) {
  return !!item(a.kind) && a.durationMin === item(a.kind)?.durationMin && a.powerKw === defaultPower(a.kind)
}
function addAppliance(kind: string) {
  const a: ApplianceInput = { uid: ++uid, kind, periods: copyPeriods(activePeriods.value) }
  setDefaults(a)
  appliances.value.push(a)
}
function applyActiveHours() {
  for (const a of appliances.value) a.periods = copyPeriods(activePeriods.value)
}
/** A new period after the last one: two hours, starting where the last one ends (capped at midnight). */
function addPeriod(ps: PeriodInput[]) {
  const last = ps[ps.length - 1]
  const start = Math.min(last ? minutes(last.end, true) + 60 : 18 * 60, 22 * 60)
  // a time input cannot show 24:00: midnight as an end is 00:00 here and sent as 24:00
  const clock = (v: number) => v >= 1440 ? '00:00' : `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`
  ps.push({ start: clock(start), end: clock(Math.min(start + 120, 1440)) })
}
const addMenu = computed(() => [catalog.value.map(c => ({ label: c.label, icon: applianceIcon(c.kind), onSelect: () => addAppliance(c.kind) }))])

// ── run ──
const tools = ref<ToolsResponse | null>(null)
const agent = ref<PlanResult | null>(null)
const loadingTools = ref(false)
const loadingAgent = ref(false)
const runError = ref('')
const agentError = ref('')
const agentEvents = ref<AgentEvent[]>([]) // the pipeline's live run, agent by agent
const summaryText = ref('') // the Orchestrator's summary as it is written
const recommendation = ref<Recommendation | null>(null) // the pipeline's answer in its fixed JSON form
const recommendationJson = computed(() => (recommendation.value ? JSON.stringify(recommendation.value, null, 2) : ''))
const copied = ref(false)
async function copyRecommendation() {
  try {
    await navigator.clipboard.writeText(recommendationJson.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch { /* clipboard not available: the JSON can still be selected */ }
}

function request(): PlanRequest {
  return {
    date: day.value,
    housing: housing.value,
    base_kw: baseKw.value || undefined,
    peak_limit_kw: peakLimit.value,
    fee_eur_per_kw: fee.value ?? 0,
    appliances: appliances.value.map(a => ({
      kind: a.kind,
      periods: a.periods.map(p => ({ start: p.start, end: p.end === '00:00' ? '24:00' : p.end })),
      // unchanged defaults are left out, so a measured appliance keeps its exact REFIT cycle
      power_kw: a.powerKw === defaultPower(a.kind) ? undefined : a.powerKw,
      duration_min: a.durationMin === item(a.kind)?.durationMin ? undefined : a.durationMin
    }))
  }
}

async function run() {
  runError.value = ''
  agentError.value = ''
  tools.value = null
  agent.value = null
  recommendation.value = null
  agentEvents.value = []
  summaryText.value = ''
  loadingTools.value = true
  loadingAgent.value = true
  const body = request()
  // The comparison systems and the pipeline start together, so the agents do not wait for prices and EMHASS.
  const comparison = api.tools(body)
    .then((r) => { tools.value = r })
    .catch((e) => { runError.value = api.errorText(e) })
    .finally(() => { loadingTools.value = false })
  const pipeline = api.agentStream(body, (e) => {
    agentEvents.value.push(e)
    if (e.type === 'summary_delta') summaryText.value += e.text ?? ''
    else if (e.type === 'result' && e.result) {
      agent.value = e.result
      recommendation.value = e.recommendation ?? null
    }
    else if (e.type === 'error') agentError.value = e.message ?? 'The pipeline stopped with an error.'
  })
    .then(() => {
      if (!agent.value && !agentError.value) agentError.value = 'The pipeline ended without a schedule.'
    })
    .catch((e) => { agentError.value = api.errorText(e) })
    .finally(() => { loadingAgent.value = false })
  await Promise.all([comparison, pipeline])
}

// ── results ──
// The systems compared on the page. The optimum (MILP with the fee) is not one of them: its cost only sets the
// "% of the possible saving" in the timeline (tools.milpCost).
const ORDER = ['multi_duo_thoughts', 'emhass_rest', 'timer', 'cheapest_window', 'cheapest_hours', 'naive']
const allResults = computed<PlanResult[]>(() => {
  const rs = [...(tools.value?.results ?? []), ...(agent.value ? [agent.value] : [])].filter(r => r.system !== 'milp')
  return rs.sort((a, b) => ORDER.indexOf(a.system) - ORDER.indexOf(b.system))
})
const runResults = computed(() => allResults.value.map(toRunResult))
const selected = ref('multi_duo_thoughts|gpt-4o-mini')
const current = computed(() => runResults.value.find(r => `${r.system}|${r.model}` === selected.value) ?? runResults.value[0])
const pipelineRun = computed(() => runResults.value.find(r => r.system === 'multi_duo_thoughts'))
const priceCents = computed(() => (tools.value?.priceEurPerKwh ?? []).map(p => p * 100))
const hourlyPrices = computed(() => hourly(priceCents.value))
const priceSpread = computed(() => (hourlyPrices.value.length ? Math.max(...hourlyPrices.value) - Math.min(...hourlyPrices.value) : 0))
const comparison = allResults
</script>

<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-2xl font-semibold text-highlighted">Try it: your appliances, a real day</h1>
      <p class="mt-1 max-w-3xl text-sm text-muted">
        Enter the appliances you want to run and when they may run. The demo fetches that day's Finnish day-ahead
        prices from ENTSO-E, adds a typical household base load, and asks the Multi-Agent Pipeline for a
        recommendation. It is compared with the home energy management tools households can install. Going over the
        peak limit is allowed but costs a fee per kW, as under a power-based tariff. The pipeline runs live with
        GPT-4o-mini (usually under 10 seconds).
      </p>
      <p class="mt-1 max-w-3xl text-xs text-dimmed">
        The pipeline has two language model agents, the Orchestrator agent and the Scheduler agent. Reading the
        household data (profile_data) and checking the schedule (verify_schedule) are functions without a language
        model. Before every action, the Scheduler agent writes a Thought; the page shows it with the function it
        called and the result. The other pages replay the recorded evaluation runs.
      </p>
    </div>

    <UAlert v-if="apiError" color="warning" variant="subtle" icon="i-lucide-plug-zap" title="Local API not reachable" :description="apiError" />

    <!-- profile -->
    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-house" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">Household and day</span>
        </div>
      </template>
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <UFormField label="Day" help="Default today; tomorrow's prices appear around 15:00 Finnish time">
          <UInput v-model="day" type="date" class="w-full" />
        </UFormField>
        <UFormField label="Home" help="Sets the default base load">
          <USelect v-model="housing" :items="housingItems" class="w-full" />
        </UFormField>
        <UFormField label="Average base load, kW" help="Everything except the appliances below">
          <UInputNumber v-model="baseKw" :step-snapping="false" :min="0.05" :max="5" :step="0.05" placeholder="default" class="w-full" />
        </UFormField>
        <UFormField label="Peak limit" help="Above it, each kW of the day's peak pays the fee">
          <USelect v-model="peakLimit" :items="limitItems" class="w-full" />
        </UFormField>
        <UFormField label="Fee above the limit, €/kW" help="Default: Helen's power charge, €1.57/kW + VAT">
          <UInputNumber v-model="fee" :step-snapping="false" :min="0" :max="50" :step="0.1" :format-options="{ minimumFractionDigits: 2 }" class="w-full" />
        </UFormField>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <UIcon name="i-lucide-plug" class="size-4 text-primary" />
            <span class="font-semibold text-sm text-highlighted">Appliances to run</span>
          </div>
          <div class="flex flex-wrap items-center gap-2 text-xs text-muted">
            Active hours
            <template v-for="(p, j) in activePeriods" :key="j">
              <span v-if="j > 0" class="text-dimmed">and</span>
              <span class="flex items-center gap-1">
                <UInput v-model="p.start" type="time" size="xs" class="w-24" :aria-label="`Active period ${j + 1} start`" />
                –
                <UInput v-model="p.end" type="time" size="xs" class="w-24" :aria-label="`Active period ${j + 1} end`" />
                <UButton
                  v-if="activePeriods.length > 1"
                  icon="i-lucide-x"
                  size="xs"
                  variant="ghost"
                  color="neutral"
                  :aria-label="`Remove active period ${j + 1}`"
                  @click="activePeriods.splice(j, 1)" />
              </span>
            </template>
            <UButton v-if="activePeriods.length < MAX_PERIODS" size="xs" variant="ghost" icon="i-lucide-plus" @click="addPeriod(activePeriods)">
              Period
            </UButton>
            <UButton size="xs" variant="soft" color="neutral" @click="applyActiveHours">Apply to all</UButton>
          </div>
        </div>
      </template>
      <div class="space-y-2">
        <div v-for="a in appliances" :key="a.uid" class="space-y-1">
          <div class="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-[13rem_auto_7rem_7rem_auto] sm:justify-start items-start">
            <UFormField label="Appliance" class="col-span-2 sm:col-span-1">
              <USelect :model-value="a.kind" :items="kindItems" class="w-full" :icon="applianceIcon(a.kind)" @update:model-value="(k: string) => changeKind(a, k)" />
            </UFormField>
            <UFormField
              label="May run"
              class="col-span-2 sm:col-span-1"
              :help="a.periods.length > 1 ? 'Starts and finishes inside one period' : undefined">
              <div class="space-y-1">
                <div v-for="(p, j) in a.periods" :key="j" class="flex items-center gap-1">
                  <UInput v-model="p.start" type="time" class="w-32" :aria-label="`Period ${j + 1} start`" />
                  <span class="text-muted">–</span>
                  <UInput v-model="p.end" type="time" class="w-32" :aria-label="`Period ${j + 1} end`" />
                  <UButton
                    v-if="a.periods.length > 1"
                    icon="i-lucide-x"
                    size="xs"
                    variant="ghost"
                    color="neutral"
                    :aria-label="`Remove period ${j + 1}`"
                    @click="a.periods.splice(j, 1)" />
                  <UButton
                    v-else-if="a.periods.length < MAX_PERIODS"
                    icon="i-lucide-plus"
                    size="xs"
                    variant="ghost"
                    aria-label="Add a period"
                    @click="addPeriod(a.periods)" />
                </div>
                <UButton
                  v-if="a.periods.length > 1 && a.periods.length < MAX_PERIODS"
                  icon="i-lucide-plus"
                  size="xs"
                  variant="link"
                  class="p-0"
                  @click="addPeriod(a.periods)">
                  Period
                </UButton>
              </div>
            </UFormField>
            <UFormField label="Runtime, min">
              <UInputNumber v-model="a.durationMin" :step-snapping="false" :min="15" :max="1440" :step="15" class="w-full" />
            </UFormField>
            <UFormField label="Power, kW">
              <UInputNumber v-model="a.powerKw" :step-snapping="false" :min="0.1" :max="50" :step="0.1" :format-options="{ maximumFractionDigits: 1 }" class="w-full" />
            </UFormField>
            <UButton icon="i-lucide-trash-2" color="neutral" variant="ghost" size="sm" class="sm:mt-6" aria-label="Remove appliance" @click="appliances = appliances.filter(x => x.uid !== a.uid)" />
          </div>
          <p v-for="msg in periodProblems(a.periods, a.durationMin)" :key="msg" class="text-xs" :class="blocking(msg) ? 'text-error' : 'text-muted'">
            {{ msg }}
          </p>
          <div v-if="item(a.kind)" class="flex flex-wrap items-center gap-x-2 text-xs text-muted">
            <span v-if="item(a.kind)?.measured">
              Measured REFIT cycle{{ isDefault(a) ? '' : ', stretched to this runtime and scaled to this peak power' }}
            </span>
            <span v-else>Constant power for the whole runtime</span>
            <span v-if="energyKwh(a) !== undefined">· about {{ energyKwh(a)!.toFixed(2) }} kWh per cycle</span>
            <UButton v-if="!isDefault(a)" size="xs" variant="link" color="neutral" class="p-0" @click="setDefaults(a)">
              Reset to {{ item(a.kind)?.durationMin }} min, {{ defaultPower(a.kind)?.toFixed(1) }} kW
            </UButton>
          </div>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 pt-2">
          <UDropdownMenu :items="addMenu">
            <UButton icon="i-lucide-plus" variant="soft" size="sm">Add appliance</UButton>
          </UDropdownMenu>
          <UButton icon="i-lucide-sparkles" :loading="loadingTools || loadingAgent" :disabled="!appliances.length || !!apiError || hasBlockingProblem" @click="run">
            Get recommendations
          </UButton>
        </div>
        <p class="text-xs text-dimmed">
          Default runtimes and powers follow the Low-carbon-alerts appliance catalog; washing machine,
          dishwasher and tumble dryer use real cycles measured in the REFIT homes, whose power is the cycle's peak.
          Change them to match your own appliances.
        </p>
      </div>
    </UCard>

    <UAlert v-if="runError" color="error" variant="subtle" icon="i-lucide-triangle-alert" title="Could not plan this day" :description="runError" />

    <!-- the pipeline's recommendation, then how its agents got there (live while it runs) -->
    <UAlert v-if="!loadingAgent && agentError && !runError" color="error" variant="subtle" icon="i-lucide-bot-off" title="The Multi-Agent Pipeline did not answer" :description="agentError" />
    <SystemRecommendationCard
      v-else-if="tools && !loadingAgent && pipelineRun"
      :result="pipelineRun"
      :appliances="tools.appliances"
      :naive-cost="tools.naiveCost"
      :milp-cost="tools.milpCost" />
    <AgentActivity
      v-if="!runError && (agentEvents.length || loadingAgent)"
      :events="agentEvents"
      :running="loadingAgent"
      :summary="summaryText"
      :result="agent" />
    <UCard v-if="recommendation && !runError" :ui="{ body: 'p-0 sm:p-0' }">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <UIcon name="i-lucide-braces" class="size-4 text-primary" />
            <span class="font-semibold text-sm text-highlighted">Recommendation as JSON</span>
            <span class="text-xs text-dimmed">· what an app would receive from POST /api/plan/agent</span>
          </div>
          <UButton
            size="xs"
            variant="soft"
            color="neutral"
            :icon="copied ? 'i-lucide-check' : 'i-lucide-copy'"
            @click="copyRecommendation">
            {{ copied ? 'Copied' : 'Copy' }}
          </UButton>
        </div>
      </template>
      <pre class="max-h-96 overflow-auto px-4 py-3 text-xs leading-relaxed font-mono text-default">{{ recommendationJson }}</pre>
      <p class="px-4 py-2 text-xs text-dimmed border-t border-default">
        Only <code>message</code> is written by the language model. <code>schedules</code> and every figure come from
        the verified schedule, scored as in the table below (energy plus the fee above the limit).
      </p>
    </UCard>
    <div v-if="loadingTools" class="h-40 rounded-lg bg-elevated/40 animate-pulse" />

    <template v-if="tools">

      <!-- comparison -->
      <UCard>
        <template #header>
          <div class="flex items-center gap-2">
            <UIcon name="i-lucide-scale" class="size-4 text-primary" />
            <span class="font-semibold text-sm text-highlighted">Cost and saving compared with no scheduling</span>
          </div>
        </template>
        <div class="overflow-x-auto">
          <table class="w-full text-sm tabular-nums">
            <thead class="text-xs text-muted text-left">
              <tr>
                <th class="py-1.5 pr-3 font-medium">System</th>
                <th class="py-1.5 pr-3 font-medium">Peak</th>
                <th class="py-1.5 pr-3 font-medium text-right">Energy</th>
                <th class="py-1.5 pr-3 font-medium text-right">Peak fee</th>
                <th class="py-1.5 pr-3 font-medium text-right">Total</th>
                <th class="py-1.5 pr-3 font-medium text-right">Saving</th>
                <th class="py-1.5 font-medium text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in comparison" :key="r.system" class="border-t border-default" :class="r.system === 'multi_duo_thoughts' ? 'bg-primary/5' : ''">
                <td class="py-1.5 pr-3">
                  <span class="text-highlighted">{{ r.label }}</span>
                  <UBadge :color="groupBadge(r.system).color" variant="subtle" size="xs" class="ml-2">{{ groupBadge(r.system).label }}</UBadge>
                </td>
                <td class="py-1.5 pr-3 whitespace-nowrap">
                  <UTooltip v-if="!r.feasible" :text="r.violations[0] ?? 'Not a usable schedule'">
                    <UBadge color="error" variant="subtle" size="xs" icon="i-lucide-triangle-alert">invalid</UBadge>
                  </UTooltip>
                  <UBadge v-else-if="r.overKw > 0.005" color="warning" variant="subtle" size="xs" icon="i-lucide-zap">
                    {{ r.peakKw.toFixed(1) }} kW, {{ r.overKw.toFixed(1) }} over
                  </UBadge>
                  <UBadge v-else color="success" variant="subtle" size="xs">{{ r.peakKw.toFixed(1) }} kW</UBadge>
                </td>
                <td class="py-1.5 pr-3 text-right text-muted">{{ euro(r.energyEur, 3) }}</td>
                <td class="py-1.5 pr-3 text-right" :class="r.feeEur > 0.0005 ? 'text-warning' : 'text-dimmed'">{{ r.feeEur > 0.0005 ? euro(r.feeEur, 2) : '–' }}</td>
                <td class="py-1.5 pr-3 text-right text-highlighted">{{ euro(r.costEur, 3) }}</td>
                <td class="py-1.5 pr-3 text-right" :class="r.system === 'naive' ? 'text-dimmed' : r.savingEur > 0.0005 ? 'text-success' : r.savingEur < -0.0005 ? 'text-warning' : 'text-muted'">
                  <template v-if="r.system === 'naive'">–</template>
                  <template v-else>{{ euro(r.savingEur, 3) }} · {{ r.savingPct.toFixed(1) }} %</template>
                </td>
                <td class="py-1.5 text-right text-muted">{{ r.latencyS == null ? '–' : r.latencyS < 0.01 ? '< 0.01 s' : `${r.latencyS.toFixed(1)} s` }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-3 text-xs text-dimmed">
          Total = energy cost + {{ euro(tools.feeEurPerKw, 2) }} for each kW of the day's highest load above
          {{ tools.peakLimitKw }} kW. EMHASS is given the limit as its maximum grid power and
          only exceeds it when no schedule fits; the pipeline treats the limit as a target. An invalid schedule
          (an appliance missing or outside its window) saves nothing.
          <template v-if="priceSpread < 1">
            Prices on this day are almost flat ({{ priceSpread.toFixed(1) }} c/kWh between the cheapest and dearest
            hour), so there is little to save; try a winter day such as 2026-01-15.
          </template>
          <template v-if="tools.emhassSkipped === 'periods'">
            EMHASS is not shown: it gives each appliance one start-to-end window, so it cannot plan an appliance with
            several periods. The cheapest-hours rule treats all periods of an appliance as one automation.
          </template>
          <template v-else-if="!tools.emhass"> EMHASS was not reachable (Docker container on localhost:5000), so it is not shown.</template>
        </p>
      </UCard>

      <UCard>
        <template #header>
          <div class="flex items-center gap-2">
            <UIcon name="i-lucide-calendar-range" class="size-4 text-primary" />
            <span class="font-semibold text-sm text-highlighted">When each system runs your appliances</span>
            <span class="text-xs text-dimmed">· click a row to see its load</span>
          </div>
        </template>
        <ScheduleTimeline
          :appliances="tools.appliances"
          :results="runResults"
          :selected="selected"
          :naive-cost="tools.naiveCost"
          :milp-cost="tools.milpCost"
          @select="k => (selected = k)" />
      </UCard>

      <div class="grid gap-4 lg:grid-cols-2">
        <UCard>
          <template #header>
            <div class="flex items-center gap-2">
              <UIcon name="i-lucide-receipt-euro" class="size-4 text-primary" />
              <span class="font-semibold text-sm text-highlighted">Electricity price on {{ tools.date }}, c/kWh</span>
            </div>
          </template>
          <PriceBars :prices="hourlyPrices" />
          <p class="mt-2 text-xs text-dimmed">
            ENTSO-E day-ahead price for Finland plus margin, transfer fee, electricity tax and VAT; hourly means.
          </p>
        </UCard>
        <UCard v-if="current">
          <template #header>
            <div class="flex items-center gap-2">
              <UIcon name="i-lucide-activity" class="size-4 text-primary" />
              <span class="font-semibold text-sm text-highlighted">Household load: {{ current.label }}</span>
            </div>
          </template>
          <LoadChart :base-load-kw="tools.baseLoadKw" :appliances="tools.appliances" :starts="current.starts" :peak-limit-kw="tools.peakLimitKw" />
          <p class="mt-2 text-xs text-dimmed">
            Base load: {{ tools.baseLoad.label }}<template v-if="tools.baseLoad.day"> on {{ tools.baseLoad.day }}, scaled to your average base load</template>.
          </p>
        </UCard>
      </div>
    </template>

  </div>
</template>

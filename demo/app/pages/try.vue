<script setup lang="ts">
// "Try it": enter a household's appliances, active hours and a day (default today); the local API fetches the
// real day-ahead prices (ENTSO-E), builds the base load from the typical REFIT household shape, and runs the
// Multi-Agent Pipeline live next to the existing home energy management tools. Exceeding the peak limit is
// allowed but pays a fee per kW.
import type { ApplianceInput, CatalogItem, Housing, PlanRequest, PlanResult, ToolsResponse } from '~/composables/useTryIt'
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
const activeStart = ref('07:00')
const activeEnd = ref('22:00')

let uid = 0
const appliances = ref<ApplianceInput[]>([
  { uid: ++uid, kind: 'washing_machine', ready: '07:00', finishBy: '22:00' },
  { uid: ++uid, kind: 'dishwasher', ready: '07:00', finishBy: '22:00' },
  { uid: ++uid, kind: 'tumble_dryer', ready: '07:00', finishBy: '22:00' }
])

onMounted(async () => {
  try {
    const c = await api.catalog()
    catalog.value = c.appliances
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

function addAppliance(kind: string) {
  appliances.value.push({ uid: ++uid, kind, ready: activeStart.value, finishBy: activeEnd.value })
}
function applyActiveHours() {
  for (const a of appliances.value) { a.ready = activeStart.value; a.finishBy = activeEnd.value }
}
const addMenu = computed(() => [catalog.value.map(c => ({ label: c.label, icon: applianceIcon(c.kind), onSelect: () => addAppliance(c.kind) }))])

// ── run ──
const tools = ref<ToolsResponse | null>(null)
const agent = ref<PlanResult | null>(null)
const loadingTools = ref(false)
const loadingAgent = ref(false)
const runError = ref('')
const agentError = ref('')

function request(): PlanRequest {
  return {
    date: day.value,
    housing: housing.value,
    base_kw: baseKw.value || undefined,
    peak_limit_kw: peakLimit.value,
    fee_eur_per_kw: fee.value ?? 0,
    appliances: appliances.value.map(a => ({
      kind: a.kind,
      ready: a.ready,
      finish_by: a.finishBy,
      power_kw: item(a.kind)?.measured ? undefined : a.powerKw,
      duration_min: item(a.kind)?.measured ? undefined : a.durationMin
    }))
  }
}

async function run() {
  runError.value = ''
  agentError.value = ''
  tools.value = null
  agent.value = null
  loadingTools.value = true
  const body = request()
  try {
    tools.value = await api.tools(body)
  } catch (e) {
    runError.value = api.errorText(e)
    loadingTools.value = false
    return
  }
  loadingTools.value = false
  loadingAgent.value = true
  try {
    agent.value = (await api.agent(body)).result
  } catch (e) {
    agentError.value = api.errorText(e)
  } finally {
    loadingAgent.value = false
  }
}

// ── results ──
const ORDER = ['multi_rag_opt', 'emhass_rest', 'timer', 'cheapest_window', 'cheapest_hours', 'naive', 'milp']
const allResults = computed<PlanResult[]>(() => {
  const rs = [...(tools.value?.results ?? []), ...(agent.value ? [agent.value] : [])]
  return rs.sort((a, b) => ORDER.indexOf(a.system) - ORDER.indexOf(b.system))
})
const runResults = computed(() => allResults.value.map(toRunResult))
const selected = ref('multi_rag_opt|gpt-4o-mini')
const current = computed(() => runResults.value.find(r => `${r.system}|${r.model}` === selected.value) ?? runResults.value[0])
const pipelineRun = computed(() => runResults.value.find(r => r.system === 'multi_rag_opt'))
const priceCents = computed(() => (tools.value?.priceEurPerKwh ?? []).map(p => p * 100))
const hourlyPrices = computed(() => hourly(priceCents.value))
const priceSpread = computed(() => (hourlyPrices.value.length ? Math.max(...hourlyPrices.value) - Math.min(...hourlyPrices.value) : 0))
const comparison = computed(() => allResults.value.filter(r => r.system !== 'milp'))
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
        GPT-4o-mini (about 20 seconds).
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
          <UInputNumber v-model="baseKw" :min="0.05" :max="5" :step="0.05" placeholder="default" class="w-full" />
        </UFormField>
        <UFormField label="Peak limit" help="Above it, each kW of the day's peak pays the fee">
          <USelect v-model="peakLimit" :items="limitItems" class="w-full" />
        </UFormField>
        <UFormField label="Fee above the limit, €/kW" help="Default: Helen's power charge, €1.57/kW + VAT">
          <UInputNumber v-model="fee" :min="0" :max="50" :step="0.1" :format-options="{ minimumFractionDigits: 2 }" class="w-full" />
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
            <UInput v-model="activeStart" type="time" size="xs" class="w-24" />
            to
            <UInput v-model="activeEnd" type="time" size="xs" class="w-24" />
            <UButton size="xs" variant="soft" color="neutral" @click="applyActiveHours">Apply to all</UButton>
          </div>
        </div>
      </template>
      <div class="space-y-2">
        <div v-for="a in appliances" :key="a.uid" class="grid grid-cols-[1fr_auto] gap-2 sm:grid-cols-[14rem_7rem_7rem_1fr_auto] items-end">
          <UFormField label="Appliance">
            <USelect v-model="a.kind" :items="kindItems" class="w-full" :icon="applianceIcon(a.kind)" />
          </UFormField>
          <UFormField label="Ready from">
            <UInput v-model="a.ready" type="time" class="w-full" />
          </UFormField>
          <UFormField label="Finish by">
            <UInput v-model="a.finishBy" type="time" class="w-full" />
          </UFormField>
          <div class="text-xs text-muted pb-2">
            <template v-if="item(a.kind)?.measured">
              Measured REFIT cycle: {{ item(a.kind)?.durationMin }} min, up to {{ item(a.kind)?.peakKw.toFixed(1) }} kW,
              {{ item(a.kind)?.energyKwh }} kWh
            </template>
            <div v-else-if="item(a.kind)" class="flex flex-wrap items-center gap-2">
              <UInputNumber v-model="a.powerKw" :min="0.1" :max="22" :step="0.1" :placeholder="String(item(a.kind)?.peakKw)" size="xs" class="w-24" /> kW
              <UInputNumber v-model="a.durationMin" :min="15" :max="720" :step="15" :placeholder="String(item(a.kind)?.durationMin)" size="xs" class="w-24" /> min
            </div>
          </div>
          <UButton icon="i-lucide-trash-2" color="neutral" variant="ghost" size="sm" aria-label="Remove appliance" @click="appliances = appliances.filter(x => x.uid !== a.uid)" />
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 pt-2">
          <UDropdownMenu :items="addMenu">
            <UButton icon="i-lucide-plus" variant="soft" size="sm">Add appliance</UButton>
          </UDropdownMenu>
          <UButton icon="i-lucide-sparkles" :loading="loadingTools || loadingAgent" :disabled="!appliances.length || !!apiError" @click="run">
            Get recommendations
          </UButton>
        </div>
        <p class="text-xs text-dimmed">
          Appliance types, powers and durations follow the Low-carbon-alerts appliance catalog; washing machine,
          dishwasher and tumble dryer use real cycles measured in the REFIT homes.
        </p>
      </div>
    </UCard>

    <UAlert v-if="runError" color="error" variant="subtle" icon="i-lucide-triangle-alert" title="Could not plan this day" :description="runError" />
    <div v-if="loadingTools" class="h-40 rounded-lg bg-elevated/40 animate-pulse" />

    <template v-if="tools">
      <!-- the pipeline's recommendation -->
      <UCard v-if="loadingAgent">
        <div class="flex items-center gap-3 text-sm text-muted">
          <UIcon name="i-lucide-loader-circle" class="size-5 animate-spin text-primary" />
          The Multi-Agent Pipeline is planning your day: the Orchestrator, Profiler, Scheduler and Resolver are at work
          (about 20 seconds). The other systems are already shown below.
        </div>
      </UCard>
      <UAlert v-else-if="agentError" color="error" variant="subtle" icon="i-lucide-bot-off" title="The Multi-Agent Pipeline did not answer" :description="agentError" />
      <SystemRecommendationCard
        v-else-if="pipelineRun"
        :result="pipelineRun"
        :appliances="tools.appliances"
        :naive-cost="tools.naiveCost"
        :milp-cost="tools.milpCost" />

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
              <tr v-for="r in comparison" :key="r.system" class="border-t border-default" :class="r.system === 'multi_rag_opt' ? 'bg-primary/5' : ''">
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
          {{ tools.peakLimitKw }} kW. Optimum with the fee: {{ euro(tools.milpCost, 3) }} (saving
          {{ euro(tools.naiveCost - tools.milpCost, 3) }}). EMHASS is given the limit as its maximum grid power and
          only exceeds it when no schedule fits; the pipeline treats the limit as a target. An invalid schedule
          (an appliance missing or outside its window) saves nothing.
          <template v-if="priceSpread < 1">
            Prices on this day are almost flat ({{ priceSpread.toFixed(1) }} c/kWh between the cheapest and dearest
            hour), so there is little to save; try a winter day such as 2026-01-15.
          </template>
          <template v-if="!tools.emhass"> EMHASS was not reachable (Docker container on localhost:5000), so it is not shown.</template>
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

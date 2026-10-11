<script setup lang="ts">
// The Multi-Agent Pipeline's live run, agent by agent: when each agent worked, which tools it called and what it
// handed on. Built from the server-sent events of POST /api/plan/agent/stream.
import type { AgentEvent, AgentName, PlanResult } from '~/composables/useTryIt'

const props = defineProps<{ events: AgentEvent[], running: boolean, summary: string, result?: PlanResult | null }>()

interface ToolCall { name: string, count: number, ms: number, input: string, output: string }
interface Step {
  agent: AgentName
  start: number | null
  end: number | null
  tokens: number
  tools: ToolCall[]
  output: Record<string, unknown> | null
  errors: string[]
}

const AGENTS: { agent: AgentName, label: string, role: string, icon: string }[] = [
  { agent: 'orchestrator', label: 'Orchestrator', role: 'Reads the request and briefs the specialists', icon: 'i-lucide-network' },
  { agent: 'profiler', label: 'Appliance Profiler', role: 'Turns the household data into appliance profiles', icon: 'i-lucide-scan-search' },
  { agent: 'scheduler', label: 'Price-Aware Scheduler', role: 'Plans the start times with the optimiser tool', icon: 'i-lucide-calendar-clock' },
  { agent: 'resolver', label: 'Verification and Conflict Resolver', role: 'Checks the peak limit, every appliance and every window', icon: 'i-lucide-shield-check' },
  { agent: 'summary', label: 'Orchestrator', role: 'Explains the schedule to the household', icon: 'i-lucide-message-square-text' }
]

/** Fold the events into one step per agent and round (the Scheduler and Resolver repeat after feedback). */
const steps = computed(() => {
  const out: Step[] = []
  const open = (agent: AgentName, t: number) => {
    const last = [...out].reverse().find(s => s.agent === agent)
    if (last && last.end === null) return last
    const step: Step = { agent, start: t, end: null, tokens: 0, tools: [], output: null, errors: [] }
    out.push(step)
    return step
  }
  for (const e of props.events) {
    if (!e.agent) continue
    if (e.type === 'working') open(e.agent, e.t)
    else if (e.type === 'tool') {
      const step = open(e.agent, e.t)
      const last = step.tools[step.tools.length - 1]
      if (last && last.name === e.name) {
        last.count++
        last.ms += e.ms ?? 0
      } else {
        step.tools.push({ name: e.name ?? 'tool', count: 1, ms: e.ms ?? 0, input: e.input ?? '', output: String(e.output ?? '') })
      }
    } else if (e.type === 'done') {
      const step = open(e.agent, e.t)
      step.end = e.t
      step.tokens = e.tokens ?? 0
      step.output = (e.output as Record<string, unknown>) ?? null
      step.errors = e.errors ?? []
    }
  }
  return out
})
const stepsOf = (agent: AgentName) => steps.value.filter(s => s.agent === agent)
const latest = (agent: AgentName) => stepsOf(agent).at(-1)

// live clock while the run is in progress
const now = ref(0)
let startedAt = 0
let timer: ReturnType<typeof setInterval> | undefined
watch(() => props.running, (running) => {
  clearInterval(timer)
  if (running) {
    startedAt = performance.now()
    now.value = 0
    timer = setInterval(() => { now.value = (performance.now() - startedAt) / 1000 }, 100)
  }
}, { immediate: true })
onBeforeUnmount(() => clearInterval(timer))

const lastT = computed(() => props.events.length ? props.events[props.events.length - 1]!.t : 0)
const clock = computed(() => props.running ? Math.max(now.value, lastT.value) : lastT.value)

function status(step: Step | undefined): 'waiting' | 'working' | 'done' | 'skipped' {
  if (!step) return 'waiting'
  if (step.end === null) return props.running ? 'working' : 'done'
  return step.agent === 'resolver' && step.output?.skipped ? 'skipped' : 'done'
}
const seconds = (step: Step) => {
  const end = step.end ?? clock.value
  return Math.max(0, end - (step.start ?? end))
}
const kindOf = (id: string) => id.replace(/_\d+$/, '')
const name = (id: string) => applianceName(id, kindOf(id))
const totalTokens = computed(() => props.result?.tokens ?? steps.value.reduce((n, s) => n + s.tokens, 0))
const errorMessage = computed(() => props.events.find(e => e.type === 'error')?.message)
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-workflow" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">How the agents worked</span>
        </div>
        <div class="flex items-center gap-3 text-xs text-muted tabular-nums">
          <span class="flex items-center gap-1">
            <UIcon :name="running ? 'i-lucide-loader-circle' : 'i-lucide-timer'" :class="running ? 'animate-spin text-primary' : ''" class="size-3.5" />
            {{ clock.toFixed(1) }} s
          </span>
          <span v-if="totalTokens">{{ totalTokens.toLocaleString() }} tokens</span>
          <span v-if="result?.usd != null">${{ result.usd.toFixed(4) }}</span>
        </div>
      </div>
    </template>

    <UAlert v-if="errorMessage" color="error" variant="subtle" icon="i-lucide-triangle-alert" :description="errorMessage" class="mb-3" />

    <ol class="relative space-y-4">
      <li v-for="(a, i) in AGENTS" :key="a.agent + i" class="relative pl-10">
        <span v-if="i < AGENTS.length - 1" class="absolute left-[0.95rem] top-8 bottom-[-1rem] w-px bg-(--ui-border)" aria-hidden="true" />
        <div class="absolute left-0 top-0 flex size-8 items-center justify-center rounded-full border"
             :class="{
               'border-default text-dimmed': status(latest(a.agent)) === 'waiting',
               'border-primary text-primary bg-primary/10': status(latest(a.agent)) === 'working',
               'border-primary/40 text-primary bg-primary/5': status(latest(a.agent)) === 'done',
               'border-default text-muted bg-elevated': status(latest(a.agent)) === 'skipped'
             }">
          <UIcon :name="status(latest(a.agent)) === 'working' ? 'i-lucide-loader-circle' : a.icon" class="size-4"
                 :class="status(latest(a.agent)) === 'working' ? 'animate-spin' : ''" />
        </div>
        <template v-for="(step, round) in (stepsOf(a.agent).length ? stepsOf(a.agent) : [undefined])" :key="round">
          <div :class="round > 0 ? 'mt-3 border-t border-default pt-3' : ''">
            <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <div class="flex flex-wrap items-baseline gap-x-2">
                <span class="text-sm font-medium" :class="status(step) === 'waiting' ? 'text-dimmed' : 'text-highlighted'">{{ a.label }}</span>
                <span class="text-xs text-muted">{{ a.role }}</span>
                <UBadge v-if="round > 0" size="xs" variant="subtle" color="warning">round {{ round + 1 }}</UBadge>
                <UBadge v-if="a.agent === 'profiler' && step" size="xs" variant="subtle" color="neutral">in parallel with the Orchestrator</UBadge>
              </div>
              <span v-if="step" class="text-xs text-muted tabular-nums">
                <template v-if="status(step) === 'skipped'">not needed</template>
                <template v-else>{{ seconds(step).toFixed(1) }} s<template v-if="step.tokens"> · {{ step.tokens.toLocaleString() }} tokens</template></template>
              </span>
              <span v-else class="text-xs text-dimmed">waiting</span>
            </div>

            <!-- what the agent handed on -->
            <div v-if="step?.output" class="mt-1.5 text-sm">
              <template v-if="a.agent === 'orchestrator'">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="text-xs text-muted">Brief:</span>
                  <UBadge v-for="id in (step.output.appliances as string[])" :key="id" variant="outline" color="neutral" size="sm" :icon="applianceIcon(kindOf(id))">{{ name(id) }}</UBadge>
                </div>
                <p v-if="step.output.notes" class="mt-1 text-xs text-muted">{{ step.output.notes }}</p>
              </template>

              <div v-else-if="a.agent === 'profiler'" class="overflow-x-auto">
                <table class="text-xs tabular-nums">
                  <thead class="text-muted text-left">
                    <tr><th class="pr-4 font-normal">Appliance</th><th class="pr-4 font-normal">Flexible</th><th class="pr-4 font-normal">Peak</th><th class="pr-4 font-normal">Runtime</th><th class="font-normal">Window</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="p in (step.output.appliances as { id: string, kind: string, flexible: boolean, peakKw: number, durationMin: number, window: string }[])" :key="p.id">
                      <td class="pr-4 py-0.5">{{ applianceName(p.id, p.kind) }}</td>
                      <td class="pr-4">{{ p.flexible ? 'yes' : 'no' }}</td>
                      <td class="pr-4">{{ p.peakKw.toFixed(2) }} kW</td>
                      <td class="pr-4">{{ p.durationMin }} min</td>
                      <td>{{ p.window }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <template v-else-if="a.agent === 'scheduler'">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="text-xs text-muted">Proposal:</span>
                  <UBadge v-for="(time, id) in (step.output.starts as Record<string, string>)" :key="id" variant="soft" size="sm" :icon="applianceIcon(kindOf(String(id)))">
                    {{ name(String(id)) }} {{ time }}
                  </UBadge>
                </div>
                <p v-if="step.output.explanation" class="mt-1 text-xs text-muted">{{ step.output.explanation }}</p>
              </template>

              <template v-else-if="a.agent === 'resolver'">
                <p v-if="step.output.skipped" class="flex items-center gap-1.5 text-xs text-success">
                  <UIcon name="i-lucide-circle-check" class="size-3.5" />
                  Verification passed: within the peak limit, every appliance scheduled, every start inside its window. The Resolver was not called.
                </p>
                <template v-else>
                  <p class="text-xs text-muted">Changes: {{ step.output.changes }}</p>
                  <p v-if="step.output.feedback" class="mt-1 flex items-start gap-1.5 text-xs text-warning">
                    <UIcon name="i-lucide-undo-2" class="size-3.5 mt-0.5 shrink-0" />
                    Sent back to the Scheduler: {{ step.output.feedback }}
                  </p>
                  <p v-else class="mt-1 flex items-center gap-1.5 text-xs text-success">
                    <UIcon name="i-lucide-circle-check" class="size-3.5" /> Verification passed after the changes.
                  </p>
                </template>
              </template>
            </div>

            <!-- the summary is shown as it is written -->
            <p v-if="a.agent === 'summary' && (summary || status(step) === 'working')" class="mt-1.5 text-sm text-default">
              {{ summary }}<span v-if="status(step) === 'working'" class="inline-block w-1.5 h-4 align-text-bottom bg-primary/70 animate-pulse ml-0.5" />
            </p>

            <p v-for="err in step?.errors ?? []" :key="err" class="mt-1 text-xs text-error">{{ err }}</p>

            <!-- tool calls -->
            <div v-if="step?.tools.length" class="mt-1.5 flex flex-col gap-1">
              <details v-for="(tool, k) in step.tools" :key="k" class="group text-xs">
                <summary class="flex cursor-pointer list-none items-center gap-1.5 text-muted hover:text-default">
                  <UIcon name="i-lucide-chevron-right" class="size-3 transition-transform group-open:rotate-90" />
                  <UIcon name="i-lucide-wrench" class="size-3" />
                  <code class="font-mono">{{ tool.name }}</code>
                  <span v-if="tool.count > 1">× {{ tool.count }}</span>
                  <span class="tabular-nums text-dimmed">{{ tool.ms }} ms</span>
                </summary>
                <pre class="mt-1 ml-6 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-elevated/60 p-2 font-mono text-[11px] text-muted">{{ tool.count > 1 ? `${tool.count} calls; last result:\n` : '' }}{{ tool.output }}</pre>
              </details>
            </div>
          </div>
        </template>
      </li>
    </ol>
  </UCard>
</template>

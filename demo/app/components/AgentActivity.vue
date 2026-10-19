<script setup lang="ts">
// The live run, step by step, of either agent design. Two agents: the Orchestrator agent and the
// Scheduler agent) and two functions without a language model (profile_data, verify_schedule). For every action an
// agent takes, the page shows its Thought and the function it called with the arguments, and the result
// (Observation). Built from the server-sent events of POST /api/plan/agent/stream.
import type { AgentEvent, AgentInput, AgentName, Design, PlanResult } from '~/composables/useTryIt'

const props = withDefaults(defineProps<{ events: AgentEvent[], running: boolean, summary: string, result?: PlanResult | null, design?: Design, title?: string }>(),
  { result: null, design: 'two_agents', title: '' })

interface ToolCall { name: string, count: number, ms: number, args: string, output: string, thoughts: string[], turn: number }
interface Step {
  agent: AgentName
  start: number | null
  end: number | null
  tokens: number
  calls: number // model calls of this step
  tools: ToolCall[]
  output: Record<string, unknown> | null
  errors: string[]
  input: AgentInput | null
}

// kind "agent": a language model agent; kind "function": a deterministic step, shown by its function name
interface Lane { agent: AgentName, label: string, role: string, icon: string, kind: 'agent' | 'function' }
const TWO_AGENTS: Lane[] = [
  { agent: 'orchestrator', label: 'Orchestrator agent', role: 'Reads the request and briefs the Scheduler agent', icon: 'i-lucide-network', kind: 'agent' },
  { agent: 'profile_data', label: 'profile_data()', role: 'Builds the appliance profiles from the household data', icon: 'i-lucide-database', kind: 'function' },
  { agent: 'retrieve_examples', label: 'retrieve_examples()', role: 'RAG: finds the most similar solved days in the case library and adds them as worked examples to the message of the Scheduler agent', icon: 'i-lucide-library', kind: 'function' },
  { agent: 'scheduler', label: 'Scheduler agent', role: 'Plans the start times with its tools and fixes any reported problem', icon: 'i-lucide-calendar-clock', kind: 'agent' },
  { agent: 'verify_schedule', label: 'verify_schedule()', role: 'Checks the peak limit, every appliance and every window; problems go back to the Scheduler agent', icon: 'i-lucide-shield-check', kind: 'function' },
  { agent: 'summary', label: 'Orchestrator agent', role: 'Explains the schedule to the household', icon: 'i-lucide-message-square-text', kind: 'agent' }
]
// one agent in the same harness: the same functions; the agent reads the request, plans, fixes and explains
const ONE_AGENT: Lane[] = [
  { agent: 'profile_data', label: 'profile_data()', role: 'Builds the appliance profiles from the household data', icon: 'i-lucide-database', kind: 'function' },
  { agent: 'retrieve_examples', label: 'retrieve_examples()', role: 'RAG: finds the most similar solved days in the case library and adds them as worked examples to the message of the agent', icon: 'i-lucide-library', kind: 'function' },
  { agent: 'agent', label: 'Agent', role: 'Reads the request, plans the start times with its tools and fixes any reported problem', icon: 'i-lucide-bot', kind: 'agent' },
  { agent: 'verify_schedule', label: 'verify_schedule()', role: 'Checks the peak limit, every appliance and every window; problems go back to the agent in the same conversation', icon: 'i-lucide-shield-check', kind: 'function' },
  { agent: 'explain', label: 'Agent', role: 'Explains the schedule to the household, with its whole conversation in view', icon: 'i-lucide-message-square-text', kind: 'agent' }
]
const LANES = computed(() => props.design === 'one_agent' ? ONE_AGENT : TWO_AGENTS)
const ACTING = new Set<AgentName>(['scheduler', 'agent']) // agents that call tools
const WRITING = new Set<AgentName>(['summary', 'explain']) // where the household message is written

/** Fold the events into one step per lane and round (the Scheduler agent and the check repeat after feedback). */
const steps = computed(() => {
  const out: Step[] = []
  const open = (agent: AgentName, t: number) => {
    const last = [...out].reverse().find(s => s.agent === agent)
    if (last && last.end === null) return last
    const step: Step = { agent, start: t, end: null, tokens: 0, calls: 0, tools: [], output: null, errors: [], input: null }
    out.push(step)
    return step
  }
  for (const e of props.events) {
    if (!e.agent) continue
    if (e.type === 'working') open(e.agent, e.t).calls++
    else if (e.type === 'input' && e.prompt) {
      const step = open(e.agent, e.t)
      step.input ??= e.prompt
    }
    else if (e.type === 'tool') {
      const step = open(e.agent, e.t)
      step.tools.push({ name: e.name ?? 'tool', count: 1, ms: e.ms ?? 0, args: e.input ?? '', output: String(e.output ?? ''),
        thoughts: e.thought ? [e.thought] : [], turn: e.turn ?? step.tools.length })
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

function status(step: Step | undefined): 'waiting' | 'working' | 'done' | 'passed' {
  if (!step) return 'waiting'
  if (step.end === null) return props.running ? 'working' : 'done'
  return step.agent === 'verify_schedule' && step.output?.passed ? 'passed' : 'done'
}
// the flow diagram: each node's status; verify_schedule is 'failed' while its latest check sent the schedule back
const flowStatus = computed(() => Object.fromEntries(LANES.value.map(({ agent }) => {
  const step = latest(agent)
  const s = status(step)
  return [agent, agent === 'verify_schedule' && s === 'done' && step?.output && !step.output.passed ? 'failed' : s]
})) as Record<AgentName, 'waiting' | 'working' | 'done' | 'passed' | 'failed'>)
const looped = computed(() => stepsOf(props.design === 'one_agent' ? 'agent' : 'scheduler').length > 1)
const seconds = (step: Step) => {
  const end = step.end ?? clock.value
  return Math.max(0, end - (step.start ?? end))
}

/** The function call as code: optimize_schedule(appliance_ids=[washing_machine_1, dishwasher_1]) */
function callText(tool: ToolCall): string {
  let args: Record<string, unknown> = {}
  try {
    args = JSON.parse(tool.args)
  } catch {
    return `${tool.name}(${tool.args})`
  }
  const value = (v: unknown): string => Array.isArray(v)
    ? `[${v.map(value).join(', ')}]`
    : v && typeof v === 'object'
      ? `{${Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${value(x)}`).join(', ')}}`
      : String(v)
  const text = Object.entries(args).map(([k, v]) => `${k}=${value(v)}`).join(', ')
  return `${tool.name}(${text.length > 160 ? `${text.slice(0, 157)}…` : text})`
}
// tools an agent returns its structured answer through; not actions
const ANSWER_TOOLS = new Set(['TaskBrief', 'ScheduleOutput'])
/** Consecutive actions requested by the same model call (made together in one response). */
function byTurn(tools: ToolCall[]): ToolCall[][] {
  const out: ToolCall[][] = []
  for (const tool of tools) {
    const last = out.at(-1)
    if (last && last[0]!.turn === tool.turn) last.push(tool)
    else out.push([tool])
  }
  return out
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
        <div class="flex flex-wrap items-center gap-2">
          <UIcon name="i-lucide-workflow" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">{{ title ? `How it worked: ${title}` : 'How the agents worked' }}</span>
          <span class="text-xs text-dimmed">· {{ design === 'one_agent' ? 'one language model agent' : 'two language model agents' }}; <code class="font-mono">profile_data()</code> and
            <code class="font-mono">verify_schedule()</code> are functions without a model</span>
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

    <PipelineFlow :status="flowStatus" :looped="looped" :design="design" class="mb-4" />

    <UAlert v-if="errorMessage" color="error" variant="subtle" icon="i-lucide-triangle-alert" :description="errorMessage" class="mb-3" />

    <ol class="relative space-y-4">
      <li v-for="(a, i) in LANES" :key="a.agent + i" class="relative pl-10">
        <span v-if="i < LANES.length - 1" class="absolute left-[0.95rem] top-8 bottom-[-1rem] w-px bg-(--ui-border)" aria-hidden="true" />
        <div class="absolute left-0 top-0 flex size-8 items-center justify-center border"
             :class="[a.kind === 'function' ? 'rounded-md' : 'rounded-full', {
               'border-default text-dimmed': status(latest(a.agent)) === 'waiting',
               'border-primary text-primary bg-primary/10': status(latest(a.agent)) === 'working',
               'border-primary/40 text-primary bg-primary/5': status(latest(a.agent)) === 'done',
               'border-success/40 text-success bg-success/5': status(latest(a.agent)) === 'passed'
             }]">
          <UIcon :name="status(latest(a.agent)) === 'working' ? 'i-lucide-loader-circle' : a.icon" class="size-4"
                 :class="status(latest(a.agent)) === 'working' ? 'animate-spin' : ''" />
        </div>
        <template v-for="(step, round) in (stepsOf(a.agent).length ? stepsOf(a.agent) : [undefined])" :key="round">
          <div :class="round > 0 ? 'mt-3 border-t border-default pt-3' : ''">
            <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <div class="flex flex-wrap items-baseline gap-x-2">
                <span class="text-sm font-medium" :class="[status(step) === 'waiting' ? 'text-dimmed' : 'text-highlighted', a.kind === 'function' ? 'font-mono' : '']">{{ a.label }}</span>
                <span class="text-xs text-muted">{{ a.role }}</span>
                <UBadge v-if="round > 0" size="xs" variant="subtle" color="warning">round {{ round + 1 }}</UBadge>
                <UBadge v-if="a.kind === 'function'" size="xs" variant="outline" color="neutral">function, no language model</UBadge>
                <UBadge v-if="a.agent === 'profile_data' && step && design === 'two_agents'" size="xs" variant="subtle" color="neutral">in parallel with the Orchestrator agent</UBadge>
              </div>
              <span v-if="step" class="text-xs text-muted tabular-nums">
                <template v-if="status(step) === 'passed'">passed</template>
                <template v-else>{{ seconds(step).toFixed(1) }} s<template v-if="a.kind === 'agent' && step.calls"> · {{ step.calls }} model call{{ step.calls === 1 ? '' : 's' }}</template><template v-if="step.tokens"> · {{ step.tokens.toLocaleString() }} tokens</template></template>
              </span>
              <span v-else class="text-xs text-dimmed">waiting</span>
            </div>

            <!-- what the agent was given: system prompt, message, tools -->
            <details v-if="step?.input" class="group/input mt-1.5 text-xs">
              <summary class="flex cursor-pointer list-none items-center gap-1.5 text-muted hover:text-default">
                <UIcon name="i-lucide-chevron-right" class="size-3 shrink-0 transition-transform group-open/input:rotate-90" />
                <span>Input</span>
                <span class="text-dimmed">· system prompt, message<template v-if="step.input.tools.some(t => !ANSWER_TOOLS.has(t))">, {{ step.input.tools.filter(t => !ANSWER_TOOLS.has(t)).length }} tools</template></span>
              </summary>
              <div class="ml-4 mt-1 flex flex-col gap-2">
                <div v-if="step.input.tools.length" class="flex flex-wrap items-center gap-1">
                  <span class="text-muted">Tools:</span>
                  <UBadge v-for="t in step.input.tools.filter(t => !ANSWER_TOOLS.has(t))" :key="t" size="xs" variant="outline" color="neutral" class="font-mono">{{ t }}()</UBadge>
                  <span v-for="t in step.input.tools.filter(t => ANSWER_TOOLS.has(t))" :key="t" class="text-dimmed">answers with <code class="font-mono">{{ t }}</code></span>
                </div>
                <div>
                  <p class="text-muted">System prompt</p>
                  <pre class="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-elevated/60 p-2 font-mono text-[11px] text-muted">{{ step.input.system }}</pre>
                </div>
                <div>
                  <p class="text-muted">Message</p>
                  <pre class="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-elevated/60 p-2 font-mono text-[11px] text-muted">{{ step.input.message }}</pre>
                </div>
              </div>
            </details>

            <!-- what the step handed on -->
            <div v-if="step?.output" class="mt-1.5 text-sm">
              <template v-if="a.agent === 'orchestrator'">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="text-xs text-muted">Brief:</span>
                  <UBadge v-for="id in (step.output.appliances as string[])" :key="id" variant="outline" color="neutral" size="sm" :icon="applianceIcon(kindOf(id))">{{ name(id) }}</UBadge>
                </div>
                <p v-if="step.output.notes" class="mt-1 text-xs text-muted">{{ step.output.notes }}</p>
              </template>

              <div v-else-if="a.agent === 'profile_data'" class="overflow-x-auto">
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

              <div v-else-if="a.agent === 'retrieve_examples'" class="flex flex-col gap-1.5">
                <p class="text-xs text-muted">
                  {{ (step.output.examples as unknown[]).length }} of {{ step.output.library }} solved days, by similarity of
                  the price shape and the appliances (no language model, no embeddings):
                </p>
                <details v-for="ex in (step.output.examples as { id: string, type: string, date: string, similarity: number, text: string }[])"
                         :key="ex.id" class="group/rag text-xs">
                  <summary class="flex cursor-pointer list-none flex-wrap items-center gap-1.5 text-muted hover:text-default">
                    <UIcon name="i-lucide-chevron-right" class="size-3 shrink-0 transition-transform group-open/rag:rotate-90" />
                    <code class="font-mono text-highlighted">{{ ex.id }}</code>
                    <span>{{ ex.type.replaceAll('-', ' · ') }}</span>
                    <span class="text-dimmed">{{ ex.date }}</span>
                    <UBadge size="xs" variant="subtle" color="neutral">similarity {{ ex.similarity.toFixed(2) }}</UBadge>
                  </summary>
                  <pre class="ml-4 mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-elevated/60 p-2 font-mono text-[11px] text-muted">{{ ex.text }}</pre>
                </details>
              </div>

              <template v-else-if="ACTING.has(a.agent)">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="text-xs text-muted">Proposal:</span>
                  <UBadge v-for="(time, id) in (step.output.starts as Record<string, string>)" :key="id" variant="soft" size="sm" :icon="applianceIcon(kindOf(String(id)))">
                    {{ name(String(id)) }} {{ time }}
                  </UBadge>
                </div>
                <p v-if="step.output.explanation" class="mt-1 text-xs text-muted">{{ step.output.explanation }}</p>
              </template>

              <template v-else-if="a.agent === 'verify_schedule'">
                <p v-if="step.output.passed" class="flex items-center gap-1.5 text-xs text-success">
                  <UIcon name="i-lucide-circle-check" class="size-3.5" />
                  Passed: within the peak limit, every appliance scheduled, every start inside its window.
                </p>
                <p v-else class="flex items-start gap-1.5 text-xs text-warning">
                  <UIcon name="i-lucide-undo-2" class="size-3.5 mt-0.5 shrink-0" />
                  Sent back to the Scheduler agent: {{ step.output.feedback }}
                </p>
              </template>
            </div>

            <!-- the summary is shown as it is written -->
            <p v-if="WRITING.has(a.agent) && (summary || status(step) === 'working')" class="mt-1.5 text-sm text-default">
              {{ summary }}<span v-if="status(step) === 'working'" class="inline-block w-1.5 h-4 align-text-bottom bg-primary/70 animate-pulse ml-0.5" />
            </p>

            <p v-for="err in step?.errors ?? []" :key="err" class="mt-1 text-xs text-error">{{ err }}</p>

            <!-- the Scheduler agent's ReAct steps: Thought, Action (the function it called) and Observation (what the
                 function returned). The Orchestrator agent has no tools; checks made by code are not agent actions. -->
            <div v-if="ACTING.has(a.agent) && step?.tools.length" class="mt-1.5 flex flex-col gap-1.5">
              <div v-for="(group, g) in byTurn(step.tools)" :key="g"
                   :class="group.length > 1 ? 'rounded-md border border-dashed border-default px-2 py-1.5 flex flex-col gap-1.5' : ''">
                <p v-if="group.length > 1" class="flex items-center gap-1.5 text-[11px] text-dimmed">
                  <UIcon name="i-lucide-layers" class="size-3 shrink-0" />
                  {{ group.length }} actions in one response (run together)
                </p>
              <div v-for="(tool, k) in group" :key="k" class="text-xs">
                <p v-for="(t, j) in tool.thoughts" :key="j" class="mb-0.5 flex items-start gap-1.5 text-default">
                  <UIcon name="i-lucide-lightbulb" class="size-3 mt-0.5 shrink-0 text-warning" />
                  <span><span class="text-muted">Thought:</span> {{ t }}</span>
                </p>
                <p class="flex items-start gap-1.5 text-muted">
                  <UIcon name="i-lucide-play" class="size-3 mt-0.5 shrink-0 text-primary" />
                  <span class="shrink-0">Action:</span>
                  <code class="font-mono text-highlighted break-all">{{ callText(tool) }}</code>
                  <span class="shrink-0 tabular-nums text-dimmed">{{ tool.ms }} ms</span>
                </p>
                <div class="mt-0.5 flex items-start gap-1.5 text-muted">
                  <UIcon name="i-lucide-eye" class="size-3 mt-0.5 shrink-0 text-info" />
                  <span class="shrink-0">Observation:</span>
                  <pre class="min-w-0 flex-1 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-elevated/60 px-2 py-1 font-mono text-[11px] text-muted">{{ tool.output }}</pre>
                </div>
              </div>
              </div>
            </div>
          </div>
        </template>
      </li>
    </ol>
  </UCard>
</template>

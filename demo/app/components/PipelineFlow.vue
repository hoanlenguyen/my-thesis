<script setup lang="ts">
// The agent design as LangGraph runs it, for either design: the two-agent pipeline
// (src/hems/agents/multi_agent.py) or one agent in the same harness (src/hems/agents/harness_agent.py). Agents and
// functions are joined by graph edges; no agent calls profile_data() or verify_schedule(), the graph runs them.
// retrieve_examples() (RAG) adds similar solved days to the acting agent's message. Each node is coloured by its
// status in the live run.
import type { AgentName, Design } from '~/composables/useTryIt'

type Status = 'waiting' | 'working' | 'done' | 'passed' | 'failed'
const props = withDefaults(defineProps<{ status: Partial<Record<AgentName, Status>>, looped: boolean, design?: Design }>(),
  { design: 'two_agents' })

interface Node { id: AgentName, x: number, y: number, title: string, sub: string, kind: 'agent' | 'function' }
const W = 124
const H = 40
const Y = 70 // the main line
const LAYOUTS: Record<Design, { nodes: Node[], acting: AgentName, inParallel: boolean }> = {
  two_agents: {
    nodes: [
      { id: 'orchestrator', x: 140, y: 38, title: 'Orchestrator agent', sub: 'plan: brief', kind: 'agent' },
      { id: 'profile_data', x: 140, y: 102, title: 'profile_data()', sub: 'household data', kind: 'function' },
      { id: 'scheduler', x: 312, y: Y, title: 'Scheduler agent', sub: 'tools + solver', kind: 'agent' },
      { id: 'verify_schedule', x: 476, y: Y, title: 'verify_schedule()', sub: 'limit, appliances, windows', kind: 'function' },
      { id: 'summary', x: 640, y: Y, title: 'Orchestrator agent', sub: 'summary', kind: 'agent' }
    ],
    acting: 'scheduler',
    inParallel: true
  },
  one_agent: {
    nodes: [
      { id: 'profile_data', x: 140, y: Y, title: 'profile_data()', sub: 'household data', kind: 'function' },
      { id: 'agent', x: 312, y: Y, title: 'Agent', sub: 'request, tools + solver', kind: 'agent' },
      { id: 'verify_schedule', x: 476, y: Y, title: 'verify_schedule()', sub: 'limit, appliances, windows', kind: 'function' },
      { id: 'explain', x: 640, y: Y, title: 'Agent', sub: 'message, same chat', kind: 'agent' }
    ],
    acting: 'agent',
    inParallel: false
  }
}
const layout = computed(() => LAYOUTS[props.design])
const at = (id: AgentName) => layout.value.nodes.find(n => n.id === id)!
const left = (id: AgentName) => at(id).x - W / 2
const right = (id: AgentName) => at(id).x + W / 2
const statusOf = (id: AgentName): Status => props.status[id] ?? 'waiting'

/** Graph edges: [path, the node whose status colours it]. */
const edges = computed<[string, AgentName][]>(() => {
  const nodes = layout.value.nodes
  const acting = layout.value.acting
  const last = nodes[nodes.length - 1]!.id
  const out: [string, AgentName][] = []
  if (layout.value.inParallel) {
    const [a, b] = [nodes[0]!.id, nodes[1]!.id]
    out.push([`M29,66 C50,40 55,${at(a).y} ${left(a)},${at(a).y}`, a])
    out.push([`M29,74 C50,100 55,${at(b).y} ${left(b)},${at(b).y}`, b])
    out.push([`M${right(a)},${at(a).y} C225,38 225,64 ${left(acting)},64`, acting])
    out.push([`M${right(b)},${at(b).y} C225,102 225,76 ${left(acting)},76`, acting])
  } else {
    const first = nodes[0]!.id
    out.push([`M29,${Y} L${left(first)},${Y}`, first])
    out.push([`M${right(first)},${Y} L${left(acting)},${Y}`, acting])
  }
  out.push([`M${right(acting)},${Y} L${left('verify_schedule')},${Y}`, 'verify_schedule'])
  out.push([`M${right('verify_schedule')},${Y} L${left(last)},${Y}`, last])
  out.push([`M${right(last)},${Y} L726,${Y}`, last])
  return out
})

const tone = (s: Status) => ({
  waiting: 'text-dimmed',
  working: 'text-primary',
  done: 'text-primary',
  passed: 'text-success',
  failed: 'text-warning'
})[s]
const edgeTone = (to: AgentName) => statusOf(to) === 'waiting' ? 'text-(--ui-border-accented)' : 'text-muted'
const backTo = computed(() => props.design === 'one_agent' ? 'back to the agent, same conversation' : 'back with feedback')
</script>

<template>
  <figure class="overflow-x-auto">
    <svg viewBox="0 0 760 202" class="min-w-[560px] w-full" role="img"
         :aria-label="design === 'one_agent'
           ? 'One agent: profile_data, then the agent, verify_schedule which may send the schedule back once, and the agent writes the message'
           : 'Two agents: Orchestrator agent and profile_data in parallel, then the Scheduler agent, verify_schedule which may send the schedule back once, and the Orchestrator agent\'s summary'">
      <defs>
        <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
        </marker>
      </defs>

      <!-- RAG: the retrieved solved days are added to the acting agent's message (a step of the harness, not a call) -->
      <g :class="[tone(statusOf('retrieve_examples')), statusOf('retrieve_examples') === 'working' ? 'animate-pulse' : '']">
        <rect :x="at(layout.acting).x - W / 2" y="3" :width="W" height="32" rx="4" fill="currentColor"
              :fill-opacity="statusOf('retrieve_examples') === 'waiting' ? 0.03 : 0.1" stroke="currentColor"
              stroke-width="1.2" stroke-dasharray="5 3" />
        <text :x="at(layout.acting).x" y="17" text-anchor="middle" class="text-[11px] font-medium font-mono"
              :class="statusOf('retrieve_examples') === 'waiting' ? 'fill-(--ui-text-muted)' : 'fill-(--ui-text-highlighted)'">retrieve_examples()</text>
        <text :x="at(layout.acting).x" y="29" text-anchor="middle" class="fill-(--ui-text-dimmed) text-[9px]">RAG: similar solved days</text>
      </g>
      <path :class="edgeTone(layout.acting)" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#flow-arrow)"
            :d="`M${at(layout.acting).x},35 L${at(layout.acting).x},${30 + Y - H / 2 - 1}`" />
      <text :x="at(layout.acting).x + 6" :y="30 + Y - H / 2 - 6" class="fill-(--ui-text-dimmed) text-[9px]">worked examples</text>

      <g transform="translate(0, 30)">

      <!-- start and end -->
      <circle cx="22" :cy="Y" r="7" class="fill-(--ui-text-muted)" />
      <text x="22" :y="Y + 24" text-anchor="middle" class="fill-(--ui-text-dimmed) text-[10px]">start</text>
      <circle cx="736" :cy="Y" r="8" fill="none" stroke-width="1.5" class="stroke-(--ui-text-muted)" />
      <circle cx="736" :cy="Y" r="4.5" class="fill-(--ui-text-muted)" />
      <text x="736" :y="Y + 24" text-anchor="middle" class="fill-(--ui-text-dimmed) text-[10px]">end</text>

      <!-- edges, run by the graph -->
      <g fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#flow-arrow)">
        <path v-for="([d, to], k) in edges" :key="k" :class="edgeTone(to)" :d="d" />
        <!-- feedback loop: problems found and fewer than 2 rounds -->
        <path :class="looped ? 'text-warning' : 'text-(--ui-border-accented)'" :stroke-dasharray="looped ? '' : '4 3'"
              :d="`M${at('verify_schedule').x},${Y + H / 2} L${at('verify_schedule').x},142 L${at(layout.acting).x},142 L${at(layout.acting).x},${Y + H / 2 + 2}`" />
      </g>
      <text :x="(at(layout.acting).x + at('verify_schedule').x) / 2" y="160" text-anchor="middle"
            class="text-[10px]" :class="looped ? 'fill-(--ui-warning)' : 'fill-(--ui-text-dimmed)'">
        problems found and round &lt; 2: {{ backTo }}
      </text>
      <text :x="(right('verify_schedule') + left(layout.nodes[layout.nodes.length - 1]!.id)) / 2" :y="Y - 8" text-anchor="middle" class="fill-(--ui-text-dimmed) text-[10px]">passed</text>
      <text v-if="layout.inParallel" x="198" y="16" text-anchor="middle" class="fill-(--ui-text-dimmed) text-[10px]">in parallel</text>

      <!-- nodes -->
      <g v-for="n in layout.nodes" :key="n.id" :class="[tone(statusOf(n.id)), statusOf(n.id) === 'working' ? 'animate-pulse' : '']">
        <rect :x="n.x - W / 2" :y="n.y - H / 2" :width="W" :height="H" :rx="n.kind === 'agent' ? H / 2 : 4"
              fill="currentColor" :fill-opacity="statusOf(n.id) === 'waiting' ? 0.03 : 0.1" stroke="currentColor"
              :stroke-width="statusOf(n.id) === 'working' ? 2 : 1.2" :stroke-dasharray="n.kind === 'function' ? '5 3' : ''" />
        <text :x="n.x" :y="n.y - 2" text-anchor="middle" class="text-[11px] font-medium"
              :class="[statusOf(n.id) === 'waiting' ? 'fill-(--ui-text-muted)' : 'fill-(--ui-text-highlighted)', n.kind === 'function' ? 'font-mono' : '']">{{ n.title }}</text>
        <text :x="n.x" :y="n.y + 11" text-anchor="middle" class="fill-(--ui-text-dimmed) text-[9px]">{{ n.sub }}</text>
      </g>
      </g>
    </svg>
    <figcaption class="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-dimmed">
      <span class="flex items-center gap-1.5"><span class="inline-block h-3 w-5 rounded-full border border-current" /> agent (language model)</span>
      <span class="flex items-center gap-1.5"><span class="inline-block h-3 w-5 rounded-sm border border-dashed border-current" /> function, no language model</span>
      <span>Arrows are graph edges: LangGraph runs every step in this order; no agent calls <code class="font-mono">profile_data()</code> or <code class="font-mono">verify_schedule()</code>.</span>
    </figcaption>
  </figure>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { portalTerminalApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { TerminalScope } from '@/types/inventory'

const props = defineProps<{
  environmentId: string
  canExecute?: boolean
}>()

const canExecute = props.canExecute ?? true
const scope: TerminalScope = 'hosting'

type Line = {
  id: number
  kind: 'cmd' | 'out' | 'err' | 'meta'
  text: string
}

const cwd = ref('')
const command = ref('')
const running = ref(false)
const lines = ref<Line[]>([])
const scrollEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)
let lineId = 0

function push(kind: Line['kind'], text: string) {
  lines.value.push({ id: ++lineId, kind, text })
}

async function scrollBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function run() {
  if (!canExecute || running.value) return
  const cmd = command.value.trim()
  if (!cmd) return
  running.value = true
  const promptCwd = cwd.value.trim() || '~'
  push('cmd', `${promptCwd} $ ${cmd}`)
  // Keep the command box ready for the next command; do not wipe session history.
  command.value = ''
  await scrollBottom()
  try {
    const { data } = await portalTerminalApi.execute(props.environmentId, {
      command: cmd,
      cwd: cwd.value || undefined,
      scope,
    })
    if (data.stdout?.trim()) push('out', data.stdout.replace(/\n$/, ''))
    if (data.stderr?.trim()) push('err', data.stderr.replace(/\n$/, ''))
    push('meta', data.success ? `exit ${data.exit_code ?? 0}` : `failed · exit ${data.exit_code ?? '—'}`)
  } catch (e) {
    push('err', getApiErrorMessage(e, 'Command failed'))
  } finally {
    running.value = false
    await scrollBottom()
    inputEl.value?.focus()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void run()
  }
}

function clearScreen() {
  lines.value = []
  push('meta', 'Screen cleared. Previous commands remain in server audit logs.')
}

onMounted(() => {
  push('meta', 'Terminal ready. Commands run inside your hosting home. Enter to run · Shift+Enter for newline.')
  inputEl.value?.focus()
})
</script>

<template>
  <div class="term">
    <div class="term-bar">
      <h2>Terminal</h2>
      <label class="cwd">
        <span>cwd</span>
        <input v-model="cwd" type="text" placeholder="leave empty for home" :disabled="!canExecute" />
      </label>
      <button type="button" class="ghost" :disabled="!lines.length" @click="clearScreen">Clear screen</button>
    </div>

    <p v-if="!canExecute" class="blocked">Terminal is not enabled on this hosting pack.</p>

    <div ref="scrollEl" class="term-screen" role="log" aria-live="polite">
      <div v-for="line in lines" :key="line.id" class="line" :class="line.kind">
        <pre>{{ line.text }}</pre>
      </div>
      <div v-if="running" class="line meta"><pre>…</pre></div>
    </div>

    <div class="term-input">
      <textarea
        ref="inputEl"
        v-model="command"
        rows="2"
        spellcheck="false"
        :disabled="running || !canExecute"
        placeholder="Type next command…"
        @keydown="onKeydown"
      />
      <button type="button" class="run" :disabled="running || !command.trim() || !canExecute" @click="run">
        {{ running ? 'Running…' : 'Run' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.term {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  font-family: Figtree, ui-sans-serif, system-ui, sans-serif;
}
.term-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
}
.term-bar h2 {
  margin: 0;
  font-size: 1.05rem;
}
.cwd {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: #5a6570;
  flex: 1;
  min-width: 12rem;
}
.cwd input {
  flex: 1;
  border: 1px solid #d5dce3;
  border-radius: 6px;
  padding: 0.35rem 0.5rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
}
.ghost {
  border: 1px solid #d5dce3;
  background: #fff;
  border-radius: 6px;
  padding: 0.35rem 0.65rem;
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}
.blocked {
  color: #5a6570;
  font-size: 0.9rem;
}
.term-screen {
  background: #0b1220;
  color: #d1fae5;
  border-radius: 10px;
  min-height: 18rem;
  max-height: min(60vh, 28rem);
  overflow: auto;
  padding: 0.75rem 0.85rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  line-height: 1.4;
}
.line + .line {
  margin-top: 0.45rem;
}
.line pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.line.cmd {
  color: #6ee7b7;
}
.line.out {
  color: #e2e8f0;
}
.line.err {
  color: #fca5a5;
}
.line.meta {
  color: #94a3b8;
  font-size: 0.72rem;
}
.term-input {
  display: flex;
  gap: 0.5rem;
  align-items: stretch;
}
.term-input textarea {
  flex: 1;
  border: 1px solid #d5dce3;
  border-radius: 8px;
  padding: 0.55rem 0.65rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.82rem;
  background: #0b1220;
  color: #6ee7b7;
  resize: vertical;
  min-height: 2.75rem;
}
.run {
  border: 0;
  border-radius: 8px;
  background: #059669;
  color: #fff;
  padding: 0 1rem;
  font: inherit;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}
.run:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

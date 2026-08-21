<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import AiAgentPanel from '@/components/ai/AiAgentPanel.vue'
import { terminalApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { TerminalAuditEntry, TerminalExecuteResponse } from '@/types/hosting'

const router = useRouter()
const { can } = usePermissions()
const canExecute = computed(() => can(Permission.TERMINAL_EXECUTE))

const command = ref('')
const cwd = ref('')
const running = ref(false)
const loadingAudit = ref(true)
const result = ref<TerminalExecuteResponse | null>(null)
const audit = ref<TerminalAuditEntry[]>([])
const message = ref<{ ok: boolean; text: string } | null>(null)
const clearing = ref(false)
const showAi = ref(true)
const history = ref<string[]>([])

async function run() {
  if (!command.value.trim() || !canExecute.value) return
  running.value = true
  message.value = null
  result.value = null
  try {
    const { data } = await terminalApi.execute(command.value, cwd.value || undefined)
    result.value = data
    history.value.unshift(command.value)
    if (history.value.length > 20) history.value.pop()
    await loadAudit()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Command failed') }
  } finally {
    running.value = false
  }
}

async function loadAudit() {
  loadingAudit.value = true
  try {
    const { data } = await terminalApi.audit(40)
    audit.value = data
  } catch {
    audit.value = []
  } finally {
    loadingAudit.value = false
  }
}

async function clearLogs() {
  if (!confirm('Clear all terminal audit logs? This cannot be undone.')) return
  clearing.value = true
  message.value = null
  try {
    const { data } = await terminalApi.clearAudit()
    audit.value = []
    result.value = null
    history.value = []
    message.value = { ok: data.success, text: data.message }
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Failed to clear terminal logs') }
  } finally {
    clearing.value = false
  }
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {
    ev.preventDefault()
    run()
  }
}

function reuseCommand(cmd: string) {
  command.value = cmd
}

function onAiApplied(action: { type: string; command?: string | null }) {
  if (action.type === 'terminal' && action.command) {
    command.value = action.command
  }
  loadAudit()
}

function closeWindow() {
  if (window.opener) {
    window.close()
    return
  }
  router.push({ name: 'terminal' })
}

onMounted(loadAudit)
</script>

<template>
  <div class="term-shell">
    <header class="term-top">
      <div class="term-identity">
        <button type="button" class="icon-btn" title="Close" @click="closeWindow">←</button>
        <span class="ext-chip">TERM</span>
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold text-emerald-100">IFNOTUS Terminal</p>
          <p class="truncate font-mono text-[11px] text-emerald-500/70">
            {{ cwd || '~' }} · controlled execution
          </p>
        </div>
      </div>
      <div class="term-tools">
        <button type="button" class="tool-btn" @click="showAi = !showAi">
          {{ showAi ? 'Hide AI' : 'AI' }}
        </button>
        <button
          type="button"
          class="tool-btn"
          :disabled="clearing || (!audit.length && !result)"
          @click="clearLogs"
        >
          {{ clearing ? 'Clearing…' : 'Clear logs' }}
        </button>
        <button type="button" class="tool-btn" @click="closeWindow">Close</button>
      </div>
    </header>

    <div v-if="!canExecute" class="term-denied">
      You do not have permission to execute terminal commands.
    </div>

    <div v-else class="term-body" :class="{ 'with-ai': showAi }">
      <main class="term-main">
        <section class="term-input-pane">
          <label class="field">
            <span>Working directory</span>
            <input v-model="cwd" placeholder="/var/www or leave empty" />
          </label>
          <label class="field grow">
            <span>Command <em>⌘/Ctrl + Enter</em></span>
            <textarea
              v-model="command"
              rows="4"
              placeholder="ls -la"
              spellcheck="false"
              @keydown="onKeydown"
            />
          </label>
          <div class="term-actions">
            <button type="button" class="run-btn" :disabled="running || !command.trim()" @click="run">
              {{ running ? 'Running…' : 'Execute' }}
            </button>
            <p v-if="message" class="msg" :class="message.ok ? 'ok' : 'err'">{{ message.text }}</p>
          </div>
        </section>

        <section class="term-output-pane">
          <div v-if="running && !result" class="pad">
            <Skeleton height="0.85rem" width="30%" />
            <Skeleton class="mt-2" height="8rem" />
          </div>

          <div v-else-if="result" class="output-block">
            <div class="output-meta">
              <Badge :variant="result.success ? 'success' : 'danger'" size="sm">
                exit {{ result.exit_code }}
              </Badge>
              <span>audit {{ result.audit_id }}</span>
            </div>
            <pre v-if="result.stdout" class="stdout">{{ result.stdout }}</pre>
            <pre v-if="result.stderr" class="stderr">{{ result.stderr }}</pre>
            <pre v-if="!result.stdout && !result.stderr" class="stdout muted">(no output)</pre>
          </div>

          <div v-else class="pad muted">Run a command to see output here.</div>
        </section>

        <section class="term-audit-pane">
          <div class="pane-head">
            <h2>Recent commands</h2>
            <span>{{ audit.length }}</span>
          </div>
          <div v-if="loadingAudit" class="pad space-y-2">
            <Skeleton height="2.5rem" />
            <Skeleton height="2.5rem" />
          </div>
          <div v-else-if="!audit.length" class="pad muted">No audit entries yet.</div>
          <div v-else class="audit-list">
            <button
              v-for="entry in audit"
              :key="entry.id"
              type="button"
              class="audit-item"
              @click="reuseCommand(entry.command)"
            >
              <div class="audit-meta">
                <span class="font-mono">{{ entry.username }}</span>
                <Badge :variant="entry.success ? 'success' : 'danger'" size="sm">
                  {{ entry.exit_code ?? '—' }}
                </Badge>
                <span class="when">{{ entry.executed_at }}</span>
              </div>
              <p class="cmd">{{ entry.command }}</p>
              <p v-if="entry.output_preview" class="preview">{{ entry.output_preview }}</p>
            </button>
          </div>
        </section>
      </main>

      <aside v-if="showAi" class="term-ai">
        <AiAgentPanel
          surface="terminal"
          :cwd="cwd || undefined"
          :path="cwd || undefined"
          @applied="onAiApplied"
        />
      </aside>
    </div>
  </div>
</template>

<style scoped>
.term-shell {
  display: flex;
  height: 100vh;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(ellipse 70% 50% at 50% -10%, rgba(16, 185, 129, 0.12), transparent 55%),
    #020805;
  color: #d1fae5;
}
.term-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 1px solid rgba(16, 185, 129, 0.18);
  background: rgba(7, 17, 12, 0.92);
  padding: 0.65rem 0.85rem;
}
.term-identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.65rem;
}
.icon-btn,
.tool-btn,
.run-btn {
  border: 1px solid rgba(16, 185, 129, 0.28);
  border-radius: 0.55rem;
  background: rgba(16, 185, 129, 0.08);
  color: #a7f3d0;
  font-size: 0.75rem;
  font-weight: 600;
}
.icon-btn {
  display: grid;
  width: 2rem;
  height: 2rem;
  place-items: center;
}
.tool-btn {
  padding: 0.4rem 0.7rem;
}
.tool-btn:disabled,
.run-btn:disabled {
  opacity: 0.45;
}
.ext-chip {
  border-radius: 0.4rem;
  background: rgba(16, 185, 129, 0.18);
  padding: 0.2rem 0.45rem;
  color: #6ee7b7;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.term-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.term-denied {
  display: grid;
  flex: 1;
  place-items: center;
  color: #94a3b8;
  font-size: 0.9rem;
}
.term-body {
  display: grid;
  min-height: 0;
  flex: 1;
  grid-template-columns: minmax(0, 1fr);
}
.term-body.with-ai {
  grid-template-columns: minmax(0, 1fr) minmax(18rem, 24rem);
}
.term-main {
  display: grid;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr) minmax(10rem, 28%);
}
.term-input-pane {
  display: grid;
  gap: 0.65rem;
  border-bottom: 1px solid rgba(16, 185, 129, 0.14);
  padding: 0.85rem 1rem;
}
.field {
  display: grid;
  gap: 0.35rem;
  font-size: 0.72rem;
  color: rgba(110, 231, 183, 0.75);
}
.field span em {
  margin-left: 0.4rem;
  font-style: normal;
  opacity: 0.65;
}
.field input,
.field textarea {
  width: 100%;
  border: 1px solid rgba(16, 185, 129, 0.22);
  border-radius: 0.65rem;
  background: rgba(0, 0, 0, 0.45);
  padding: 0.55rem 0.75rem;
  color: #a7f3d0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.85rem;
}
.field textarea {
  resize: vertical;
  min-height: 5.5rem;
}
.term-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}
.run-btn {
  background: rgba(16, 185, 129, 0.22);
  padding: 0.5rem 1rem;
  color: #ecfdf5;
}
.msg.ok { color: #6ee7b7; font-size: 0.8rem; }
.msg.err { color: #fca5a5; font-size: 0.8rem; }
.term-output-pane,
.term-audit-pane {
  min-height: 0;
  overflow: auto;
}
.term-output-pane {
  border-bottom: 1px solid rgba(16, 185, 129, 0.14);
}
.pad {
  padding: 1rem;
}
.pad.muted,
.muted {
  color: rgba(110, 231, 183, 0.55);
  font-size: 0.85rem;
}
.output-block {
  padding: 0.85rem 1rem 1rem;
}
.output-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem;
  margin-bottom: 0.65rem;
  color: rgba(110, 231, 183, 0.65);
  font-size: 0.7rem;
}
.stdout,
.stderr {
  max-height: none;
  overflow: auto;
  border-radius: 0.65rem;
  padding: 0.75rem 0.85rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
.stdout {
  background: rgba(0, 0, 0, 0.55);
  color: #e2e8f0;
}
.stderr {
  margin-top: 0.5rem;
  background: rgba(127, 29, 29, 0.35);
  color: #fecaca;
}
.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 1rem 0.35rem;
}
.pane-head h2 {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(110, 231, 183, 0.7);
}
.pane-head span {
  color: rgba(110, 231, 183, 0.5);
  font-size: 0.7rem;
}
.audit-list {
  display: grid;
  gap: 0.35rem;
  padding: 0.35rem 0.65rem 0.85rem;
}
.audit-item {
  width: 100%;
  border: 1px solid rgba(16, 185, 129, 0.12);
  border-radius: 0.65rem;
  background: rgba(0, 0, 0, 0.28);
  padding: 0.55rem 0.7rem;
  text-align: left;
  color: inherit;
}
.audit-item:hover {
  border-color: rgba(16, 185, 129, 0.35);
  background: rgba(16, 185, 129, 0.06);
}
.audit-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.7rem;
  color: rgba(110, 231, 183, 0.75);
}
.audit-meta .when {
  opacity: 0.7;
}
.cmd {
  margin: 0.35rem 0 0;
  color: #a7f3d0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.75rem;
}
.preview {
  margin: 0.25rem 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(148, 163, 184, 0.85);
  font-size: 0.68rem;
}
.term-ai {
  min-height: 0;
  overflow: hidden;
  border-left: 1px solid rgba(16, 185, 129, 0.18);
  background: rgba(7, 17, 12, 0.88);
}
.term-ai :deep(.ai-panel) {
  height: 100%;
  border: 0;
  border-radius: 0;
}
@media (max-width: 1100px) {
  .term-body.with-ai {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(0, 1fr) minmax(16rem, 40%);
  }
  .term-ai {
    border-left: 0;
    border-top: 1px solid rgba(16, 185, 129, 0.18);
  }
}
</style>

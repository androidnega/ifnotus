<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
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

const history = ref<string[]>([])

function openFullscreen() {
  const href = router.resolve({ name: 'terminal-full' }).href
  const win = window.open(href, 'ifnotus-terminal-full')
  if (!win) {
    message.value = {
      ok: false,
      text: 'Pop-up blocked — allow pop-ups for this site, or open /terminal/full directly.',
    }
  }
}

async function run() {
  if (!command.value.trim()) return
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
    const { data } = await terminalApi.audit(30)
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
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault()
    run()
  }
}

function onAiApplied(action: { type: string; command?: string | null }) {
  if (action.type === 'terminal' && action.command) {
    command.value = action.command
  }
  loadAudit()
}

onMounted(loadAudit)
</script>

<template>
  <DashboardLayout @refresh="loadAudit">
    <div class="animate-fade-in space-y-5">
      <UiPageHeader title="Terminal" lede="Controlled host command execution with audit logging (not an SSH session)">
        <template #actions>
          <div class="flex flex-wrap items-center gap-2">
            <button
              v-if="canExecute"
              type="button"
              class="ds-btn-primary text-sm"
              @click="openFullscreen"
            >
              Open fullscreen
            </button>
            <button
              v-if="canExecute"
              type="button"
              class="ds-btn-ghost text-sm"
              :disabled="clearing || (!audit.length && !result)"
              @click="clearLogs"
            >
              {{ clearing ? 'Clearing…' : 'Clear logs' }}
            </button>
          </div>
        </template>
      </UiPageHeader>

      <Card v-if="!canExecute" padding="md">
        <p class="text-sm text-surface-muted">You do not have permission to execute terminal commands.</p>
      </Card>

      <div v-else class="terminal-with-agent">
        <div class="space-y-5 min-w-0">
          <Card padding="md">
            <label class="block text-sm">
              <span class="text-surface-muted">Working directory (optional)</span>
              <input v-model="cwd" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm" placeholder="/var/www" />
            </label>
            <label class="mt-3 block text-sm">
              <span class="text-surface-muted">Command</span>
              <textarea
                v-model="command"
                rows="3"
                class="mt-1 w-full rounded-lg border border-surface-border bg-slate-950 px-3 py-2 font-mono text-sm text-emerald-300"
                placeholder="ls -la"
                @keydown="onKeydown"
              />
            </label>
            <button
              type="button"
              class="mt-3 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              :disabled="running || !command.trim()"
              @click="run"
            >
              {{ running ? 'Running…' : 'Execute' }}
            </button>
              <UiAlert v-if="message" :tone="message.ok ? 'ok' : 'err'" class="mt-2">{{ message.text }}</UiAlert>
            </Card>

          <Card v-if="running && !result" padding="md">
            <div class="space-y-2">
              <Skeleton height="0.85rem" width="30%" />
              <Skeleton height="6rem" />
            </div>
          </Card>

          <Card v-if="result" padding="md">
            <div class="mb-2 flex items-center gap-2">
              <Badge :variant="result.success ? 'success' : 'danger'" size="sm">exit {{ result.exit_code }}</Badge>
              <span class="text-xs text-surface-muted">audit {{ result.audit_id }}</span>
            </div>
            <pre v-if="result.stdout" class="max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{{ result.stdout }}</pre>
            <pre v-if="result.stderr" class="mt-2 max-h-32 overflow-auto rounded-lg bg-red-950/30 p-3 text-xs text-red-200">{{ result.stderr }}</pre>
          </Card>

          <Card padding="md">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 class="text-sm font-semibold">Recent commands</h2>
              <button
                type="button"
                class="rounded-lg border border-surface-border px-2.5 py-1 text-xs hover:bg-slate-50 disabled:opacity-50 dark:hover:bg-slate-800"
                :disabled="clearing || !audit.length"
                @click="clearLogs"
              >
                {{ clearing ? 'Clearing…' : 'Clear logs' }}
              </button>
            </div>
            <div v-if="loadingAudit" class="space-y-2">
              <Skeleton height="2.5rem" />
              <Skeleton height="2.5rem" />
              <Skeleton height="2.5rem" />
            </div>
            <div v-else-if="!audit.length" class="text-sm text-surface-muted">No audit entries yet.</div>
            <div v-else class="max-h-[min(50vh,24rem)] overflow-auto rounded-lg border border-surface-border/60">
              <div
                v-for="entry in audit"
                :key="entry.id"
                class="border-b border-surface-border px-3 py-2 text-sm last:border-b-0"
              >
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-mono text-xs">{{ entry.username }}</span>
                  <Badge :variant="entry.success ? 'success' : 'danger'" size="sm">{{ entry.exit_code ?? '—' }}</Badge>
                  <span class="text-xs text-surface-muted">{{ entry.executed_at }}</span>
                </div>
                <p class="mt-1 font-mono text-xs">{{ entry.command }}</p>
                <p v-if="entry.output_preview" class="mt-1 truncate text-xs text-surface-muted">{{ entry.output_preview }}</p>
              </div>
            </div>
          </Card>
        </div>

        <AiAgentPanel
          surface="terminal"
          :cwd="cwd || undefined"
          :path="cwd || undefined"
          @applied="onAiApplied"
        />
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.terminal-with-agent {
  display: grid;
  gap: 1rem;
}
@media (min-width: 1280px) {
  .terminal-with-agent {
    grid-template-columns: minmax(0, 1fr) minmax(18rem, 22rem);
    align-items: start;
  }
}
</style>

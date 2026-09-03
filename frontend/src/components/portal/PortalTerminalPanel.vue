<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import { portalTerminalApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { TerminalAuditEntry, TerminalExecuteResponse } from '@/types/hosting'
import type { TerminalScope } from '@/types/inventory'

const props = defineProps<{
  environmentId: string
  canExecute?: boolean
}>()

const canExecute = props.canExecute ?? true

const command = ref('')
const cwd = ref('')
const running = ref(false)
const result = ref<TerminalExecuteResponse | null>(null)
const audit = ref<TerminalAuditEntry[]>([])
const message = ref<{ ok: boolean; text: string } | null>(null)
const loadingAudit = ref(true)
const clearing = ref(false)

const scope: TerminalScope = 'hosting'

async function run() {
  if (!canExecute) return
  if (!command.value.trim()) return
  running.value = true
  message.value = null
  result.value = null
  try {
    const { data } = await portalTerminalApi.execute(props.environmentId, {
      command: command.value.trim(),
      cwd: cwd.value || undefined,
      scope,
    })
    result.value = data
    command.value = ''
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
    const { data } = await portalTerminalApi.audit(props.environmentId, 40)
    audit.value = data
  } catch {
    audit.value = []
  } finally {
    loadingAudit.value = false
  }
}

async function clearLogs() {
  if (!confirm('Clear terminal audit logs for you? This cannot be undone.')) return
  clearing.value = true
  message.value = null
  try {
    const { data } = await portalTerminalApi.clearAudit(props.environmentId)
    audit.value = []
    result.value = null
    message.value = { ok: data.success, text: data.message || 'Cleared.' }
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Failed to clear logs') }
  } finally {
    clearing.value = false
  }
}

onMounted(() => {
  void loadAudit()
})
</script>

<template>
  <div class="hp-terminal">
    <h2 class="hp-card-title">Terminal</h2>

    <div class="space-y-4">
      <Card padding="md">
        <label class="block text-sm">
          <span class="text-surface-muted">Working directory (optional)</span>
          <input
            v-model="cwd"
            class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
            placeholder="/var/www or leave empty"
          />
        </label>

        <label class="mt-3 block text-sm">
          <span class="text-surface-muted"
            >Command <em class="text-xs">(safe, audited, stays inside your hosting roots)</em></span
          >
          <textarea
            v-model="command"
            rows="4"
            class="mt-1 w-full rounded-lg border border-surface-border bg-slate-950 px-3 py-2 font-mono text-sm text-emerald-300"
            placeholder="ls -la"
          />
        </label>

        <div class="mt-3 flex items-center gap-3">
          <button
            type="button"
            class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            :disabled="running || !command.trim() || !canExecute"
            @click="run"
          >
            {{ running ? 'Running…' : 'Execute' }}
          </button>
          <button
            type="button"
            class="rounded-lg border border-surface-border px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
            :disabled="clearing || !audit.length || !canExecute"
            @click="clearLogs"
          >
            {{ clearing ? 'Clearing…' : 'Clear logs' }}
          </button>
        </div>

        <UiAlert v-if="message" :tone="message.ok ? 'ok' : 'err'" class="mt-3">
          {{ message.text }}
        </UiAlert>

        <div v-if="!canExecute" class="mt-3 text-sm text-surface-muted">
          Terminal execution is not enabled for this hosting pack.
        </div>
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
        <pre v-if="result.stdout" class="max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">
{{ result.stdout }}
        </pre>
        <pre
          v-if="result.stderr"
          class="mt-2 max-h-32 overflow-auto rounded-lg bg-red-950/30 p-3 text-xs text-red-200"
        >
{{ result.stderr }}
        </pre>
      </Card>

      <Card padding="md">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-sm font-semibold">Recent commands</h3>
          <span class="text-xs text-surface-muted">{{ audit.length }}</span>
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
  </div>
</template>

<style scoped>
.hp-terminal :deep(.hp-card-title) {
  font-weight: 700;
  margin-bottom: 8px;
}
</style>


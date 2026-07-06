<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { terminalApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { TerminalAuditEntry, TerminalExecuteResponse } from '@/types/hosting'

const { can } = usePermissions()
const canExecute = computed(() => can(Permission.TERMINAL_EXECUTE))

const command = ref('')
const cwd = ref('')
const running = ref(false)
const result = ref<TerminalExecuteResponse | null>(null)
const audit = ref<TerminalAuditEntry[]>([])
const message = ref<string | null>(null)

const history = ref<string[]>([])

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
    message.value = e instanceof Error ? e.message : 'Command failed'
  } finally {
    running.value = false
  }
}

async function loadAudit() {
  try {
    const { data } = await terminalApi.audit(30)
    audit.value = data
  } catch {
    audit.value = []
  }
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault()
    run()
  }
}

onMounted(loadAudit)
</script>

<template>
  <DashboardLayout @refresh="loadAudit">
    <div class="animate-fade-in space-y-5">
      <div>
        <h1 class="text-lg font-semibold text-slate-900 dark:text-white">Terminal</h1>
        <p class="text-sm text-surface-muted">Controlled command execution with audit logging</p>
      </div>

      <Card v-if="!canExecute" padding="md">
        <p class="text-sm text-surface-muted">You do not have permission to execute terminal commands.</p>
      </Card>

      <template v-else>
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
          <p v-if="message" class="mt-2 text-sm text-red-600">{{ message }}</p>
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
          <h2 class="mb-3 text-sm font-semibold">Recent commands</h2>
          <div v-if="!audit.length" class="text-sm text-surface-muted">No audit entries yet.</div>
          <div v-for="entry in audit" :key="entry.id" class="border-t border-surface-border py-2 text-sm">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-mono text-xs">{{ entry.username }}</span>
              <Badge :variant="entry.success ? 'success' : 'danger'" size="sm">{{ entry.exit_code ?? '—' }}</Badge>
              <span class="text-xs text-surface-muted">{{ entry.executed_at }}</span>
            </div>
            <p class="mt-1 font-mono text-xs">{{ entry.command }}</p>
            <p v-if="entry.output_preview" class="mt-1 truncate text-xs text-surface-muted">{{ entry.output_preview }}</p>
          </div>
        </Card>
      </template>
    </div>
  </DashboardLayout>
</template>

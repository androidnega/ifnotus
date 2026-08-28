<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import ConfirmPasswordModal from '@/components/databases/ConfirmPasswordModal.vue'
import { securityApi, terminalApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { useAuthStore } from '@/stores/auth'
import { isPlatformOwner } from '@/lib/roles'
import { Permission } from '@/lib/permissions'
import type {
  AccessAttemptEntry,
  BlockedActionEntry,
  FirewallRuleEntry,
  IpBlacklistEntry,
  SystemActionLogEntry,
} from '@/types/security'
import type { TerminalAuditEntry } from '@/types/hosting'

const auth = useAuthStore()
const { can } = usePermissions()
const allowed = computed(() => can(Permission.SYSTEM_ADMIN) || can(Permission.SYSTEM_READ) || isPlatformOwner(auth.user))
const canMutate = computed(() => isPlatformOwner(auth.user))

const loading = ref(false)
const message = ref<{ ok: boolean; text: string } | null>(null)

const attempts = ref<AccessAttemptEntry[]>([])
const blacklist = ref<IpBlacklistEntry[]>([])
const firewall = ref<FirewallRuleEntry[]>([])
const blocked = ref<BlockedActionEntry[]>([])
const availableActions = ref<Array<{ key: string; label: string }>>([])
const actionLogs = ref<SystemActionLogEntry[]>([])
const terminalAudit = ref<TerminalAuditEntry[]>([])
const terminalAuditError = ref<string | null>(null)

const blockIp = ref('')
const blockReason = ref('Manual block')
const blockHours = ref<number | null>(24)

const ruleCidr = ref('')
const ruleAction = ref<'allow' | 'deny'>('allow')
const ruleNote = ref('')

const blockActionKey = ref('')
const blockActionReason = ref('')

const clearModalOpen = ref(false)
const clearBusy = ref(false)
const clearError = ref<string | null>(null)
const logsDownloaded = ref(false)

async function loadAll() {
  if (!allowed.value) return
  loading.value = true
  message.value = null
  terminalAuditError.value = null
  try {
    const [a, b, f, ba, logs, term] = await Promise.all([
      securityApi.attempts(150),
      securityApi.blacklist(true),
      securityApi.firewall(),
      securityApi.blockedActions(),
      securityApi.actionLogs(250),
      terminalApi.audit(50).catch((e) => {
        terminalAuditError.value = getApiErrorMessage(e, 'Terminal audit unavailable')
        return { data: [] as TerminalAuditEntry[] }
      }),
    ])
    attempts.value = a.data.attempts
    blacklist.value = b.data.entries
    firewall.value = f.data.rules
    blocked.value = ba.data.entries
    availableActions.value = ba.data.available
    actionLogs.value = logs.data.logs
    terminalAudit.value = Array.isArray(term.data) ? term.data : []
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Failed to load security data') }
  } finally {
    loading.value = false
  }
}

function downloadSecurityLogs() {
  const payload = {
    exported_at: new Date().toISOString(),
    login_activity: attempts.value,
    action_audit: actionLogs.value,
    terminal_audit: terminalAudit.value,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  a.href = url
  a.download = `ifnotus-security-logs-${stamp}.json`
  a.click()
  URL.revokeObjectURL(url)
  logsDownloaded.value = true
  message.value = {
    ok: true,
    text: 'Security logs downloaded. You can clear them after confirming your password.',
  }
}

function startClearLogs() {
  clearError.value = null
  if (!logsDownloaded.value) {
    downloadSecurityLogs()
  }
  clearModalOpen.value = true
}

async function confirmClearLogs(password: string) {
  clearBusy.value = true
  clearError.value = null
  try {
    if (!logsDownloaded.value) {
      downloadSecurityLogs()
    }
    const { data } = await securityApi.clearLogs({
      confirm_password: password,
      acknowledge_downloaded: true,
      clear_attempts: true,
      clear_actions: true,
      clear_terminal: true,
    })
    clearModalOpen.value = false
    logsDownloaded.value = false
    message.value = {
      ok: true,
      text: `${data.message} (attempts ${data.cleared.attempts ?? 0}, actions ${data.cleared.actions ?? 0}, terminal ${data.cleared.terminal ?? 0})`,
    }
    await loadAll()
  } catch (e) {
    clearError.value = getApiErrorMessage(e, 'Clear failed — check password')
  } finally {
    clearBusy.value = false
  }
}

async function submitBlockIp() {
  if (!blockIp.value.trim()) return
  try {
    await securityApi.blockIp({
      ip_address: blockIp.value.trim(),
      reason: blockReason.value || 'Manual block',
      hours: blockHours.value,
    })
    blockIp.value = ''
    message.value = { ok: true, text: 'IP blocked.' }
    await loadAll()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Block failed') }
  }
}

async function unlock(entry: IpBlacklistEntry) {
  try {
    await securityApi.unlock(entry.id, 'Unlocked from Security page')
    message.value = { ok: true, text: `Unlocked ${entry.ip_address}` }
    await loadAll()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Unlock failed') }
  }
}

async function addFirewallRule() {
  if (!ruleCidr.value.trim()) return
  try {
    await securityApi.createFirewallRule({
      cidr: ruleCidr.value.trim(),
      action: ruleAction.value,
      note: ruleNote.value || undefined,
    })
    ruleCidr.value = ''
    ruleNote.value = ''
    message.value = { ok: true, text: 'Firewall rule added.' }
    await loadAll()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Firewall update failed') }
  }
}

async function removeRule(rule: FirewallRuleEntry) {
  try {
    await securityApi.deleteFirewallRule(rule.id)
    message.value = { ok: true, text: 'Rule removed.' }
    await loadAll()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Remove failed') }
  }
}

async function blockAction() {
  const key = blockActionKey.value
  if (!key) return
  try {
    await securityApi.setBlockedAction({
      action_key: key,
      enabled: true,
      reason: blockActionReason.value || 'Blocked by administrator',
    })
    blockActionReason.value = ''
    message.value = { ok: true, text: `Blocked ${key}` }
    await loadAll()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Could not block action') }
  }
}

async function unblockAction(entry: BlockedActionEntry) {
  try {
    await securityApi.unblockAction(entry.action_key)
    message.value = { ok: true, text: `Unblocked ${entry.action_key}` }
    await loadAll()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Unblock failed') }
  }
}

function sourceBadge(source?: string) {
  if (source === 'ssh') return 'warning'
  if (source === 'cli') return 'info'
  return 'neutral'
}

onMounted(loadAll)
</script>

<template>
  <DashboardLayout @refresh="loadAll">
    <div v-if="!allowed" class="rounded-xl border border-surface-border bg-surface-raised p-6 text-sm text-surface-muted">
      Administrator permission required to manage security and audit logs.
    </div>

    <div v-else class="animate-fade-in space-y-5">
      <UiPageHeader
        title="Security & Audit"
        lede="Panel access rules, IP blocks, kill-switches, and login/action audits. This is not the OS packet firewall."
      >
        <template #actions>
          <div class="flex flex-wrap gap-2">
            <button type="button" class="ds-btn-ghost text-sm" :disabled="loading" @click="downloadSecurityLogs">
              Download logs
            </button>
            <button
              v-if="canMutate"
              type="button"
              class="rounded-lg border border-red-300 bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
              :disabled="loading || clearBusy"
              @click="startClearLogs"
            >
              Clear logs…
            </button>
            <button type="button" class="ds-btn-ghost text-sm" :disabled="loading" @click="loadAll">
              {{ loading ? 'Loading…' : 'Refresh' }}
            </button>
          </div>
        </template>
      </UiPageHeader>

      <UiAlert v-if="message" :tone="message.ok ? 'ok' : 'err'">{{ message.text }}</UiAlert>

      <Card v-if="canMutate" title="Block actions" subtitle="Kill-switch sensitive capabilities for everyone">
        <div class="mb-3 flex flex-wrap gap-2">
          <select v-model="blockActionKey" class="input">
            <option value="" disabled>Select action…</option>
            <option v-for="item in availableActions" :key="item.key" :value="item.key">
              {{ item.label }} ({{ item.key }})
            </option>
          </select>
          <input v-model="blockActionReason" class="input" placeholder="Reason" />
          <button type="button" class="btn danger" @click="blockAction">Block</button>
        </div>
        <div v-if="!blocked.length" class="text-sm text-surface-muted">No actions are blocked.</div>
        <div v-else class="space-y-2">
          <div
            v-for="entry in blocked"
            :key="entry.id"
            class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border px-3 py-2 text-sm"
          >
            <div>
              <p class="font-medium">{{ entry.label || entry.action_key }}</p>
              <p class="text-xs text-surface-muted">{{ entry.action_key }} · {{ entry.reason || '—' }}</p>
            </div>
            <button type="button" class="btn ghost" @click="unblockAction(entry)">Unblock</button>
          </div>
        </div>
      </Card>

      <div v-if="canMutate" class="grid gap-5 xl:grid-cols-2">
        <Card title="Panel CIDR rules" subtitle="Allow trusted ranges · deny hostile ranges for panel access">
          <p class="mb-3 text-xs text-surface-muted">
            If any <strong>allow</strong> rule exists, only matching networks can reach the panel (health checks exempt).
            Deny rules always block.
          </p>
          <div class="mb-3 flex flex-wrap gap-2">
            <input v-model="ruleCidr" class="input" placeholder="CIDR e.g. 10.0.0.0/8 or 203.0.113.10/32" />
            <select v-model="ruleAction" class="input w-auto">
              <option value="allow">allow</option>
              <option value="deny">deny</option>
            </select>
            <input v-model="ruleNote" class="input" placeholder="Note (optional)" />
            <button type="button" class="btn" @click="addFirewallRule">Add rule</button>
          </div>
          <div v-if="!firewall.length" class="text-sm text-surface-muted">No firewall rules yet.</div>
          <div v-else class="max-h-56 space-y-2 overflow-y-auto">
            <div
              v-for="rule in firewall"
              :key="rule.id"
              class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border px-3 py-2 text-sm"
            >
              <div>
                <p class="font-mono font-medium">{{ rule.cidr }}</p>
                <p class="text-xs text-surface-muted">{{ rule.action }} · {{ rule.note || '—' }}</p>
              </div>
              <button type="button" class="btn ghost" @click="removeRule(rule)">Remove</button>
            </div>
          </div>
        </Card>

        <Card title="IP blocks" subtitle="Manual lockout + auto-block after 3 failed logins (3 days)">
          <div class="mb-3 flex flex-wrap gap-2">
            <input v-model="blockIp" class="input" placeholder="IP address" />
            <input v-model="blockReason" class="input" placeholder="Reason" />
            <input v-model.number="blockHours" type="number" min="1" class="input w-28" placeholder="Hours" />
            <button type="button" class="btn danger" @click="submitBlockIp">Block IP</button>
          </div>
          <div v-if="!blacklist.length" class="text-sm text-surface-muted">No active IP blocks.</div>
          <div v-else class="max-h-56 space-y-2 overflow-y-auto">
            <div
              v-for="entry in blacklist"
              :key="entry.id"
              class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border px-3 py-2 text-sm"
            >
              <div class="min-w-0">
                <p class="font-mono font-medium">{{ entry.ip_address }}</p>
                <p class="text-xs text-surface-muted">
                  {{ entry.reason }} · {{ new Date(entry.blocked_at).toLocaleString() }}
                  <span v-if="entry.blocked_until"> · until {{ new Date(entry.blocked_until).toLocaleString() }}</span>
                </p>
                <p
                  v-if="entry.last_device_fingerprint"
                  class="mt-0.5 truncate font-mono text-[10px] text-surface-muted"
                  :title="entry.last_device_fingerprint"
                >
                  fp {{ entry.last_device_fingerprint.slice(0, 16) }}…
                </p>
              </div>
              <button type="button" class="btn ghost" @click="unlock(entry)">Unlock</button>
            </div>
          </div>
        </Card>
      </div>

      <Card title="Login activity" subtitle="Web dashboard, CLI clients, and SSH host logins — includes device fingerprints">
        <div class="max-h-80 overflow-auto rounded-lg border border-surface-border">
          <table class="w-full text-left text-xs">
            <thead class="sticky top-0 bg-surface-raised text-surface-muted">
              <tr>
                <th class="px-2 py-1.5">When</th>
                <th class="px-2 py-1.5">Source</th>
                <th class="px-2 py-1.5">IP</th>
                <th class="px-2 py-1.5">Event</th>
                <th class="px-2 py-1.5">Identity</th>
                <th class="px-2 py-1.5">Fingerprint</th>
                <th class="px-2 py-1.5">Agent</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in attempts" :key="row.id" class="border-t border-surface-border">
                <td class="whitespace-nowrap px-2 py-1.5">{{ new Date(row.attempted_at).toLocaleString() }}</td>
                <td class="px-2 py-1.5">
                  <Badge :variant="sourceBadge(row.source)" size="sm">{{ row.source || 'web' }}</Badge>
                </td>
                <td class="px-2 py-1.5 font-mono">{{ row.ip_address }}</td>
                <td class="px-2 py-1.5">
                  <Badge :variant="row.success ? 'success' : 'warning'" size="sm">{{ row.event_type }}</Badge>
                </td>
                <td class="px-2 py-1.5">{{ row.username_or_email || '—' }}</td>
                <td
                  class="max-w-[9rem] truncate px-2 py-1.5 font-mono text-[10px] text-surface-muted"
                  :title="row.device_fingerprint || ''"
                >
                  {{ row.device_fingerprint ? `${row.device_fingerprint.slice(0, 12)}…` : '—' }}
                </td>
                <td class="max-w-[12rem] truncate px-2 py-1.5 text-surface-muted">{{ row.user_agent || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <div class="grid gap-5 xl:grid-cols-2">
        <Card title="Action audit" subtitle="Mutating API calls from web or CLI">
          <div class="max-h-80 overflow-auto rounded-lg border border-surface-border">
            <table class="w-full text-left text-xs">
              <thead class="sticky top-0 bg-surface-raised text-surface-muted">
                <tr>
                  <th class="px-2 py-1.5">When</th>
                  <th class="px-2 py-1.5">Actor</th>
                  <th class="px-2 py-1.5">Source</th>
                  <th class="px-2 py-1.5">Action</th>
                  <th class="px-2 py-1.5">Status</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in actionLogs" :key="row.id" class="border-t border-surface-border">
                  <td class="whitespace-nowrap px-2 py-1.5">{{ new Date(row.occurred_at).toLocaleString() }}</td>
                  <td class="px-2 py-1.5">{{ row.actor_username || '—' }}</td>
                  <td class="px-2 py-1.5">
                    <Badge :variant="sourceBadge(row.source)" size="sm">{{ row.source }}</Badge>
                  </td>
                  <td class="px-2 py-1.5 font-mono">{{ row.action_key || row.summary }}</td>
                  <td class="px-2 py-1.5">{{ row.status_code }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Terminal CLI audit" subtitle="Commands run from the in-panel terminal">
          <p v-if="terminalAuditError" class="text-sm text-rose-400">{{ terminalAuditError }}</p>
          <div v-else-if="!terminalAudit.length" class="text-sm text-surface-muted">
            No terminal commands logged yet. Every command run from the panel terminal appears here.
          </div>
          <div v-else class="max-h-80 space-y-2 overflow-y-auto text-xs">
            <div
              v-for="entry in terminalAudit"
              :key="entry.id"
              class="rounded-lg border border-surface-border px-3 py-2"
            >
              <div class="flex flex-wrap items-center gap-2">
                <Badge :variant="entry.success ? 'success' : 'danger'" size="sm">
                  exit {{ entry.exit_code ?? '—' }}
                </Badge>
                <span class="font-mono text-[11px] text-surface-muted">{{ entry.username }}</span>
              </div>
              <p class="mt-1 font-mono text-[11px]">{{ entry.command }}</p>
              <p class="mt-1 text-surface-muted">{{ new Date(entry.executed_at).toLocaleString() }}</p>
            </div>
          </div>
        </Card>
      </div>

    </div>

    <ConfirmPasswordModal
      :open="clearModalOpen"
      title="Clear security logs"
      description="A JSON export downloads first. Enter your dashboard admin password to permanently delete login activity, action audit, and terminal audit from the database. SSH logins from before the clear stay hidden, and one audit row records that you cleared the logs."
      confirm-label="Clear security logs"
      :busy="clearBusy"
      :error="clearError"
      @cancel="clearModalOpen = false"
      @confirm="confirmClearLogs"
    />
  </DashboardLayout>
</template>

<style scoped>
.input {
  min-width: 10rem;
  flex: 1;
  border-radius: 0.65rem;
  border: 1px solid var(--color-border, rgb(148 163 184 / 0.35));
  background: transparent;
  padding: 0.45rem 0.65rem;
  font-size: 0.82rem;
}
.btn {
  border-radius: 0.65rem;
  border: 1px solid transparent;
  background: #0f766e;
  color: white;
  padding: 0.45rem 0.8rem;
  font-size: 0.8rem;
  font-weight: 600;
}
.btn.ghost {
  background: transparent;
  border-color: rgb(148 163 184 / 0.35);
  color: inherit;
}
.btn.danger {
  background: #dc2626;
}
</style>

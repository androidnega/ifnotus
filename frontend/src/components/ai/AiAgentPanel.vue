<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import Skeleton from '@/components/ui/Skeleton.vue'
import ConfirmPasswordModal from '@/components/databases/ConfirmPasswordModal.vue'
import { aiApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { renderAiMarkdown } from '@/lib/aiMarkdown'
import { readSseStream, streamAiApply, streamAiChat } from '@/lib/aiStream'
import type { AiPanelMessage, AiPendingAction, AiSessionSummary, AiSettings, AiToolTrace } from '@/types/ai'
import type { OperationResult } from '@/types/operations'

const props = withDefaults(
  defineProps<{
    surface: 'files' | 'terminal' | 'editor' | 'dashboard' | 'studio'
    path?: string
    appId?: string
    rootId?: string
    cwd?: string
    fileContent?: string
    originalContent?: string
    compact?: boolean
  }>(),
  { compact: false },
)

const emit = defineEmits<{
  applied: [action: AiPendingAction]
  undone: []
  liveWriteStart: [{ path: string }]
  liveWriteDelta: [{ path: string; content: string }]
  liveWriteDone: [{ path: string; success: boolean }]
}>()

/** One chat thread per surface + root/app jail — NOT per folder/file path. */
const SESSION_KEY = computed(() => {
  const scope = (props.rootId || props.appId || 'host')
    .replace(/[^a-zA-Z0-9._/-]+/g, '_')
    .slice(0, 120)
  return `ifnotus.ai.session.${props.surface}.${scope}`
})

const bootLoading = ref(true)
const status = ref<AiSettings | null>(null)
const messages = ref<AiPanelMessage[]>([])
const draft = ref('')
const sending = ref(false)
const applyingId = ref<string | null>(null)
const undoing = ref(false)
const canUndo = ref(false)
const error = ref<string | null>(null)
const liveStatus = ref<string | null>(null)
const scroller = ref<HTMLElement | null>(null)
const sessionId = ref<string | null>(null)
const sessions = ref<AiSessionSummary[]>([])
const showHistory = ref(false)
const dropConfirmOpen = ref(false)
const dropConfirmBusy = ref(false)
const dropConfirmError = ref<string | null>(null)
const pendingDropAction = ref<AiPendingAction | null>(null)

const configured = computed(() => !!status.value?.configured)
const agentName = computed(() => status.value?.agent_name?.trim() || 'SNR Dev')
const agentInitial = computed(() => agentName.value.charAt(0).toUpperCase() || 'S')
const sessionTitle = computed(() => {
  const hit = sessions.value.find((s) => s.id === sessionId.value)
  return hit?.title || 'New conversation'
})

function actionLabel(type: AiPendingAction['type']) {
  if (type === 'write_file') return 'Write file'
  if (type === 'write_files') return 'Write project files'
  if (type === 'mkdir') return 'Create directory'
  if (type === 'create_database') return 'Create database'
  if (type === 'drop_database') return 'Drop database'
  if (type === 'run_sql') return 'Run SQL'
  if (type === 'run_mongo') return 'Run Mongo script'
  if (type === 'terminal') return 'Run command'
  return type
}

function formatApplyResult(data: OperationResult): string {
  const details = (data.details || {}) as Record<string, unknown>
  const stdout = typeof details.stdout === 'string' ? details.stdout.trim() : ''
  const stderr = typeof details.stderr === 'string' ? details.stderr.trim() : ''
  const parts = [
    data.success
      ? `**Applied:** ${data.message}`
      : `**Could not apply:** ${data.message}`,
  ]
  if (stderr) parts.push(`\n**stderr**\n\`\`\`\n${stderr.slice(0, 2500)}\n\`\`\``)
  if (stdout && (!data.success || stdout.length < 800)) {
    parts.push(`\n**stdout**\n\`\`\`\n${stdout.slice(0, 1500)}\n\`\`\``)
  }
  if (data.success && details.can_undo) {
    parts.push('\nYou can **Undo** the last AI file write with the button below.')
  }
  return parts.join('\n')
}

async function loadStatus() {
  bootLoading.value = true
  error.value = null
  try {
    const { data } = await aiApi.status()
    status.value = data
    await refreshSessions()
    const saved = localStorage.getItem(SESSION_KEY.value)
    if (saved) {
      await openSession(saved, false)
    } else if (sessions.value[0]) {
      await openSession(sessions.value[0].id, false)
    }
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not load AI status')
  } finally {
    bootLoading.value = false
  }
}

async function refreshSessions() {
  try {
    // Do not filter by path — folder navigation must keep the same conversation list.
    const { data } = await aiApi.listSessions(props.surface)
    sessions.value = data.sessions || []
  } catch {
    sessions.value = []
  }
}

async function openSession(id: string, announce = true) {
  try {
    const { data } = await aiApi.getSession(id)
    sessionId.value = data.id
    localStorage.setItem(SESSION_KEY.value, data.id)
    messages.value = (data.messages || [])
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({
        id: m.id || crypto.randomUUID(),
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }))
    showHistory.value = false
    if (announce) {
      liveStatus.value = null
    }
    await scrollBottom()
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not open conversation')
    localStorage.removeItem(SESSION_KEY.value)
  }
}

async function startNewChat() {
  try {
    const { data } = await aiApi.createSession({
      surface: props.surface,
      title: 'New conversation',
      // Keep sessions surface-scoped; path is only chat context, not identity.
      appId: props.appId,
      rootId: props.rootId,
    })
    sessionId.value = data.id
    localStorage.setItem(SESSION_KEY.value, data.id)
    messages.value = []
    showHistory.value = false
    await refreshSessions()
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not start conversation')
  }
}

async function deleteCurrentSession() {
  if (!sessionId.value) return
  if (!confirm('Delete this conversation history?')) return
  try {
    await aiApi.deleteSession(sessionId.value)
    localStorage.removeItem(SESSION_KEY.value)
    sessionId.value = null
    messages.value = []
    await refreshSessions()
    if (sessions.value[0]) await openSession(sessions.value[0].id, false)
    showHistory.value = false
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not delete conversation')
  }
}

async function clearAllSessions() {
  if (!confirm('Delete ALL conversation history for this panel? This cannot be undone.')) return
  try {
    await aiApi.clearSessions(props.surface)
    localStorage.removeItem(SESSION_KEY.value)
    sessionId.value = null
    messages.value = []
    sessions.value = []
    showHistory.value = false
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not clear history (admin may be required)')
  }
}

async function scrollBottom() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

async function send(textOverride?: string) {
  const text = (textOverride ?? draft.value).trim()
  if (!text || sending.value) return
  draft.value = ''
  error.value = null
  liveStatus.value = 'Adding neckpreser…'
  const userMsg: AiPanelMessage = {
    id: crypto.randomUUID(),
    role: 'user',
    content: text,
  }
  messages.value.push(userMsg)
  const assistantId = crypto.randomUUID()
  messages.value.push({
    id: assistantId,
    role: 'assistant',
    content: '',
    pending: [],
    traces: [],
  })
  sending.value = true
  await scrollBottom()

  try {
    const hist = messages.value
      .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.id !== assistantId && m.content)
      .slice(0, -1)
      .map((m) => ({ role: m.role, content: m.content }))

    const response = await streamAiChat({
      message: text,
      history: hist,
      surface: props.surface,
      path: props.path,
      app_id: props.appId,
      root_id: props.rootId,
      cwd: props.cwd,
      session_id: sessionId.value,
      file_content: props.fileContent,
      original_content: props.originalContent,
    })

    let pending: AiPendingAction[] = []
    let traces: AiToolTrace[] = []
    let configuredFlag = configured.value

    for await (const event of readSseStream(response)) {
      if (event.type === 'session' && event.session_id) {
        sessionId.value = event.session_id
        localStorage.setItem(SESSION_KEY.value, event.session_id)
      } else if (event.type === 'status' && event.text) {
        liveStatus.value = event.text
      } else if (event.type === 'tool' && event.text) {
        liveStatus.value = event.text
      } else if (event.type === 'delta' && event.text) {
        const msg = messages.value.find((m) => m.id === assistantId)
        if (msg) msg.content += event.text
        await scrollBottom()
      } else if (event.type === 'error') {
        error.value = event.message || 'AI stream error'
      } else if (event.type === 'done') {
        configuredFlag = event.configured ?? true
        pending = event.pending_actions || []
        traces = event.tool_traces || []
        if (event.session_id) {
          sessionId.value = event.session_id
          localStorage.setItem(SESSION_KEY.value, event.session_id)
        }
      }
    }

    status.value = {
      configured: configuredFlag,
      model: status.value?.model || 'deepseek-chat',
      base_url: status.value?.base_url || '',
      api_key_masked: status.value?.api_key_masked ?? null,
      updated_at: status.value?.updated_at ?? null,
    }
    const msg = messages.value.find((m) => m.id === assistantId)
    if (msg) {
      if (!msg.content.trim()) msg.content = pending.length ? '**Snr Dev — should I proceed?**' : 'Done.'
      msg.pending = pending
      msg.traces = traces
    }
    await refreshSessions()
  } catch (e) {
    error.value = getApiErrorMessage(e, 'AI request failed')
    const msg = messages.value.find((m) => m.id === assistantId)
    if (msg && !msg.content) {
      msg.content = 'Sorry — I could not complete that request.'
    }
  } finally {
    sending.value = false
    liveStatus.value = null
    await scrollBottom()
  }
}

async function applyAction(action: AiPendingAction) {
  if (action.type === 'drop_database') {
    pendingDropAction.value = action
    dropConfirmError.value = null
    dropConfirmOpen.value = true
    return
  }

  const ok = confirm(
    action.critical
      ? `Critical · Snr Dev — should I proceed?\n\n${action.reason}\n\n${action.path || action.command || ''}`
      : `Snr Dev — should I proceed?\n\n${action.reason}\n\n${action.path || action.command || ''}`,
  )
  if (!ok) return
  await executeApply(action)
}

async function confirmDropApply(password: string) {
  if (!pendingDropAction.value) return
  dropConfirmBusy.value = true
  dropConfirmError.value = null
  try {
    await executeApply(pendingDropAction.value, password)
    dropConfirmOpen.value = false
    pendingDropAction.value = null
  } catch (e) {
    dropConfirmError.value = getApiErrorMessage(e, 'Drop failed')
  } finally {
    dropConfirmBusy.value = false
  }
}

async function executeApply(action: AiPendingAction, confirmPassword?: string) {
  applyingId.value = action.id
  error.value = null
  liveStatus.value =
    action.type === 'write_file' || action.type === 'write_files' || action.type === 'mkdir'
      ? 'Snr Dev is writing live…'
      : 'Consulting Snr Dev…'
  try {
    const response = await streamAiApply(action.token, confirmPassword)
    let result: OperationResult = { success: false, message: 'No result', details: {} }

    for await (const event of readSseStream(response)) {
      if (event.type === 'status' && event.text) {
        liveStatus.value = event.text
      } else if (event.type === 'write_start' && event.path) {
        emit('liveWriteStart', { path: event.path })
      } else if (event.type === 'write_delta' && event.path && typeof event.content === 'string') {
        emit('liveWriteDelta', { path: event.path, content: event.content })
      } else if (event.type === 'write_done' && event.path) {
        emit('liveWriteDone', { path: event.path, success: !!event.success })
      } else if (event.type === 'done') {
        result = {
          success: !!event.success,
          message: event.message || (event.success ? 'Applied' : 'Failed'),
          details: event.details || {},
        }
      } else if (event.type === 'error') {
        error.value = event.message || 'Apply failed'
      }
    }

    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: formatApplyResult(result),
    })
    messages.value = messages.value.map((m) => ({
      ...m,
      pending: m.pending?.filter((p) => p.id !== action.id),
    }))
    if (result.success) {
      emit('applied', action)
      if ((action.type === 'write_file' || action.type === 'write_files') && result.details?.can_undo) {
        canUndo.value = true
      }
    } else if (action.type === 'drop_database' && !result.success) {
      throw new Error(result.message || 'Drop failed')
    }
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Failed to apply AI action')
    if (action.type === 'drop_database') throw e
  } finally {
    applyingId.value = null
    liveStatus.value = null
    await scrollBottom()
  }
}

async function undoLast() {
  undoing.value = true
  error.value = null
  try {
    const { data } = await aiApi.undoAction()
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: data.success ? `**Undone:** ${data.message}` : `**Undo failed:** ${data.message}`,
    })
    if (data.success) {
      canUndo.value = false
      emit('undone')
    }
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Failed to undo')
  } finally {
    undoing.value = false
    await scrollBottom()
  }
}

function dismissAction(action: AiPendingAction) {
  messages.value = messages.value.map((m) => ({
    ...m,
    pending: m.pending?.filter((p) => p.id !== action.id),
  }))
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault()
    send()
  }
}

// Only reset the thread when the jail/surface changes — not when browsing folders/files.
watch(
  () => [props.surface, props.rootId, props.appId] as const,
  async () => {
    sessionId.value = null
    messages.value = []
    await refreshSessions()
    const saved = localStorage.getItem(SESSION_KEY.value)
    if (saved && sessions.value.some((s) => s.id === saved)) {
      await openSession(saved, false)
    } else if (sessions.value[0]) {
      await openSession(sessions.value[0].id, false)
    }
  },
)

onMounted(loadStatus)
</script>

<template>
  <aside class="ai-panel" :class="{ 'is-compact': compact }">
    <header class="ai-header">
      <div class="ai-brand">
        <span class="ai-brand-mark">{{ agentInitial }}</span>
        <div class="min-w-0">
          <p class="ai-brand-name">{{ agentName }}</p>
          <p class="ai-context">
            {{ sessionTitle }}
            <span v-if="path"> · {{ path }}</span>
          </p>
        </div>
      </div>
      <div class="ai-header-actions">
        <button type="button" class="ai-btn" title="History" @click="showHistory = !showHistory">
          History
        </button>
        <button type="button" class="ai-btn" title="New conversation" @click="startNewChat">
          New
        </button>
        <button
          v-if="canUndo"
          type="button"
          class="ai-btn"
          :disabled="undoing"
          title="Undo last AI file write"
          @click="undoLast"
        >
          {{ undoing ? '…' : 'Undo' }}
        </button>
        <span
          class="ai-pill"
          :class="configured ? 'is-on' : 'is-off'"
        >
          {{ configured ? 'Ready' : 'Setup' }}
        </span>
      </div>
    </header>

    <div v-if="showHistory" class="ai-history">
      <div class="flex items-center justify-between gap-2 px-1">
        <p class="text-[10px] font-semibold uppercase tracking-wide text-surface-muted">Conversations</p>
        <button type="button" class="ai-btn !py-0.5 !text-[10px]" @click="clearAllSessions">Clear all</button>
      </div>
      <button
        v-for="s in sessions"
        :key="s.id"
        type="button"
        class="ai-history-item"
        :class="{ 'is-active': s.id === sessionId }"
        @click="openSession(s.id)"
      >
        <span class="truncate font-medium">{{ s.title }}</span>
        <span class="text-[10px] text-surface-muted">{{ s.message_count }} msgs</span>
      </button>
      <p v-if="!sessions.length" class="px-1 text-xs text-surface-muted">No saved conversations yet.</p>
      <button
        v-if="sessionId"
        type="button"
        class="ai-btn !text-[10px] text-red-600"
        @click="deleteCurrentSession"
      >
        Delete current
      </button>
    </div>

    <div v-if="bootLoading" class="space-y-3 p-3">
      <Skeleton height="0.75rem" width="40%" />
      <Skeleton height="4rem" />
      <Skeleton height="4rem" />
      <Skeleton height="2.5rem" />
    </div>

    <template v-else>
      <div v-if="!configured" class="ai-setup">
        <p class="text-sm text-slate-700 dark:text-slate-200">
          Add your API key in Settings to unlock {{ agentName }}.
        </p>
        <RouterLink to="/settings" class="ai-link">Open Settings</RouterLink>
      </div>

      <div ref="scroller" class="ai-messages">
        <div v-if="!messages.length" class="ai-empty">
          <p>Ask what’s broken, what a file does, or how to fix a path.</p>
          <div class="ai-suggestions">
            <button
              v-if="surface === 'dashboard'"
              type="button"
              @click="send('Give me a clean overview of how this server is doing right now — health, resources, alerts, and apps.')"
            >
              Server overview
            </button>
            <button
              v-else-if="surface === 'editor'"
              type="button"
              @click="send('Review the open file and my unsaved changes. Summarize what changed and any issues.')"
            >
              Review my changes
            </button>
            <button
              v-else-if="surface === 'studio'"
              type="button"
              @click="send('Review the selected table or collection. Summarize its structure, data quality risks, and useful queries.')"
            >
              Review this data
            </button>
            <button
              v-else
              type="button"
              @click="send('Scan this directory and summarize what this project is.')"
            >
              Summarize this project
            </button>
            <button
              v-if="surface === 'studio'"
              type="button"
              @click="send('Suggest a safe query to inspect unusual, duplicate, or incomplete rows in this data.')"
            >
              Find data issues
            </button>
            <button
              v-else-if="surface !== 'dashboard'"
              type="button"
              @click="send('Find likely configuration or runtime issues in the current path. Use probe_site_http if a domain is involved, then read config/.env and propose a real fix.')"
            >
              Find issues here
            </button>
            <button
              v-if="surface === 'dashboard'"
              type="button"
              @click="send('What should I worry about first on this VPS?')"
            >
              What needs attention?
            </button>
          </div>
        </div>

        <div
          v-for="msg in messages"
          :key="msg.id"
          class="ai-bubble"
          :class="msg.role === 'user' ? 'is-user' : 'is-assistant'"
        >
          <div
            v-if="msg.role === 'assistant'"
            class="ai-md text-sm leading-relaxed"
            v-html="renderAiMarkdown(msg.content || (sending && msg === messages[messages.length - 1] ? '…' : ''))"
          />
          <p v-else class="whitespace-pre-wrap text-sm leading-relaxed">{{ msg.content }}</p>

          <div v-if="msg.traces?.length" class="ai-traces">
            <details>
              <summary>Inspected {{ msg.traces.length }} tool{{ msg.traces.length === 1 ? '' : 's' }}</summary>
              <ul>
                <li v-for="(t, idx) in msg.traces" :key="idx">
                  <code>{{ t.name }}</code>
                  <span>{{ t.result_preview }}</span>
                </li>
              </ul>
            </details>
          </div>

          <div
            v-for="action in msg.pending || []"
            :key="action.id"
            class="ai-action"
            :class="{ 'is-critical': action.critical }"
          >
            <p class="text-xs font-semibold" :class="action.critical ? 'text-red-700 dark:text-red-300' : 'text-amber-800 dark:text-amber-200'">
              Snr Dev — should I proceed?
              <span class="font-normal opacity-80"> · {{ actionLabel(action.type) }}</span>
            </p>
            <p class="mt-1 text-xs text-surface-muted">{{ action.reason }}</p>
            <p v-if="action.path" class="mt-1 font-mono text-[11px]">{{ action.path }}</p>
            <p v-if="action.command" class="mt-1 font-mono text-[11px]">{{ action.command }}</p>
            <pre v-if="action.preview" class="ai-preview">{{ action.preview }}</pre>
            <div class="mt-2 flex gap-2">
              <button
                type="button"
                class="ai-btn-primary"
                :disabled="applyingId === action.id"
                @click="applyAction(action)"
              >
                {{ applyingId === action.id ? 'Writing…' : 'Proceed' }}
              </button>
              <button type="button" class="ai-btn" @click="dismissAction(action)">Deny</button>
            </div>
          </div>
        </div>

        <div v-if="sending || applyingId" class="ai-status-live">
          <span class="ai-status-dot" />
          <span>{{ liveStatus || 'Adding neckpreser…' }}</span>
        </div>
      </div>

      <p v-if="error" class="px-3 pb-1 text-xs text-red-600 dark:text-red-300">{{ error }}</p>

      <footer class="ai-composer">
        <textarea
          v-model="draft"
          rows="2"
          class="ai-input"
          :disabled="sending"
          :placeholder="configured ? `Ask ${agentName}…` : `Configure ${agentName} in Settings first`"
          @keydown="onKeydown"
        />
        <button
          type="button"
          class="ai-btn-primary"
          :disabled="sending || !draft.trim() || !configured"
          @click="() => send()"
        >
          {{ sending ? '…' : 'Send' }}
        </button>
      </footer>
    </template>

    <ConfirmPasswordModal
      :open="dropConfirmOpen"
      title="Drop database"
      description="AI wants to drop a database. Confirm you are sure and enter your dashboard admin password."
      :busy="dropConfirmBusy"
      :error="dropConfirmError"
      confirm-label="Drop database"
      @cancel="dropConfirmOpen = false; pendingDropAction = null; dropConfirmError = null"
      @confirm="confirmDropApply"
    />
  </aside>
</template>

<style scoped>
.ai-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  background:
    radial-gradient(28rem 12rem at 100% 0%, rgb(45 212 191 / 0.09), transparent 68%),
    var(--color-surface-raised);
  box-shadow: 0 10px 30px rgb(15 23 42 / 0.06);
}
.ai-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-surface-raised) 94%, rgb(15 118 110) 6%);
  padding: 0.72rem 0.8rem;
}
.ai-brand {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.6rem;
}
.ai-brand-mark {
  display: grid;
  width: 1.8rem;
  height: 1.8rem;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 0.55rem;
  background: linear-gradient(145deg, #0f766e, #0d9488);
  color: white;
  font-size: 0.72rem;
  font-weight: 800;
  box-shadow: 0 5px 12px rgb(15 118 110 / 0.22);
}
.ai-brand-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #0f766e;
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.dark .ai-brand-name {
  color: #5eead4;
}
.ai-context {
  max-width: 15rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
  font-size: 0.66rem;
}
.ai-header-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: 0.35rem;
}
.ai-panel.is-compact .ai-header {
  align-items: flex-start;
  flex-direction: column;
}
.ai-panel.is-compact .ai-header-actions {
  width: 100%;
  justify-content: flex-start;
}
.ai-panel.is-compact .ai-context {
  max-width: 21rem;
}
.ai-history {
  display: grid;
  gap: 0.35rem;
  border-bottom: 1px solid var(--color-border);
  background: rgb(15 118 110 / 0.04);
  padding: 0.55rem 0.65rem;
  max-height: 11rem;
  overflow: auto;
}
.ai-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
  padding: 0.35rem 0.5rem;
  text-align: left;
  font-size: 0.75rem;
}
.ai-history-item:hover { background: rgb(148 163 184 / 0.12); }
.ai-history-item.is-active {
  border-color: rgb(15 118 110 / 0.35);
  background: rgb(15 118 110 / 0.1);
}
.ai-pill {
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.ai-pill.is-on {
  background: rgb(16 185 129 / 0.14);
  color: #059669;
}
.ai-pill.is-off {
  background: rgb(245 158 11 / 0.14);
  color: #d97706;
}
.ai-setup {
  display: grid;
  gap: 0.75rem;
  padding: 1rem;
}
.ai-link {
  display: inline-flex;
  width: fit-content;
  border-radius: 0.625rem;
  background: #0f766e;
  padding: 0.45rem 0.8rem;
  font-size: 0.8rem;
  font-weight: 500;
  color: white;
}
.ai-messages {
  flex: 1;
  min-height: 12rem;
  max-height: min(52vh, 28rem);
  min-width: 0;
  overflow: auto;
  overflow-x: hidden;
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  scrollbar-width: thin;
}
.ai-empty {
  margin: auto 0;
  color: var(--color-text-muted);
  font-size: 0.85rem;
  text-align: center;
  padding: 1rem 0.5rem;
}
.ai-suggestions {
  margin-top: 0.75rem;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.4rem;
}
.ai-suggestions button {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.3rem 0.7rem;
  font-size: 0.7rem;
  color: inherit;
}
.ai-suggestions button:hover {
  background: rgb(148 163 184 / 0.12);
}
.ai-bubble {
  box-sizing: border-box;
  max-width: min(100%, 36rem);
  min-width: 0;
  border: 1px solid transparent;
  border-radius: 0.9rem;
  padding: 0.7rem 0.8rem;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.ai-bubble.is-user {
  max-width: min(100%, 30rem);
  align-self: flex-end;
  background: rgb(15 118 110 / 0.12);
  border-color: rgb(15 118 110 / 0.12);
  color: inherit;
}
.ai-bubble.is-assistant {
  align-self: flex-start;
  border-color: var(--color-border);
  background: color-mix(in srgb, var(--color-surface-raised) 90%, rgb(148 163 184) 10%);
}
.ai-status-live {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  border-radius: 999px;
  background: rgb(15 118 110 / 0.1);
  padding: 0.35rem 0.75rem;
  font-size: 0.72rem;
  font-weight: 500;
  color: #0f766e;
}
.dark .ai-status-live { color: #5eead4; }
.ai-status-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.85;
}
.ai-md :deep(.ai-md-p) {
  margin: 0 0 0.55rem;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.55;
}
.ai-md :deep(a) {
  overflow-wrap: anywhere;
  word-break: break-word;
}
.ai-md :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
.ai-md :deep(th),
.ai-md :deep(td) {
  overflow-wrap: anywhere;
  word-break: break-word;
}
.ai-md :deep(.ai-md-p:last-child) {
  margin-bottom: 0;
}
.ai-md :deep(.ai-md-h) {
  margin: 0.55rem 0 0.35rem;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.ai-md :deep(h1.ai-md-h) { font-size: 1.05rem; }
.ai-md :deep(h2.ai-md-h) { font-size: 0.95rem; }
.ai-md :deep(h3.ai-md-h) { font-size: 0.88rem; }
.ai-md :deep(.ai-md-code) {
  border-radius: 0.3rem;
  background: rgb(15 23 42 / 0.08);
  padding: 0.05rem 0.3rem;
  font-size: 0.78em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  overflow-wrap: anywhere;
}
.dark .ai-md :deep(.ai-md-code) {
  background: rgb(226 232 240 / 0.1);
}
.ai-md :deep(.ai-md-mark) {
  background: rgb(250 204 21 / 0.45);
  color: inherit;
  border-radius: 0.2rem;
  padding: 0 0.15rem;
}
.ai-md :deep(.ai-md-pre) {
  margin: 0.45rem 0;
  max-height: 12rem;
  overflow: auto;
  border-radius: 0.5rem;
  background: rgb(15 23 42 / 0.92);
  padding: 0.55rem 0.65rem;
  font-size: 0.68rem;
  line-height: 1.45;
  color: #e2e8f0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.ai-md :deep(.ai-md-list) {
  margin: 0.35rem 0 0.55rem 1.1rem;
  list-style: disc;
  overflow-wrap: anywhere;
}
.ai-md :deep(.ai-md-list li) {
  margin: 0.15rem 0;
  line-height: 1.45;
}
.ai-bubble.is-assistant {
  max-width: 100%;
}
.ai-traces {
  margin-top: 0.5rem;
  font-size: 0.7rem;
  color: var(--color-text-muted);
}
.ai-traces ul {
  margin-top: 0.35rem;
  display: grid;
  gap: 0.35rem;
}
.ai-traces li {
  display: grid;
  gap: 0.15rem;
}
.ai-traces code {
  font-weight: 600;
}
.ai-action {
  margin-top: 0.65rem;
  border: 1px solid rgb(245 158 11 / 0.35);
  border-radius: 0.75rem;
  background: rgb(245 158 11 / 0.08);
  padding: 0.65rem;
}
.ai-action.is-critical {
  border-color: rgb(220 38 38 / 0.45);
  background: rgb(220 38 38 / 0.08);
}
.ai-preview {
  margin-top: 0.45rem;
  max-height: 8rem;
  overflow: auto;
  border-radius: 0.5rem;
  background: rgb(15 23 42 / 0.92);
  padding: 0.5rem;
  font-size: 0.65rem;
  color: #e2e8f0;
  white-space: pre-wrap;
}
.ai-composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.5rem;
  border-top: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-surface-raised) 96%, rgb(15 118 110) 4%);
  padding: 0.75rem;
}
.ai-input {
  width: 100%;
  resize: none;
  border: 1px solid var(--color-border);
  border-radius: 0.72rem;
  background: var(--color-surface-raised);
  padding: 0.62rem 0.72rem;
  font-size: 0.8rem;
}
.ai-input:focus {
  border-color: rgb(15 118 110 / 0.48);
  outline: 3px solid rgb(15 118 110 / 0.09);
}
.ai-btn,
.ai-btn-primary {
  border-radius: 0.58rem;
  border: 1px solid var(--color-border);
  padding: 0.4rem 0.65rem;
  font-size: 0.68rem;
  font-weight: 650;
}
.ai-btn-primary {
  border-color: transparent;
  background: #0f766e;
  color: white;
}
.ai-btn-primary:disabled {
  opacity: 0.5;
}
.ai-btn:hover {
  background: rgb(148 163 184 / 0.12);
}
</style>

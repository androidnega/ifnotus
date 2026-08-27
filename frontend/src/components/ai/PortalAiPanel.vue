<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { renderAiMarkdown } from '@/lib/aiMarkdown'
import { readSseStream, streamAiApply, streamAiChat } from '@/lib/aiStream'
import type { AiPanelMessage, AiPendingAction, AiSessionSummary, AiToolTrace } from '@/types/ai'

const props = withDefaults(
  defineProps<{
    environmentId: string
    domain?: string | null
    path?: string | null
    /** Working directory when browsing the file manager (no file open). */
    cwd?: string | null
    /** Selected file/folder names for FM context. */
    selectedNames?: string[]
    /** Installed stack label if known (e.g. WordPress). */
    stackHint?: string | null
    /** Plan / storage summary for the agent. */
    limitsHint?: string | null
    fileContent?: string | null
    originalContent?: string | null
    colorMode?: 'light' | 'dark'
    canUndo?: boolean
    /** files = file manager chrome; portal = editor companion */
    mode?: 'portal' | 'files'
  }>(),
  {
    path: null,
    cwd: null,
    selectedNames: () => [],
    stackHint: null,
    limitsHint: null,
    fileContent: null,
    originalContent: null,
    colorMode: 'light',
    canUndo: false,
    mode: 'portal',
  },
)

const emit = defineEmits<{
  creditsChanged: []
  hide: []
  openPath: [path: string]
  liveWriteStart: [payload: { path: string }]
  liveWriteDelta: [payload: { path: string; content: string }]
  liveWriteDone: [payload: { path: string; success: boolean; persisted?: boolean }]
  undoAi: []
}>()

const SESSION_KEY = computed(() => `ifnotus.portal.ai.session.${props.environmentId}`)

const bootLoading = ref(true)
const configured = ref(false)
const credits = ref<number | null>(null)
const tokensRemaining = ref<number | null>(null)
const tokensPerCredit = ref(12_000)
const lastCharge = ref<{ credits: number; tokens: number } | null>(null)
const messages = ref<AiPanelMessage[]>([])
const draft = ref('')
const sending = ref(false)
const applyingId = ref<string | null>(null)
const undoing = ref(false)
const error = ref<string | null>(null)
const liveStatus = ref<string | null>(null)
const writingLive = ref(false)
const scroller = ref<HTMLElement | null>(null)
const sessionId = ref<string | null>(null)
const sessions = ref<AiSessionSummary[]>([])
const showHistory = ref(false)

const chatPath = computed(() => `/customers/environments/${props.environmentId}/ai/chat/stream`)
const applyPath = computed(() => `/customers/environments/${props.environmentId}/ai/actions/apply/stream`)
const isDark = computed(() => props.colorMode === 'dark')
const tokensLabel = computed(() => {
  if (tokensRemaining.value == null) return null
  return formatTokens(tokensRemaining.value)
})
const showTyping = computed(
  () => sending.value && !!messages.value.length && !messages.value[messages.value.length - 1]?.content,
)
const sessionTitle = computed(() => {
  const hit = sessions.value.find((s) => s.id === sessionId.value)
  return hit?.title || 'Current chat'
})

function clippedBuffer(value: string | null | undefined, max = 24_000) {
  if (!value) return undefined
  if (value.length <= max) return value
  return `${value.slice(0, max)}\n\n/* …truncated for chat context… */`
}

function formatTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1000)}k`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function buildContextPrefix() {
  const lines: string[] = []
  if (props.domain) lines.push(`Site: ${props.domain}`)
  if (props.cwd) lines.push(`Working directory: ${props.cwd}`)
  if (props.path) lines.push(`Focused path: ${props.path}`)
  if (props.selectedNames?.length) {
    lines.push(`Selected: ${props.selectedNames.slice(0, 12).join(', ')}`)
  }
  if (props.stackHint) lines.push(`Installed stack: ${props.stackHint}`)
  if (props.limitsHint) lines.push(`Limits: ${props.limitsHint}`)
  if (!lines.length) return ''
  return `[File Manager context — do not bypass tenant permissions; never expose secrets; confirm before destructive actions]\n${lines.join('\n')}\n\n`
}

const quickPrompts = computed(() => {
  if (props.mode !== 'files') return [] as Array<{ label: string; text: string }>
  const focus = props.path || props.selectedNames?.[0] || props.cwd || '.'
  return [
    { label: 'Explain structure', text: `Explain the project structure under ${props.cwd || '.'}. Identify the entry point.` },
    { label: 'Explain selected', text: `Explain what ${focus} is for and how it fits the site.` },
    {
      label: 'Fix live error',
      text:
        'Open the live site, read the exact error, inspect config.php / .env / wp-config.php, ' +
        'and propose a real fix (credentials, missing tables, wrong SITE_URL). Use tools — do not guess.',
    },
    { label: 'Find errors', text: `Review ${focus} for likely errors or misconfiguration. Read the files first.` },
    { label: 'Suggest fix', text: `Suggest a safe fix for issues in ${focus}. Do not apply destructive changes without confirmation.` },
    { label: 'Help deploy', text: `Help me deploy or go live with this site. Current stack: ${props.stackHint || 'unknown'}.` },
  ]
})

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function sleep(ms: number) {
  return new Promise((r) => window.setTimeout(r, ms))
}

/** Slow, readable live overwrite so syntax highlight progress is visible. */
async function paintLiveContent(path: string, full: string) {
  emit('liveWriteStart', { path })
  if (!full) {
    emit('liveWriteDelta', { path, content: '' })
    return
  }
  const lines = full.split('\n')
  // Short files: small character steps. Longer: line-by-line for a clean typing feel.
  if (full.length < 500) {
    const step = Math.max(6, Math.min(18, Math.floor(full.length / 80) || 6))
    for (let i = 0; i < full.length; i += step) {
      emit('liveWriteDelta', { path, content: full.slice(0, Math.min(i + step, full.length)) })
      await sleep(32)
    }
  } else {
    let built = ''
    for (let i = 0; i < lines.length; i++) {
      built += (i ? '\n' : '') + lines[i]
      emit('liveWriteDelta', { path, content: built })
      await sleep(Math.min(70, 26 + Math.floor(lines[i].length / 6)))
    }
  }
  emit('liveWriteDelta', { path, content: full })
}

async function scrollBottom() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

async function refreshSessions() {
  try {
    const { data } = await customersApi.listEnvAiSessions(props.environmentId, 'portal')
    sessions.value = data.sessions || []
  } catch {
    sessions.value = []
  }
}

async function openSession(id: string) {
  try {
    const { data } = await customersApi.getEnvAiSession(props.environmentId, id)
    sessionId.value = data.id
    localStorage.setItem(SESSION_KEY.value, data.id)
    messages.value = (data.messages || [])
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({
        id: m.id || newId(),
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }))
    showHistory.value = false
    await scrollBottom()
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not open conversation.')
    localStorage.removeItem(SESSION_KEY.value)
  }
}

async function startNewChat() {
  try {
    const { data } = await customersApi.createEnvAiSession(props.environmentId, {
      surface: 'portal',
      title: 'New conversation',
      // Session is per environment — not per folder/file.
      path: null,
    })
    sessionId.value = data.id
    localStorage.setItem(SESSION_KEY.value, data.id)
    messages.value = []
    showHistory.value = false
    await refreshSessions()
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not start conversation.')
  }
}

async function deleteCurrentSession() {
  if (!sessionId.value) return
  if (!confirm('Delete this conversation? The previous chat will open if one remains.')) return
  try {
    await customersApi.deleteEnvAiSession(props.environmentId, sessionId.value)
    localStorage.removeItem(SESSION_KEY.value)
    sessionId.value = null
    messages.value = []
    await refreshSessions()
    if (sessions.value[0]) await openSession(sessions.value[0].id)
    showHistory.value = false
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not delete conversation.')
  }
}

async function loadStatus() {
  bootLoading.value = true
  error.value = null
  try {
    const { data } = await customersApi.envAiStatus(props.environmentId)
    configured.value = !!data.configured
    credits.value = data.credits_remaining
    tokensPerCredit.value = data.tokens_per_credit || 12_000
    tokensRemaining.value =
      data.tokens_remaining ??
      (typeof data.credits_remaining === 'number'
        ? data.credits_remaining * tokensPerCredit.value
        : null)
    await refreshSessions()
    const saved = localStorage.getItem(SESSION_KEY.value)
    if (saved && sessions.value.some((s) => s.id === saved)) {
      await openSession(saved)
    } else if (sessions.value[0]) {
      await openSession(sessions.value[0].id)
    }
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not load AI status.')
    configured.value = false
  } finally {
    bootLoading.value = false
  }
}

watch(
  () => props.environmentId,
  () => {
    messages.value = []
    sessionId.value = null
    lastCharge.value = null
    showHistory.value = false
    void loadStatus()
  },
  { immediate: true },
)

onMounted(() => {
  /* loadStatus runs via watch immediate */
})

function onComposerKeydown(ev: KeyboardEvent) {
  if (ev.key !== 'Enter') return
  if (ev.shiftKey) return
  ev.preventDefault()
  void send()
}

function onThreadClick(ev: MouseEvent) {
  const t = ev.target as HTMLElement | null
  const btn = t?.closest?.('[data-ai-path]') as HTMLElement | null
  if (!btn) return
  const path = btn.getAttribute('data-ai-path')
  if (path) emit('openPath', path)
}

async function send(textOverride?: string) {
  const raw = (textOverride ?? draft.value).trim()
  if (!raw || sending.value) return
  const text = `${buildContextPrefix()}${raw}`
  sending.value = true
  error.value = null
  liveStatus.value = 'Thinking…'
  lastCharge.value = null
  messages.value.push({ id: newId(), role: 'user', content: raw })
  draft.value = ''
  const assistant: AiPanelMessage = {
    id: newId(),
    role: 'assistant',
    content: '',
    pending: [],
    traces: [],
  }
  messages.value.push(assistant)
  await scrollBottom()

  const history = messages.value
    .slice(0, -1)
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .slice(-24)
    .map((m) => ({ role: m.role, content: m.content.slice(0, 4000) }))

  try {
    const response = await streamAiChat(
      {
        message: text,
        history,
        surface: 'portal',
        path: props.path || props.cwd || undefined,
        session_id: sessionId.value || undefined,
        file_content: clippedBuffer(props.fileContent),
        original_content: clippedBuffer(props.originalContent),
      },
      { path: chatPath.value },
    )
    for await (const event of readSseStream(response)) {
      if (event.type === 'session' && event.session_id) {
        sessionId.value = event.session_id
        localStorage.setItem(SESSION_KEY.value, event.session_id)
      } else if (event.type === 'status' && event.text) {
        liveStatus.value = event.text
      } else if (event.type === 'tool' && event.text) {
        liveStatus.value = event.text
      } else if (event.type === 'delta' && event.text) {
        assistant.content += event.text
        liveStatus.value = null
        await scrollBottom()
      } else if (event.type === 'done') {
        if (event.pending_actions) assistant.pending = event.pending_actions as AiPendingAction[]
        if (event.tool_traces) assistant.traces = event.tool_traces as AiToolTrace[]
        if (event.configured === false) configured.value = false
        if (event.session_id) {
          sessionId.value = event.session_id
          localStorage.setItem(SESSION_KEY.value, event.session_id)
        }
        if (typeof event.credits_remaining === 'number') credits.value = event.credits_remaining
        if (typeof event.tokens_remaining === 'number') tokensRemaining.value = event.tokens_remaining
        if (typeof event.credits_charged === 'number') {
          lastCharge.value = {
            credits: event.credits_charged,
            tokens: Number(event.usage?.weighted_tokens || event.usage?.total_tokens || 0),
          }
        }
        liveStatus.value = null
        await refreshSessions()
      } else if (event.type === 'error') {
        error.value = event.message || 'AI stream failed'
        liveStatus.value = null
      }
    }
    emit('creditsChanged')
    try {
      const { data } = await customersApi.envAiStatus(props.environmentId)
      credits.value = data.credits_remaining
      tokensRemaining.value =
        data.tokens_remaining ??
        (typeof data.credits_remaining === 'number'
          ? data.credits_remaining * tokensPerCredit.value
          : tokensRemaining.value)
    } catch {
      /* ignore */
    }
    await refreshSessions()
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Chat failed.')
    liveStatus.value = null
  } finally {
    sending.value = false
    await scrollBottom()
  }
}

function applyTextPatches(
  base: string,
  edits: Array<{ old_text: string; new_text: string }>,
): string {
  let text = base
  for (let i = 0; i < edits.length; i++) {
    const oldText = edits[i]?.old_text ?? ''
    const newText = edits[i]?.new_text ?? ''
    if (!oldText) throw new Error(`Patch ${i + 1}: missing the text to replace.`)
    const first = text.indexOf(oldText)
    if (first < 0) {
      throw new Error(`Patch ${i + 1}: target text not found in the open file (it may have changed).`)
    }
    if (text.indexOf(oldText, first + 1) >= 0) {
      throw new Error(`Patch ${i + 1}: target text matched more than once.`)
    }
    text = text.slice(0, first) + newText + text.slice(first + oldText.length)
  }
  return text
}

async function applyAction(action: AiPendingAction) {
  applyingId.value = action.id
  error.value = null
  const isWrite = action.type === 'write_file' || action.type === 'write_files'
  writingLive.value = isWrite
  liveStatus.value = isWrite ? 'AI pair programming…' : 'Applying…'
  let paintedLocally = false
  let paintPath = action.path || props.path || 'file'

  // Surgical patch or full buffer update — never write disk until Save.
  if (action.type === 'write_file') {
    paintPath = action.path || props.path || 'file'
    writingLive.value = true
    emit('liveWriteStart', { path: paintPath })
    if (paintPath && paintPath !== props.path) emit('openPath', paintPath)
    await nextTick()

    let nextContent: string | null = null
    const isPatch = !!(action.patch || action.edits?.length)
    if (action.edits?.length) {
      try {
        nextContent = applyTextPatches(props.fileContent ?? '', action.edits)
      } catch (e) {
        // Fall back to server-merged content so Proceed still works if the buffer drifted slightly.
        if (typeof action.content === 'string' && action.content.length) {
          nextContent = action.content
        } else {
          error.value = getApiErrorMessage(e, 'Could not apply patch to the open file.')
          emit('liveWriteDone', { path: paintPath, success: false, persisted: false })
          applyingId.value = null
          writingLive.value = false
          liveStatus.value = null
          return
        }
      }
    } else if (typeof action.content === 'string' && action.content.length) {
      nextContent = action.content
    }

    if (nextContent != null) {
      if (isPatch) {
        // One-shot update — do not re-type the whole file.
        emit('liveWriteDelta', { path: paintPath, content: nextContent })
      } else {
        await paintLiveContent(paintPath, nextContent)
      }
      emit('liveWriteDone', { path: paintPath, success: true, persisted: false })
      messages.value.push({
        id: newId(),
        role: 'assistant',
        content: isPatch
          ? 'Applied a **surgical patch** in the editor (rest of the file kept). **Click Save** to write, or **Undo** to discard.'
          : 'Updated the editor buffer. **Click Save** to write the file, or **Undo** to discard.',
      })
      for (const m of messages.value) {
        if (m.pending?.length) m.pending = m.pending.filter((a) => a.id !== action.id)
      }
      applyingId.value = null
      writingLive.value = false
      liveStatus.value = null
      await scrollBottom()
      return
    }
  }

  if (action.type === 'write_files' && action.files?.length) {
    const first = action.files.find((f) => typeof f.content === 'string' && f.content) || action.files[0]
    paintPath = first.path || first.absolute_path || action.path || props.path || 'file'
    const full = String(first.content || '')
    writingLive.value = true
    emit('liveWriteStart', { path: paintPath })
    if (paintPath && paintPath !== props.path) emit('openPath', paintPath)
    await nextTick()
    if (full) {
      await paintLiveContent(paintPath, full)
      paintedLocally = true
      liveStatus.value = 'Live code generation…'
    }
  }

  try {
    const response = await streamAiApply(action.token, undefined, { path: applyPath.value })
    let message = ''
    let success = false
    let sawWriteDone = false
    for await (const event of readSseStream(response)) {
      if (event.type === 'status' && event.text) liveStatus.value = event.text
      if (event.type === 'write_start' && event.path) {
        writingLive.value = true
        if (!paintedLocally) emit('liveWriteStart', { path: event.path })
      }
      if (event.type === 'write_delta' && event.path && typeof event.content === 'string') {
        if (!paintedLocally) {
          emit('liveWriteDelta', { path: event.path, content: event.content })
        }
      }
      if (event.type === 'write_done' && event.path) {
        success = !!event.success
        sawWriteDone = true
        emit('liveWriteDone', { path: event.path, success, persisted: true })
      }
      if (event.type === 'done') {
        success = event.success ?? success
        message = event.message || (success ? 'Applied.' : 'Failed.')
      }
      if (event.type === 'error') throw new Error(event.message || 'Apply failed')
    }
    if (isWrite && !sawWriteDone) {
      emit('liveWriteDone', { path: paintPath, success, persisted: true })
    }
    messages.value.push({
      id: newId(),
      role: 'assistant',
      content: message || (success ? 'Applied.' : 'Failed.'),
    })
    for (const m of messages.value) {
      if (m.pending?.length) {
        m.pending = m.pending.filter((a) => a.id !== action.id)
      }
    }
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not apply action.')
    if (isWrite) emit('liveWriteDone', { path: paintPath, success: false, persisted: false })
  } finally {
    applyingId.value = null
    writingLive.value = false
    liveStatus.value = null
    await scrollBottom()
  }
}

function undoAiEdits() {
  if (!props.canUndo || undoing.value) return
  undoing.value = true
  emit('undoAi')
  undoing.value = false
  messages.value.push({
    id: newId(),
    role: 'assistant',
    content: 'Undone — restored the editor to the content before the last AI edit.',
  })
  void scrollBottom()
}
</script>

<template>
  <div class="agent" :class="isDark ? 'is-dark' : 'is-light'">
    <header class="agent-head">
      <div class="brand">
        <span class="dot" aria-hidden="true" />
        <div class="min-w-0">
          <p class="title">{{ mode === 'files' ? 'AI Engineer' : 'Dev Companion' }}</p>
          <p class="sub">{{ sessionTitle }}</p>
        </div>
      </div>
      <div class="head-meta">
        <span v-if="tokensLabel !== null" class="tokens" :title="`${credits ?? 0} credits remaining`">
          {{ tokensLabel }}
        </span>
        <button type="button" class="icon" title="Chat history" @click="showHistory = !showHistory">☰</button>
        <button type="button" class="icon" title="New chat" @click="startNewChat">＋</button>
        <button
          v-if="canUndo"
          type="button"
          class="icon undo"
          title="Undo last AI edit"
          :disabled="undoing"
          @click="undoAiEdits"
        >
          {{ undoing ? '…' : 'Undo' }}
        </button>
        <button
          type="button"
          class="icon"
          title="Delete this chat"
          :disabled="!sessionId"
          @click="deleteCurrentSession"
        >
          ⌫
        </button>
        <button type="button" class="icon" title="Hide agent" @click="emit('hide')">✕</button>
      </div>
    </header>

    <div v-if="showHistory" class="history">
      <p class="history-label">Saved chats</p>
      <button
        v-for="s in sessions"
        :key="s.id"
        type="button"
        class="history-item"
        :class="{ on: s.id === sessionId }"
        @click="openSession(s.id)"
      >
        <span class="ht">{{ s.title || 'Conversation' }}</span>
        <span class="hm">{{ s.message_count }} msgs</span>
      </button>
      <p v-if="!sessions.length" class="history-empty">No saved chats yet — send a message to start.</p>
    </div>

    <p v-if="writingLive || liveStatus" class="gen-banner" :class="{ live: writingLive }">
      {{ liveStatus || 'Live code generation…' }}
    </p>
    <p v-else-if="lastCharge || credits !== null" class="usage">
      <template v-if="lastCharge">{{ lastCharge.credits }} credit{{ lastCharge.credits === 1 ? '' : 's' }} this turn</template>
      <template v-else>{{ credits }} credit{{ credits === 1 ? '' : 's' }} · usage-based</template>
    </p>

    <div v-if="bootLoading" class="body muted">Loading…</div>
    <div v-else-if="!configured" class="body warn">
      Dev Companion is not available yet. Open support if you need it switched on.
    </div>
    <div v-else-if="credits !== null && credits < 1" class="body warn">
      No credits left. Top up under Billing.
    </div>
    <div v-else ref="scroller" class="body thread-scroll" @click="onThreadClick">
      <p v-if="!messages.length" class="empty">
        <template v-if="mode === 'files'">
          Ask about this folder, selected files, deploy help, or errors. Destructive actions need your confirmation.
        </template>
        <template v-else>Ask to explain or edit this file. Approve changes with Proceed.</template>
      </p>
      <div v-for="m in messages" :key="m.id" class="turn" :class="m.role">
        <div class="bubble">
          <div v-if="m.role === 'assistant'" class="md" v-html="renderAiMarkdown(m.content || '')" />
          <div v-else class="plain">{{ m.content }}</div>
        </div>
        <div v-if="m.pending?.length" class="pending">
          <div v-for="action in m.pending" :key="action.id" class="action">
            <p class="reason">{{ action.reason }}</p>
            <button
              v-if="action.path"
              type="button"
              class="path-chip is-doc"
              :data-ai-path="action.path"
            >
              {{ action.path }}
            </button>
            <button type="button" class="proceed" :disabled="!!applyingId" @click="applyAction(action)">
              {{
                applyingId === action.id
                  ? 'Applying…'
                  : action.patch || action.edits?.length
                    ? 'Apply patch'
                    : action.type === 'write_file'
                      ? 'Apply to editor'
                      : 'Proceed'
              }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="showTyping" class="turn assistant">
        <div class="bubble typing" aria-label="Dev Companion is typing">
          <span /><span /><span />
        </div>
      </div>

      <p v-if="error" class="err">{{ error }}</p>
    </div>

    <div v-if="quickPrompts.length && configured && (credits === null || credits >= 1)" class="quick">
      <button
        v-for="q in quickPrompts"
        :key="q.label"
        type="button"
        class="quick-chip"
        :disabled="sending"
        @click="send(q.text)"
      >
        {{ q.label }}
      </button>
    </div>

    <form class="composer" @submit.prevent="send()">
      <textarea
        v-model="draft"
        rows="2"
        placeholder="Ask Dev Companion… (Enter to send)"
        :disabled="sending || !configured || (credits !== null && credits < 1)"
        @keydown="onComposerKeydown"
      />
      <button type="submit" :disabled="sending || !configured || !draft.trim() || (credits !== null && credits < 1)">
        {{ sending ? '…' : '↑' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.agent {
  --a-bg: #f4f7fb;
  --a-panel: #ffffff;
  --a-ink: #0f172a;
  --a-muted: #64748b;
  --a-line: #e2e8f0;
  --a-accent: #1e3a5f;
  --a-user: #1e3a5f;
  --a-assist: #ffffff;
  --a-warn: #92400e;
  --a-chip: #e8eef5;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(520px 220px at 100% 0%, color-mix(in srgb, var(--a-accent) 10%, transparent), transparent 60%),
    var(--a-bg);
  color: var(--a-ink);
  border-left: 1px solid var(--a-line);
  overflow: hidden;
}
.agent.is-dark {
  --a-bg: #0b1220;
  --a-panel: #111827;
  --a-ink: #e2e8f0;
  --a-muted: #94a3b8;
  --a-line: #1e293b;
  --a-accent: #93c5fd;
  --a-user: #1e3a5f;
  --a-assist: #152033;
  --a-warn: #fbbf24;
  --a-chip: #1e293b;
}
.agent-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem;
  border-bottom: 1px solid var(--a-line);
  flex-shrink: 0;
  background: color-mix(in srgb, var(--a-panel) 88%, transparent);
}
.brand { display: flex; align-items: center; gap: 0.5rem; min-width: 0; }
.dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 999px;
  background: var(--a-accent);
  flex-shrink: 0;
}
.title { margin: 0; font-size: 0.82rem; font-weight: 750; }
.sub {
  margin: 0.1rem 0 0;
  font-size: 0.68rem;
  color: var(--a-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 10rem;
}
.head-meta { display: flex; align-items: center; gap: 0.35rem; flex-shrink: 0; }
.history {
  flex-shrink: 0;
  max-height: 9rem;
  overflow: auto;
  border-bottom: 1px solid var(--a-line);
  padding: 0.45rem 0.65rem;
  background: color-mix(in srgb, var(--a-panel) 92%, var(--a-accent) 8%);
}
.history-label {
  margin: 0 0 0.35rem;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--a-muted);
}
.history-item {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  width: 100%;
  text-align: left;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0.35rem 0.4rem;
  border-radius: 0.35rem;
  cursor: pointer;
  font-size: 0.72rem;
}
.history-item:hover, .history-item.on {
  background: color-mix(in srgb, var(--a-accent) 16%, transparent);
}
.ht {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hm { color: var(--a-muted); flex-shrink: 0; }
.history-empty { margin: 0; font-size: 0.7rem; color: var(--a-muted); }
.tokens {
  font-size: 0.68rem;
  font-weight: 750;
  font-variant-numeric: tabular-nums;
  color: var(--a-accent);
  padding: 0.15rem 0.4rem;
  border-radius: 0.35rem;
  border: 1px solid var(--a-line);
}
.icon {
  border: none;
  background: transparent;
  color: var(--a-muted);
  cursor: pointer;
  font-size: 0.85rem;
  line-height: 1;
  padding: 0.2rem 0.35rem;
}
.icon.undo {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--a-accent);
}
.usage, .gen-banner {
  margin: 0;
  padding: 0.3rem 0.75rem;
  font-size: 0.65rem;
  color: var(--a-muted);
  border-bottom: 1px solid var(--a-line);
  flex-shrink: 0;
}
.gen-banner.live {
  color: var(--a-accent);
  font-weight: 700;
  background: color-mix(in srgb, var(--a-accent) 10%, transparent);
}
.body {
  flex: 1;
  min-height: 0;
  padding: 0.7rem 0.75rem;
  overflow: hidden;
}
.thread-scroll {
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.thread-scroll::-webkit-scrollbar { display: none; width: 0; height: 0; }
.muted, .empty { margin: 0; color: var(--a-muted); font-size: 0.8rem; line-height: 1.45; }
.warn { color: var(--a-warn); font-size: 0.8rem; }
.turn {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-bottom: 0.7rem;
  width: 100%;
  max-width: 100%;
  min-width: 0;
}
.turn.user { align-items: flex-end; }
.turn.assistant { align-items: flex-start; }
.bubble {
  box-sizing: border-box;
  max-width: min(100%, 36rem);
  min-width: 0;
  width: auto;
  border-radius: 0.85rem;
  padding: 0.6rem 0.75rem;
  font-size: 0.82rem;
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-word;
  box-shadow: 0 1px 0 color-mix(in srgb, var(--a-ink) 6%, transparent);
}
.turn.user .bubble { max-width: min(100%, 30rem); }
.turn.user .bubble { background: var(--a-user); color: #fff; }
.turn.assistant .bubble { background: var(--a-assist); color: var(--a-ink); border: 1px solid var(--a-line); }
.plain { white-space: pre-wrap; overflow-wrap: anywhere; }
.md { min-width: 0; max-width: 100%; overflow: hidden; overflow-wrap: anywhere; }
.md :deep(p),
.md :deep(.ai-md-p) { margin: 0 0 0.45rem; overflow-wrap: anywhere; word-break: break-word; }
.md :deep(a) { overflow-wrap: anywhere; word-break: break-word; }
.md :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
}
.md :deep(th),
.md :deep(td) { overflow-wrap: anywhere; word-break: break-word; }
.md :deep(ul),
.md :deep(ol) { padding-left: 1.1rem; margin: 0.35rem 0 0.55rem; overflow-wrap: anywhere; }
.md :deep(p:last-child),
.md :deep(.ai-md-p:last-child) { margin-bottom: 0; }
.md :deep(pre),
.md :deep(.ai-md-pre) {
  margin: 0.4rem 0;
  padding: 0.5rem;
  border-radius: 0.45rem;
  overflow-x: auto;
  max-width: 100%;
  font-size: 0.72rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: color-mix(in srgb, var(--a-ink) 7%, transparent);
  scrollbar-width: none;
}
.md :deep(pre)::-webkit-scrollbar { display: none; }
.md :deep(.ai-file-chip),
.path-chip {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  margin: 0.1rem 0.1rem;
  padding: 0.12rem 0.4rem;
  border-radius: 0.35rem;
  border: 1px solid color-mix(in srgb, var(--a-accent) 28%, var(--a-line));
  background: var(--a-chip);
  color: var(--a-accent);
  font: inherit;
  font-size: 0.72rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 650;
  cursor: pointer;
  overflow-wrap: anywhere;
  word-break: break-all;
  text-align: left;
}
.md :deep(.ai-file-chip.is-doc),
.path-chip.is-doc {
  background: color-mix(in srgb, #0ea5e9 14%, var(--a-chip));
  border-color: color-mix(in srgb, #0ea5e9 35%, var(--a-line));
}
.typing {
  display: inline-flex;
  gap: 0.28rem;
  align-items: center;
  padding: 0.7rem 0.9rem !important;
  min-width: 3.2rem;
}
.typing span {
  width: 0.35rem;
  height: 0.35rem;
  border-radius: 999px;
  background: var(--a-muted);
  animation: bounce 1.1s infinite ease-in-out;
}
.typing span:nth-child(2) { animation-delay: 0.15s; }
.typing span:nth-child(3) { animation-delay: 0.3s; }
@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.45; }
  40% { transform: translateY(-0.25rem); opacity: 1; }
}
.pending { width: 100%; display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; }
.action {
  border: 1px solid var(--a-line);
  border-radius: 0.55rem;
  padding: 0.5rem 0.6rem;
  background: var(--a-panel);
  min-width: 0;
}
.reason { margin: 0; font-size: 0.74rem; font-weight: 650; overflow-wrap: anywhere; }
.proceed {
  margin-top: 0.4rem;
  border: none;
  border-radius: 0.4rem;
  background: var(--a-accent);
  color: #fff;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.3rem 0.65rem;
  cursor: pointer;
}
.is-dark .proceed { color: #0b1220; }
.proceed:disabled { opacity: 0.5; cursor: not-allowed; }
.err { margin: 0; font-size: 0.75rem; color: #ef4444; overflow-wrap: anywhere; }
.quick {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  padding: 0.45rem 0.65rem 0;
  flex-shrink: 0;
}
.quick-chip {
  border: 1px solid var(--a-line);
  background: var(--a-panel);
  color: inherit;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 650;
  padding: 0.25rem 0.55rem;
  cursor: pointer;
}
.quick-chip:disabled { opacity: 0.45; cursor: not-allowed; }
.composer {
  display: flex;
  gap: 0.4rem;
  align-items: flex-end;
  padding: 0.55rem 0.65rem 0.7rem;
  border-top: 1px solid var(--a-line);
  flex-shrink: 0;
  background: var(--a-panel);
}
.composer textarea {
  flex: 1;
  border: 1px solid var(--a-line);
  border-radius: 0.55rem;
  background: var(--a-bg);
  color: var(--a-ink);
  padding: 0.5rem 0.6rem;
  font: inherit;
  font-size: 0.82rem;
  resize: none;
  line-height: 1.35;
  max-height: 6rem;
  overflow-y: auto;
  scrollbar-width: none;
}
.composer textarea::-webkit-scrollbar { display: none; }
.composer textarea:focus { outline: 1px solid color-mix(in srgb, var(--a-accent) 55%, transparent); }
.composer button {
  width: 2.1rem;
  height: 2.1rem;
  border: none;
  border-radius: 0.5rem;
  background: var(--a-accent);
  color: #fff;
  font-size: 1rem;
  font-weight: 700;
  cursor: pointer;
  flex-shrink: 0;
}
.is-dark .composer button { color: #0b1220; }
.composer button:disabled { opacity: 0.45; cursor: not-allowed; }
</style>

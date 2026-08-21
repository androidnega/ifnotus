<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import CodeEditor from '@/components/files/CodeEditor.vue'
import DiffEditor from '@/components/files/DiffEditor.vue'
import AiAgentPanel from '@/components/ai/AiAgentPanel.vue'
import { filesApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import { useThemeStore } from '@/stores/theme'
import type { FileDetail } from '@/types/hosting'

type EditorColorMode = 'light' | 'dark'
type ViewMode = 'edit' | 'compare'

const route = useRoute()
const router = useRouter()
const theme = useThemeStore()
const { can } = usePermissions()
const canWrite = computed(() => can(Permission.FILES_WRITE))

const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)
const message = ref<{ ok: boolean; text: string } | null>(null)
const meta = ref<FileDetail | null>(null)
const content = ref('')
const original = ref('')
const savedContent = ref('')
const aiBaseline = ref('')
const isAiWriting = ref(false)
const reviewingAi = ref(false)
const viewMode = ref<ViewMode>('edit')
const showAi = ref(true)
const FONT_KEY = 'ifnotus.editor.fontSize'
const WRAP_KEY = 'ifnotus.editor.wordWrap'
const storedFont = Number(localStorage.getItem(FONT_KEY) || '14')
const fontSize = ref(Number.isFinite(storedFont) ? Math.min(36, Math.max(10, storedFont)) : 14)
const wordWrap = ref(localStorage.getItem(WRAP_KEY) !== '0')

const storedEditorTheme = localStorage.getItem('ifnotus.editor.theme') as EditorColorMode | null
const colorMode = ref<EditorColorMode>(
  storedEditorTheme || (theme.isDark ? 'dark' : 'light'),
)

const filePath = computed(() => String(route.query.path || ''))
const rootId = computed(() => {
  const root = String(route.query.root || '')
  if (
    root.startsWith('root:') ||
    root.startsWith('discovered:') ||
    root.startsWith('storage:')
  ) {
    return root
  }
  return undefined
})
const appId = computed(() => {
  const root = String(route.query.root || '')
  if (
    !root ||
    root.startsWith('root:') ||
    root.startsWith('discovered:') ||
    root.startsWith('storage:')
  ) {
    return undefined
  }
  return root
})
const scope = computed(() => ({
  appId: appId.value,
  rootId: rootId.value,
}))

const fileName = computed(() => filePath.value.split('/').pop() || filePath.value || 'untitled')
const dirty = computed(() => content.value !== savedContent.value)
const extension = computed(() => {
  const i = fileName.value.lastIndexOf('.')
  return i > 0 ? fileName.value.slice(i + 1).toUpperCase() : 'FILE'
})

watch(colorMode, (mode) => {
  localStorage.setItem('ifnotus.editor.theme', mode)
  document.documentElement.classList.toggle('dark', mode === 'dark')
  document.documentElement.style.colorScheme = mode
})

watch(fontSize, (size) => localStorage.setItem(FONT_KEY, String(size)))
watch(wordWrap, (on) => localStorage.setItem(WRAP_KEY, on ? '1' : '0'))

function zoomIn() {
  fontSize.value = Math.min(36, fontSize.value + 1)
}
function zoomOut() {
  fontSize.value = Math.max(10, fontSize.value - 1)
}
function zoomReset() {
  fontSize.value = 14
}

async function loadFile() {
  if (!filePath.value) {
    error.value = 'Missing file path.'
    loading.value = false
    return
  }
  loading.value = true
  error.value = null
  try {
    const { data } = await filesApi.read(filePath.value, scope.value)
    content.value = data.content ?? ''
    original.value = data.content ?? ''
    savedContent.value = data.content ?? ''
    meta.value = data
    document.title = `${fileName.value} · IFNOTUS Editor`
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Failed to open file')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!canWrite.value || !dirty.value) return
  saving.value = true
  message.value = null
  try {
    const { data } = await filesApi.write(filePath.value, content.value, scope.value)
    message.value = { ok: data.success, text: data.message }
    if (data.success) {
      original.value = content.value
      savedContent.value = content.value
    }
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Save failed') }
  } finally {
    saving.value = false
  }
}

function closeWindow() {
  if (dirty.value && !confirm('Discard unsaved changes?')) return
  try {
    window.close()
  } catch {
    /* ignore */
  }
  window.setTimeout(() => {
    if (!window.closed) {
      router.push({
        name: 'files',
        query: {
          root: String(route.query.root || ''),
          path: filePath.value.includes('/') ? filePath.value.replace(/\/[^/]+$/, '') || '.' : '.',
        },
      })
    }
  }, 120)
}

function toggleTheme() {
  colorMode.value = colorMode.value === 'dark' ? 'light' : 'dark'
}

function onKeydown(ev: KeyboardEvent) {
  const mod = ev.metaKey || ev.ctrlKey
  if (!mod) return

  if (ev.key.toLowerCase() === 's') {
    ev.preventDefault()
    save()
    return
  }
  if (ev.key.toLowerCase() === 'd') {
    ev.preventDefault()
    toggleCompare()
    return
  }

  // Zoom: ⌘/Ctrl + (Equal/+), −, 0 — capture so Monaco doesn't eat it
  const code = ev.code
  if (code === 'Equal' || code === 'NumpadAdd' || ev.key === '=' || ev.key === '+') {
    ev.preventDefault()
    ev.stopPropagation()
    zoomIn()
    return
  }
  if (code === 'Minus' || code === 'NumpadSubtract' || ev.key === '-' || ev.key === '_') {
    ev.preventDefault()
    ev.stopPropagation()
    zoomOut()
    return
  }
  if (code === 'Digit0' || code === 'Numpad0' || ev.key === '0') {
    ev.preventDefault()
    ev.stopPropagation()
    zoomReset()
  }
}

function onWheel(ev: WheelEvent) {
  if (!(ev.metaKey || ev.ctrlKey)) return
  ev.preventDefault()
  if (ev.deltaY < 0) zoomIn()
  else if (ev.deltaY > 0) zoomOut()
}

function sameFile(path: string) {
  const target = path.replace(/^\/+/, '')
  const current = filePath.value.replace(/^\/+/, '')
  return target === current
    || target.endsWith('/' + current)
    || current.endsWith('/' + target)
    || path === filePath.value
}

function onAiApplied(action: { type: string }) {
  if (action.type !== 'write_file' && action.type !== 'write_files') loadFile()
}

function onAiUndone() {
  loadFile()
  reviewingAi.value = false
  message.value = { ok: true, text: 'AI write undone. Reloaded from server.' }
}

function toggleCompare() {
  if (viewMode.value === 'compare') {
    viewMode.value = 'edit'
    reviewingAi.value = false
    return
  }
  viewMode.value = 'compare'
}

function onLiveWriteStart(payload: { path: string }) {
  if (!sameFile(payload.path)) return
  aiBaseline.value = content.value
  original.value = content.value
  isAiWriting.value = true
  reviewingAi.value = false
  if (viewMode.value !== 'edit') viewMode.value = 'edit'
  message.value = { ok: true, text: 'Snr Dev is writing in the editor live…' }
}

function onLiveWriteDelta(payload: { path: string; content: string }) {
  if (!sameFile(payload.path)) return
  content.value = payload.content
}

function onLiveWriteDone(payload: { path: string; success: boolean }) {
  if (!sameFile(payload.path)) return
  isAiWriting.value = false
  if (payload.success) {
    savedContent.value = content.value
    original.value = aiBaseline.value || original.value
    reviewingAi.value = true
    viewMode.value = 'compare'
    message.value = { ok: true, text: 'Snr Dev finished writing live. Reviewing highlighted changes.' }
  } else {
    content.value = aiBaseline.value || content.value
    reviewingAi.value = false
    message.value = { ok: false, text: 'The live write did not complete. Restored the previous editor content.' }
  }
}

onMounted(async () => {
  document.documentElement.classList.toggle('dark', colorMode.value === 'dark')
  document.documentElement.style.colorScheme = colorMode.value
  window.addEventListener('keydown', onKeydown, true)
  window.addEventListener('wheel', onWheel, { passive: false, capture: true })
  await loadFile()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown, true)
  window.removeEventListener('wheel', onWheel, true)
})
</script>

<template>
  <div class="editor-shell" :class="colorMode === 'dark' ? 'is-dark' : 'is-light'">
    <header class="editor-top">
      <div class="editor-identity">
        <button type="button" class="icon-btn" title="Close" @click="closeWindow">←</button>
        <span class="ext-chip">{{ extension }}</span>
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold">
            {{ fileName }}
            <span v-if="dirty" class="dirty">●</span>
            <span v-if="isAiWriting" class="ml-2 text-xs font-normal text-emerald-600">AI writing live…</span>
          </p>
          <p class="truncate font-mono text-[11px] opacity-60">{{ filePath }}</p>
        </div>
      </div>

      <div class="editor-tools">
        <Badge v-if="meta?.mode" size="sm">{{ meta.mode }}</Badge>
        <div class="zoom-group" title="Zoom (⌘/Ctrl + scroll, + / − / 0)">
          <button type="button" class="tool-btn zoom-btn" :disabled="fontSize <= 10" @click="zoomOut">A−</button>
          <span class="zoom-label">{{ fontSize }}</span>
          <button type="button" class="tool-btn zoom-btn" :disabled="fontSize >= 36" @click="zoomIn">A+</button>
        </div>
        <button
          type="button"
          class="tool-btn"
          :class="{ 'is-active': wordWrap }"
          title="Toggle word wrap"
          @click="wordWrap = !wordWrap"
        >
          Wrap
        </button>
        <button
          type="button"
          class="tool-btn"
          :class="{ 'is-active': viewMode === 'compare' }"
          title="Compare before/after (⌘D)"
          @click="toggleCompare"
        >
          {{ viewMode === 'compare' ? 'Editing' : reviewingAi ? 'AI Diff' : 'Compare' }}
        </button>
        <button type="button" class="tool-btn" @click="toggleTheme">
          {{ colorMode === 'dark' ? 'Light' : 'Dark' }}
        </button>
        <button type="button" class="tool-btn" @click="showAi = !showAi">
          {{ showAi ? 'Hide AI' : 'AI' }}
        </button>
        <button type="button" class="tool-btn" @click="closeWindow">Close</button>
        <button
          v-if="canWrite"
          type="button"
          class="save-btn"
          :disabled="saving || !dirty || viewMode === 'compare'"
          @click="save"
        >
          {{ saving ? 'Saving…' : dirty ? 'Save' : 'Saved' }}
        </button>
      </div>
    </header>

    <p
      v-if="message"
      class="banner"
      :class="message.ok ? 'is-ok' : 'is-err'"
    >
      {{ message.text }}
    </p>

    <div class="editor-body" :class="{ 'with-ai': showAi }">
      <div class="editor-main">
        <div v-if="loading" class="pad">
          <Skeleton height="1rem" width="30%" />
          <Skeleton class="mt-3" height="70vh" />
        </div>
        <div v-else-if="error" class="pad error">{{ error }}</div>
        <DiffEditor
          v-else-if="viewMode === 'compare'"
          :original="reviewingAi ? (aiBaseline || original) : original"
          :modified="content"
          :path="filePath"
          :color-mode="colorMode"
          :font-size="fontSize"
          :word-wrap="wordWrap"
        />
        <CodeEditor
          v-else
          v-model="content"
          :path="filePath"
          :readonly="!canWrite || isAiWriting"
          :color-mode="colorMode"
          :font-size="fontSize"
          :word-wrap="wordWrap"
          @save="save"
        />
      </div>

      <AiAgentPanel
        v-if="showAi"
        surface="editor"
        :path="filePath"
        :app-id="appId"
        :root-id="rootId"
        :file-content="content"
        :original-content="reviewingAi ? (aiBaseline || original) : original"
        @applied="onAiApplied"
        @undone="onAiUndone"
        @live-write-start="onLiveWriteStart"
        @live-write-delta="onLiveWriteDelta"
        @live-write-done="onLiveWriteDone"
      />
    </div>
  </div>
</template>

<style scoped>
.editor-shell {
  display: flex;
  height: 100vh;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(900px 320px at 8% -10%, rgb(15 118 110 / 0.08), transparent 55%),
    var(--bg);
  color: var(--fg);
  --bg: #f7f8fa;
  --fg: #0f172a;
  --panel: #ffffff;
  --line: rgb(15 23 42 / 0.1);
  --muted: #64748b;
}
.editor-shell.is-dark {
  --bg: #0b1220;
  --fg: #e2e8f0;
  --panel: #111827;
  --line: rgb(148 163 184 / 0.18);
  --muted: #94a3b8;
}
.editor-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  padding: 0.7rem 0.9rem;
  backdrop-filter: blur(8px);
}
.editor-identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.65rem;
}
.icon-btn,
.tool-btn,
.save-btn {
  border-radius: 0.65rem;
  border: 1px solid var(--line);
  background: transparent;
  padding: 0.4rem 0.7rem;
  font-size: 0.78rem;
  color: inherit;
}
.icon-btn {
  width: 2rem;
  padding: 0.35rem;
}
.tool-btn.is-active,
.tool-btn:hover,
.icon-btn:hover {
  background: rgb(15 118 110 / 0.12);
}
.zoom-group {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  border: 1px solid var(--line);
  border-radius: 0.65rem;
  padding: 0.1rem;
}
.zoom-btn {
  border: 0 !important;
  padding: 0.3rem 0.5rem !important;
  min-width: 2rem;
}
.zoom-btn:disabled {
  opacity: 0.35;
}
.zoom-label {
  min-width: 1.6rem;
  text-align: center;
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
}
.save-btn {
  border-color: transparent;
  background: #0f766e;
  color: white;
  font-weight: 600;
}
.save-btn:disabled { opacity: 0.45; }
.ext-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2.4rem;
  border-radius: 0.55rem;
  background: rgb(15 118 110 / 0.14);
  color: #0f766e;
  padding: 0.35rem 0.45rem;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.is-dark .ext-chip { color: #5eead4; }
.dirty { color: #f59e0b; margin-left: 0.25rem; }
.editor-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}
.banner {
  padding: 0.45rem 0.9rem;
  font-size: 0.8rem;
}
.banner.is-ok { background: rgb(16 185 129 / 0.12); color: #047857; }
.banner.is-err { background: rgb(239 68 68 / 0.12); color: #b91c1c; }
.editor-body {
  display: grid;
  min-height: 0;
  flex: 1;
  gap: 0.75rem;
  padding: 0.75rem;
}
.editor-body.with-ai {
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 1100px) {
  .editor-body.with-ai {
    grid-template-columns: minmax(0, 1fr) minmax(17rem, 22rem);
  }
}
.editor-main {
  display: flex;
  min-height: 0;
  flex-direction: column;
}
.pad { padding: 1rem; }
.error { color: #dc2626; font-size: 0.9rem; }
</style>

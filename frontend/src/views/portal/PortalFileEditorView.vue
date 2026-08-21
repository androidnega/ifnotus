<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import CodeEditor from '@/components/files/CodeEditor.vue'
import DiffEditor from '@/components/files/DiffEditor.vue'
import PortalAiPanel from '@/components/ai/PortalAiPanel.vue'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'

type EditorColorMode = 'light' | 'dark'
type ViewMode = 'edit' | 'compare'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)
const message = ref<{ ok: boolean; text: string } | null>(null)
const content = ref('')
const original = ref('')
const savedContent = ref('')
const viewMode = ref<ViewMode>('edit')
const FONT_KEY = 'ifnotus.editor.fontSize'
const WRAP_KEY = 'ifnotus.editor.wordWrap'
const storedFont = Number(localStorage.getItem(FONT_KEY) || '14')
const fontSize = ref(Number.isFinite(storedFont) ? Math.min(36, Math.max(10, storedFont)) : 14)
const wordWrap = ref(localStorage.getItem(WRAP_KEY) !== '0')
const storedEditorTheme = localStorage.getItem('ifnotus.editor.theme') as EditorColorMode | null
const colorMode = ref<EditorColorMode>(storedEditorTheme || 'light')
const AI_KEY = 'ifnotus.editor.showAi'
const showAi = ref(localStorage.getItem(AI_KEY) !== '0')
const isAiWriting = ref(false)
const liveGenLabel = ref<string | null>(null)
const aiBaseline = ref('')
const canUndoAi = ref(false)

watch(showAi, (on) => localStorage.setItem(AI_KEY, on ? '1' : '0'))

const envId = computed(() => String(route.query.env || ''))
const filePath = computed(() => String(route.query.path || ''))
const fileName = computed(() => filePath.value.split('/').pop() || filePath.value || 'untitled')
const dirty = computed(() => content.value !== savedContent.value)
const extension = computed(() => {
  const i = fileName.value.lastIndexOf('.')
  return i > 0 ? fileName.value.slice(i + 1).toUpperCase() : 'FILE'
})
const folderPath = computed(() => {
  if (!filePath.value.includes('/')) return '.'
  return filePath.value.replace(/\/[^/]+$/, '') || '.'
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
  if (!envId.value || !filePath.value) {
    error.value = 'Missing file path or site.'
    loading.value = false
    return
  }
  loading.value = true
  error.value = null
  try {
    const { data } = await customersApi.readEnvFile(envId.value, filePath.value)
    content.value = data.content ?? ''
    original.value = data.content ?? ''
    savedContent.value = data.content ?? ''
    document.title = `${fileName.value} · IFNOTUS Editor`
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Failed to open file')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!dirty.value) return
  saving.value = true
  message.value = null
  try {
    const { data } = await customersApi.writeEnvFile(envId.value, filePath.value, content.value)
    const ok = Boolean((data as { success?: boolean }).success ?? true)
    message.value = {
      ok,
      text: (data as { message?: string }).message || (ok ? 'Saved.' : 'Save failed'),
    }
    if (ok) {
      original.value = content.value
      savedContent.value = content.value
      canUndoAi.value = false
      aiBaseline.value = content.value
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
        name: 'portal-files',
        query: { env: envId.value, path: folderPath.value },
      })
    }
  }, 120)
}

function openManager() {
  const href = `/account/files?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(folderPath.value)}`
  window.open(href, `ifnotus-files-${envId.value}`)
}

function onLiveWriteStart(payload: { path: string }) {
  isAiWriting.value = true
  aiBaseline.value = content.value
  // Keep original as pre-AI for Compare; do not touch savedContent (Save stays required).
  original.value = content.value
  canUndoAi.value = false
  liveGenLabel.value = 'AI pair programming…'
  message.value = { ok: true, text: liveGenLabel.value }
  void payload
}

function onLiveWriteDelta(payload: { path: string; content: string }) {
  if (payload.content == null) return
  isAiWriting.value = true
  // Keep painting even if path label differs slightly (public vs relative).
  content.value = payload.content
  liveGenLabel.value = 'Live code generation…'
  message.value = { ok: true, text: liveGenLabel.value }
  if (viewMode.value === 'compare') viewMode.value = 'edit'
}

function onLiveWriteDone(payload: { path: string; success: boolean; persisted?: boolean }) {
  isAiWriting.value = false
  if (payload.success) {
    canUndoAi.value = true
    if (payload.persisted) {
      // Multi-file / mkdir path wrote disk — buffer matches disk.
      savedContent.value = content.value
      liveGenLabel.value = 'AI finished. Review with Compare if needed.'
    } else {
      // Buffer-only: leave dirty so Save is required.
      liveGenLabel.value = 'AI updated the editor. Click Save to write the file, or Undo to discard.'
    }
    message.value = { ok: true, text: liveGenLabel.value }
    window.setTimeout(() => {
      if (liveGenLabel.value?.includes('AI')) liveGenLabel.value = null
    }, 8000)
  } else {
    content.value = aiBaseline.value || content.value
    canUndoAi.value = false
    liveGenLabel.value = null
    message.value = { ok: false, text: 'Code generation did not complete. Restored previous editor content.' }
  }
}

function undoAiChanges() {
  if (!canUndoAi.value) return
  content.value = aiBaseline.value
  canUndoAi.value = false
  liveGenLabel.value = null
  message.value = { ok: true, text: 'Undone — restored content from before the AI edit.' }
  if (viewMode.value === 'compare') viewMode.value = 'edit'
}

async function openPath(path: string) {
  const clean = path.replace(/^\/+/, '').replace(/^site root\/?/i, '')
  if (!clean || clean === filePath.value) return
  // During live generation, switch files without a discard prompt.
  if (!isAiWriting.value && dirty.value && !confirm('Open another file and discard unsaved changes?')) return
  await router.replace({
    name: 'portal-file-editor',
    query: { env: envId.value, path: clean },
  })
  // Never reload from disk while AI is painting into the buffer.
  if (!isAiWriting.value) await loadFile()
}

function toggleTheme() {
  colorMode.value = colorMode.value === 'dark' ? 'light' : 'dark'
}

function toggleCompare() {
  viewMode.value = viewMode.value === 'compare' ? 'edit' : 'compare'
}

function onKeydown(ev: KeyboardEvent) {
  const mod = ev.metaKey || ev.ctrlKey
  if (!mod) return
  if (ev.key.toLowerCase() === 's') {
    ev.preventDefault()
    void save()
    return
  }
  if (ev.key.toLowerCase() === 'd') {
    ev.preventDefault()
    toggleCompare()
    return
  }
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
          </p>
          <p class="truncate font-mono text-[11px] opacity-60">{{ filePath }}</p>
        </div>
      </div>

      <div class="editor-tools">
        <Badge size="sm">Site files</Badge>
        <div class="zoom-group" title="Zoom (⌘/Ctrl + scroll, + / − / 0)">
          <button type="button" class="tool-btn zoom-btn" :disabled="fontSize <= 10" @click="zoomOut">A−</button>
          <span class="zoom-label" :title="`Font size ${fontSize}px`">{{ fontSize }}px</span>
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
          {{ viewMode === 'compare' ? 'Editing' : 'Compare' }}
        </button>
        <button type="button" class="tool-btn" @click="toggleTheme">
          {{ colorMode === 'dark' ? 'Light' : 'Dark' }}
        </button>
        <button
          type="button"
          class="tool-btn"
          :class="{ 'is-active': showAi }"
          title="Toggle Dev Companion"
          @click="showAi = !showAi"
        >
          {{ showAi ? 'Hide AI' : 'AI' }}
        </button>
        <button
          type="button"
          class="tool-btn"
          :disabled="!canUndoAi || isAiWriting"
          title="Undo last AI edit"
          @click="undoAiChanges"
        >
          Undo
        </button>
        <button type="button" class="tool-btn" @click="openManager">Files</button>
        <button type="button" class="tool-btn" @click="closeWindow">Close</button>
        <button
          type="button"
          class="save-btn"
          :disabled="saving || !dirty || viewMode === 'compare' || isAiWriting"
          @click="save"
        >
          {{ saving ? 'Saving…' : dirty ? 'Save' : 'Saved' }}
        </button>
      </div>
    </header>

    <p v-if="liveGenLabel" class="banner is-gen">{{ liveGenLabel }}</p>
    <p v-else-if="message" class="banner" :class="message.ok ? 'is-ok' : 'is-err'">{{ message.text }}</p>

    <div class="editor-body" :class="{ 'with-ai': showAi && !!envId }">
      <div class="editor-main">
        <div v-if="loading" class="pad">
          <Skeleton height="1rem" width="30%" />
          <Skeleton class="mt-3" height="70vh" />
        </div>
        <div v-else-if="error" class="pad error">{{ error }}</div>
        <DiffEditor
          v-else-if="viewMode === 'compare'"
          :original="original"
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
          :readonly="isAiWriting"
          :streaming="isAiWriting"
          :color-mode="colorMode"
          :font-size="fontSize"
          :word-wrap="wordWrap"
          @save="save"
        />
      </div>

      <aside v-if="showAi && envId" class="ai-aside">
        <PortalAiPanel
          :environment-id="envId"
          :path="filePath"
          :file-content="content"
          :original-content="original"
          :color-mode="colorMode"
          :can-undo="canUndoAi"
          @hide="showAi = false"
          @open-path="openPath"
          @live-write-start="onLiveWriteStart"
          @live-write-delta="onLiveWriteDelta"
          @live-write-done="onLiveWriteDone"
          @undo-ai="undoAiChanges"
        />
      </aside>
    </div>
  </div>
</template>

<style scoped>
.editor-shell {
  height: 100vh;
  max-height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f8fafc;
  color: #0f172a;
}
.editor-shell.is-dark {
  background: #0b1220;
  color: #e2e8f0;
}
.editor-top {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid #d7dee8;
  background: rgba(255, 255, 255, 0.96);
  flex-shrink: 0;
  z-index: 5;
}
.is-dark .editor-top {
  background: rgba(11, 18, 32, 0.96);
  border-color: #1e293b;
}
.editor-identity {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
}
.icon-btn,
.tool-btn,
.save-btn {
  border-radius: 0.4rem;
  border: 1px solid #d7dee8;
  background: #fff;
  color: #334155;
  font-size: 0.78rem;
  font-weight: 650;
  padding: 0.35rem 0.55rem;
  cursor: pointer;
}
.is-dark .icon-btn,
.is-dark .tool-btn {
  background: #111827;
  border-color: #334155;
  color: #e2e8f0;
}
.tool-btn.is-active {
  border-color: #1e3a5f;
  color: #1e3a5f;
  background: #e8eef5;
}
.save-btn {
  background: #1e3a5f;
  border-color: #1e3a5f;
  color: #fff;
}
.save-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.ext-chip {
  font-size: 0.65rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  background: #e8eef5;
  color: #1e3a5f;
  border-radius: 0.35rem;
  padding: 0.2rem 0.4rem;
}
.dirty { color: #ea580c; margin-left: 0.25rem; }
.editor-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}
.zoom-group {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  border: 1px solid #d7dee8;
  border-radius: 0.45rem;
  padding: 0.1rem;
}
.is-dark .zoom-group { border-color: #334155; }
.zoom-label {
  min-width: 2.2rem;
  text-align: center;
  font-size: 0.7rem;
  font-weight: 700;
  opacity: 0.75;
  user-select: none;
}
.banner {
  margin: 0;
  padding: 0.45rem 0.85rem;
  font-size: 0.82rem;
  flex-shrink: 0;
}
.banner.is-ok { background: #ecfdf5; color: #047857; }
.banner.is-err { background: #fef2f2; color: #b91c1c; }
.banner.is-gen {
  background: color-mix(in srgb, #1e3a5f 12%, #f8fafc);
  color: #1e3a5f;
  font-weight: 700;
}
.is-dark .banner.is-gen {
  background: color-mix(in srgb, #93c5fd 12%, #0b1220);
  color: #93c5fd;
}
.editor-body {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
  padding: 0;
  overflow: hidden;
}
.editor-body.with-ai {
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 1100px) {
  .editor-body.with-ai {
    grid-template-columns: minmax(0, 1fr) minmax(18rem, 24rem);
  }
}
.editor-main {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0.65rem;
}
.ai-aside {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
@media (max-width: 1099px) {
  .editor-body.with-ai {
    grid-template-rows: minmax(0, 1fr) minmax(14rem, 38vh);
  }
}
.pad { padding: 1rem; }
.error { color: #b91c1c; }
</style>

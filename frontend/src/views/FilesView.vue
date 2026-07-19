<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Badge from '@/components/ui/Badge.vue'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import IconFolder from '@/components/icons/IconFolder.vue'
import { filesApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { useFileTransferStore } from '@/stores/fileTransfers'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { FileDetail, FileRoot } from '@/types/hosting'
import type { FileEntry } from '@/types/operations'

type ViewMode = 'list' | 'grid'
type SortKey = 'name' | 'size' | 'modified' | 'type'
type SortDir = 'asc' | 'desc'

const VIEW_KEY = 'ifnotus.files.view'
const SORT_KEY = 'ifnotus.files.sort'

const route = useRoute()
const transfers = useFileTransferStore()
const { can } = usePermissions()
const canWrite = computed(() => can(Permission.FILES_WRITE))

const loading = ref(true)
const roots = ref<FileRoot[]>([])
const selectedRoot = ref('')
const entries = ref<FileEntry[]>([])
const currentPath = ref('.')
const parentPath = ref<string | undefined>()
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const actionKey = ref<string | null>(null)

const viewMode = ref<ViewMode>((localStorage.getItem(VIEW_KEY) as ViewMode) || 'list')
const sortKey = ref<SortKey>((localStorage.getItem(SORT_KEY) as SortKey) || 'name')
const sortDir = ref<SortDir>('asc')
const search = ref('')
const showHidden = ref(false)
const menuPath = ref<string | null>(null)

const editorOpen = ref(false)
const editorPath = ref('')
const editorContent = ref('')
const editorMeta = ref<FileDetail | null>(null)

const newFolderName = ref('')
const showNewFolder = ref(false)
const chmodMode = ref('644')

const selected = ref<FileEntry | null>(null)
const infoPanel = ref<FileDetail | null>(null)
const renameTarget = ref<FileEntry | null>(null)
const renameValue = ref('')
const moveTarget = ref<FileEntry | null>(null)
const moveDestination = ref('')

const scope = computed(() => {
  if (!selectedRoot.value) return {}
  if (selectedRoot.value.startsWith('root:') || selectedRoot.value.startsWith('discovered:')) {
    return { rootId: selectedRoot.value }
  }
  return { appId: selectedRoot.value }
})

const activeRoot = computed(() => roots.value.find((r) => r.id === selectedRoot.value))

const uploadLink = computed(() => ({
  name: 'files-upload',
  query: {
    root: selectedRoot.value,
    path: currentPath.value,
  },
}))

const breadcrumbs = computed(() => {
  const rootLabel = activeRoot.value?.label || 'Root'
  const parts = currentPath.value === '.' ? [] : currentPath.value.split('/').filter(Boolean)
  const crumbs: Array<{ label: string; path: string }> = [{ label: rootLabel, path: '.' }]
  let acc = ''
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part
    crumbs.push({ label: part, path: acc })
  }
  return crumbs
})

const filteredEntries = computed(() => {
  const q = search.value.trim().toLowerCase()
  let list = entries.value.filter((e) => showHidden.value || !e.name.startsWith('.'))
  if (q) list = list.filter((e) => e.name.toLowerCase().includes(q))

  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...list].sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
    if (sortKey.value === 'size') return ((a.size_bytes ?? 0) - (b.size_bytes ?? 0)) * dir
    if (sortKey.value === 'modified') {
      return (Date.parse(a.modified ?? '') - Date.parse(b.modified ?? '')) * dir || a.name.localeCompare(b.name)
    }
    if (sortKey.value === 'type') {
      return fileKind(a).localeCompare(fileKind(b)) * dir || a.name.localeCompare(b.name)
    }
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) * dir
  })
})

const folderCount = computed(() => filteredEntries.value.filter((e) => e.is_dir).length)
const fileCount = computed(() => filteredEntries.value.filter((e) => !e.is_dir).length)

watch(viewMode, (v) => localStorage.setItem(VIEW_KEY, v))
watch(sortKey, (v) => localStorage.setItem(SORT_KEY, v))

function fileKind(entry: FileEntry): string {
  if (entry.is_dir) return 'folder'
  const name = entry.name.toLowerCase()
  if (/\.(png|jpe?g|gif|webp|svg|ico|bmp)$/.test(name)) return 'image'
  if (/\.(mp4|webm|mov|mkv|avi)$/.test(name)) return 'video'
  if (/\.(mp3|wav|ogg|flac|m4a)$/.test(name)) return 'audio'
  if (/\.(zip|tar|gz|tgz|rar|7z|bz2)$/.test(name)) return 'archive'
  if (/\.(js|ts|tsx|jsx|vue|py|php|rb|go|rs|java|c|cpp|h|css|scss|html|json|ya?ml|toml|xml|sh|sql)$/.test(name)) return 'code'
  if (/\.(md|txt|log|csv|env|ini|conf|cfg)$/.test(name)) return 'text'
  if (/\.(pdf|docx?|xlsx?|pptx?)$/.test(name)) return 'doc'
  return 'file'
}

function kindClass(kind: string) {
  return ({
    folder: 'kind-folder',
    image: 'kind-image',
    video: 'kind-video',
    audio: 'kind-audio',
    archive: 'kind-archive',
    code: 'kind-code',
    text: 'kind-text',
    doc: 'kind-doc',
    file: 'kind-file',
  } as Record<string, string>)[kind] ?? 'kind-file'
}

function formatBytes(n?: number | null) {
  if (n == null) return '—'
  if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function extension(name: string) {
  const i = name.lastIndexOf('.')
  if (i <= 0) return ''
  return name.slice(i + 1).toUpperCase()
}

function downloadEntry(entry: FileEntry) {
  if (entry.is_dir) return
  transfers.enqueueDownload(entry.path, entry.name, entry.size_bytes ?? 0, scope.value)
  menuPath.value = null
}

async function loadRoots() {
  const { data } = await filesApi.roots()
  roots.value = data.roots
  const queryRoot = String(route.query.root ?? '')
  if (queryRoot && roots.value.some((r) => r.id === queryRoot)) {
    selectedRoot.value = queryRoot
  } else if (!selectedRoot.value && roots.value.length) {
    selectedRoot.value = roots.value[0].id
  }
}

async function load(path = '.') {
  if (!selectedRoot.value) return
  loading.value = true
  message.value = null
  menuPath.value = null
  try {
    const { data } = await filesApi.list(path, scope.value)
    entries.value = data.entries
    currentPath.value = data.path
    parentPath.value = data.parent
    if (selected.value && !data.entries.some((e) => e.path === selected.value?.path)) {
      selected.value = null
      infoPanel.value = null
    }
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Failed to list files') }
  } finally {
    loading.value = false
  }
}

async function switchRoot() {
  currentPath.value = '.'
  selected.value = null
  infoPanel.value = null
  search.value = ''
  await load('.')
}

function openDir(entry: FileEntry) {
  if (entry.is_dir) load(entry.path)
}

function goUp() {
  if (parentPath.value !== undefined) load(parentPath.value)
}

function goBreadcrumb(path: string) {
  load(path)
}

async function selectEntry(entry: FileEntry) {
  selected.value = entry
  menuPath.value = null
  try {
    const { data } = await filesApi.stat(entry.path, scope.value)
    infoPanel.value = data
  } catch {
    infoPanel.value = {
      name: entry.name,
      path: entry.path,
      is_dir: entry.is_dir,
      size_bytes: entry.size_bytes,
      mode: entry.mode,
      owner: entry.owner,
      group: entry.group,
      modified: entry.modified,
    }
  }
}

function openEntry(entry: FileEntry) {
  if (entry.is_dir) {
    openDir(entry)
    return
  }
  openFile(entry)
}

async function showInfo(entry: FileEntry) {
  await selectEntry(entry)
  menuPath.value = null
}

async function openFile(entry: FileEntry) {
  if (entry.is_dir) return
  actionKey.value = 'read'
  menuPath.value = null
  try {
    const { data } = await filesApi.read(entry.path, scope.value)
    editorPath.value = entry.path
    editorContent.value = data.content ?? ''
    editorMeta.value = data
    editorOpen.value = true
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Cannot open file') }
  } finally {
    actionKey.value = null
  }
}

async function saveFile() {
  actionKey.value = 'save'
  try {
    const { data } = await filesApi.write(editorPath.value, editorContent.value, scope.value)
    message.value = { type: data.success ? 'ok' : 'err', text: data.message }
    editorOpen.value = false
    await load(currentPath.value)
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Save failed') }
  } finally {
    actionKey.value = null
  }
}

async function mkdir() {
  if (!newFolderName.value.trim()) return
  const name = newFolderName.value.trim()
  const path = currentPath.value === '.' ? name : `${currentPath.value}/${name}`
  const { data } = await filesApi.mkdir(path, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  newFolderName.value = ''
  showNewFolder.value = false
  await load(currentPath.value)
}

async function remove(entry: FileEntry) {
  if (!confirm(`Delete ${entry.name}?`)) return
  const { data } = await filesApi.delete(entry.path, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  if (selected.value?.path === entry.path) {
    selected.value = null
    infoPanel.value = null
  }
  menuPath.value = null
  await load(currentPath.value)
}

async function chmodEntry(entry: FileEntry) {
  const mode = prompt(`chmod mode for ${entry.name}`, entry.mode?.replace(/^0/, '') || chmodMode.value)
  if (!mode) return
  chmodMode.value = mode
  const { data } = await filesApi.chmod(entry.path, mode, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  menuPath.value = null
  await load(currentPath.value)
  if (selected.value?.path === entry.path) await selectEntry(entry)
}

async function unzip(entry: FileEntry) {
  const { data } = await filesApi.unzip(entry.path, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  menuPath.value = null
  await load(currentPath.value)
}

function startRename(entry: FileEntry) {
  renameTarget.value = entry
  renameValue.value = entry.name
  menuPath.value = null
}

async function confirmRename() {
  if (!renameTarget.value || !renameValue.value.trim()) return
  const entry = renameTarget.value
  const parent = entry.path.includes('/') ? entry.path.replace(/\/[^/]+$/, '') : '.'
  const destination = parent === '.' ? renameValue.value.trim() : `${parent}/${renameValue.value.trim()}`
  const { data } = await filesApi.move(entry.path, destination, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  renameTarget.value = null
  await load(currentPath.value)
}

function startMove(entry: FileEntry) {
  moveTarget.value = entry
  moveDestination.value = entry.path
  menuPath.value = null
}

async function confirmMove() {
  if (!moveTarget.value || !moveDestination.value.trim()) return
  const { data } = await filesApi.move(moveTarget.value.path, moveDestination.value.trim(), scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  moveTarget.value = null
  await load(currentPath.value)
}

function toggleMenu(path: string, event: Event) {
  event.stopPropagation()
  menuPath.value = menuPath.value === path ? null : path
}

function onDocClick() {
  menuPath.value = null
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    menuPath.value = null
    editorOpen.value = false
    renameTarget.value = null
    moveTarget.value = null
    showNewFolder.value = false
  }
  if ((ev.key === 'Backspace' || ev.key === 'ArrowLeft') && (ev.metaKey || ev.altKey) && !editorOpen.value) {
    ev.preventDefault()
    goUp()
  }
}

onMounted(async () => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('keydown', onKeydown)
  await loadRoots()
  const queryPath = String(route.query.path ?? '.')
  await load(queryPath || '.')
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <DashboardLayout @refresh="() => { loadRoots(); load(currentPath) }">
    <div class="files-shell animate-fade-in flex min-h-0 flex-col gap-4">
      <header class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold tracking-tight text-slate-900 dark:text-white">Files</h1>
          <p class="text-sm text-surface-muted">Browse and manage approved server paths</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button type="button" class="files-btn" :disabled="parentPath === undefined" title="Go up" @click="goUp">↑ Up</button>
          <RouterLink v-if="canWrite" :to="uploadLink" class="files-btn-primary">Upload</RouterLink>
          <button v-if="canWrite" type="button" class="files-btn" @click="showNewFolder = !showNewFolder">New folder</button>
        </div>
      </header>

      <div class="files-toolbar">
        <label class="min-w-[12rem] flex-1 text-sm sm:max-w-xs">
          <span class="sr-only">Browse root</span>
          <select v-model="selectedRoot" class="files-input w-full" @change="switchRoot">
            <option v-for="root in roots" :key="root.id" :value="root.id">{{ root.label }} — {{ root.path }}</option>
          </select>
        </label>

        <label class="min-w-[10rem] flex-[2] text-sm">
          <span class="sr-only">Search</span>
          <input v-model="search" class="files-input w-full" type="search" placeholder="Filter current folder…" />
        </label>

        <label class="text-sm">
          <span class="sr-only">Sort</span>
          <select v-model="sortKey" class="files-input">
            <option value="name">Name</option>
            <option value="size">Size</option>
            <option value="modified">Modified</option>
            <option value="type">Type</option>
          </select>
        </label>

        <button type="button" class="files-btn" :title="sortDir === 'asc' ? 'Ascending' : 'Descending'" @click="sortDir = sortDir === 'asc' ? 'desc' : 'asc'">
          {{ sortDir === 'asc' ? 'A→Z' : 'Z→A' }}
        </button>

        <label class="flex items-center gap-2 px-1 text-xs text-surface-muted">
          <input v-model="showHidden" type="checkbox" class="rounded border-surface-border" />
          Hidden
        </label>

        <div class="files-view-toggle" role="group" aria-label="View mode">
          <button type="button" class="files-view-btn" :class="{ 'is-active': viewMode === 'list' }" title="List view" @click="viewMode = 'list'">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>
          </button>
          <button type="button" class="files-view-btn" :class="{ 'is-active': viewMode === 'grid' }" title="Grid view" @click="viewMode = 'grid'">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
          </button>
        </div>
      </div>

      <nav class="files-crumbs" aria-label="Breadcrumb">
        <template v-for="(crumb, index) in breadcrumbs" :key="crumb.path">
          <span v-if="index > 0" class="text-surface-muted/60">/</span>
          <button type="button" class="files-crumb" :class="{ 'is-current': index === breadcrumbs.length - 1 }" @click="goBreadcrumb(crumb.path)">
            {{ crumb.label }}
          </button>
        </template>
        <span class="ml-auto hidden text-xs text-surface-muted sm:inline">{{ folderCount }} folders · {{ fileCount }} files</span>
      </nav>

      <div v-if="showNewFolder && canWrite" class="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-teal-600/35 bg-teal-600/5 px-3 py-2">
        <input v-model="newFolderName" class="files-input min-w-[12rem] flex-1" placeholder="Folder name" @keydown.enter="mkdir" />
        <button type="button" class="files-btn-primary" @click="mkdir">Create</button>
        <button type="button" class="files-btn" @click="showNewFolder = false">Cancel</button>
      </div>

      <p v-if="message" class="rounded-lg px-3 py-2 text-sm" :class="message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'bg-red-500/10 text-red-700 dark:text-red-300'">
        {{ message.text }}
      </p>

      <div class="files-workspace">
        <div class="files-browser">
          <div v-if="loading" class="flex h-48 items-center justify-center text-sm text-surface-muted">Loading…</div>
          <div v-else-if="!filteredEntries.length" class="flex h-48 flex-col items-center justify-center gap-2 text-sm text-surface-muted">
            <IconFolder :size="36" icon-class="opacity-40" />
            <p>{{ search ? 'No matches in this folder.' : 'This folder is empty.' }}</p>
          </div>

          <div v-else-if="viewMode === 'list'" class="files-scroll">
            <table class="w-full text-left text-sm">
              <thead class="sticky top-0 z-10 border-b border-surface-border bg-surface-raised/95 backdrop-blur">
                <tr class="text-xs uppercase tracking-wide text-surface-muted">
                  <th class="px-4 py-2.5 font-medium">Name</th>
                  <th class="hidden px-3 py-2.5 font-medium sm:table-cell">Size</th>
                  <th class="hidden px-3 py-2.5 font-medium md:table-cell">Modified</th>
                  <th class="hidden px-3 py-2.5 font-medium lg:table-cell">Perms</th>
                  <th class="w-12 px-2 py-2.5" />
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="entry in filteredEntries"
                  :key="entry.path"
                  class="files-row group"
                  :class="{ 'is-selected': selected?.path === entry.path }"
                  @click="selectEntry(entry)"
                  @dblclick="openEntry(entry)"
                >
                  <td class="px-4 py-2">
                    <div class="flex min-w-0 items-center gap-3">
                      <span class="files-icon" :class="kindClass(fileKind(entry))">
                        <IconFolder v-if="entry.is_dir" :size="18" />
                        <span v-else class="text-[10px] font-semibold tracking-wide">{{ extension(entry.name).slice(0, 4) || 'FILE' }}</span>
                      </span>
                      <button
                        type="button"
                        class="truncate text-left font-medium"
                        :class="entry.is_dir ? 'text-teal-700 dark:text-teal-300' : 'text-slate-900 dark:text-slate-100'"
                        @click.stop="openEntry(entry)"
                      >
                        {{ entry.name }}
                      </button>
                    </div>
                  </td>
                  <td class="hidden px-3 py-2 text-surface-muted sm:table-cell">{{ entry.is_dir ? '—' : formatBytes(entry.size_bytes) }}</td>
                  <td class="hidden px-3 py-2 text-xs text-surface-muted md:table-cell">{{ formatDate(entry.modified) }}</td>
                  <td class="hidden px-3 py-2 font-mono text-xs text-surface-muted lg:table-cell">{{ entry.mode ?? '—' }}</td>
                  <td class="relative px-2 py-2 text-right">
                    <button
                      type="button"
                      class="files-more opacity-0 group-hover:opacity-100 focus:opacity-100"
                      :class="{ 'opacity-100': menuPath === entry.path }"
                      aria-label="Actions"
                      @click="toggleMenu(entry.path, $event)"
                    >⋮</button>
                    <div v-if="menuPath === entry.path" class="files-menu" @click.stop>
                      <button type="button" @click="openEntry(entry)">Open</button>
                      <button type="button" @click="showInfo(entry)">Details</button>
                      <button v-if="!entry.is_dir" type="button" @click="downloadEntry(entry)">Download</button>
                      <template v-if="canWrite">
                        <button type="button" @click="startRename(entry)">Rename</button>
                        <button type="button" @click="startMove(entry)">Move</button>
                        <button type="button" @click="chmodEntry(entry)">Permissions</button>
                        <button v-if="entry.name.toLowerCase().endsWith('.zip')" type="button" @click="unzip(entry)">Unzip</button>
                        <button type="button" class="is-danger" @click="remove(entry)">Delete</button>
                      </template>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-else class="files-scroll p-3">
            <div class="files-grid">
              <button
                v-for="entry in filteredEntries"
                :key="entry.path"
                type="button"
                class="files-tile group"
                :class="{ 'is-selected': selected?.path === entry.path }"
                @click="selectEntry(entry)"
                @dblclick="openEntry(entry)"
              >
                <span class="files-icon files-icon-lg" :class="kindClass(fileKind(entry))">
                  <IconFolder v-if="entry.is_dir" :size="28" />
                  <span v-else class="text-xs font-semibold tracking-wide">{{ extension(entry.name).slice(0, 4) || 'FILE' }}</span>
                </span>
                <span class="mt-2 w-full truncate text-sm font-medium text-slate-900 dark:text-slate-100">{{ entry.name }}</span>
                <span class="mt-0.5 text-[11px] text-surface-muted">{{ entry.is_dir ? 'Folder' : formatBytes(entry.size_bytes) }}</span>
                <span
                  class="files-more absolute right-2 top-2 opacity-0 group-hover:opacity-100"
                  :class="{ 'opacity-100': menuPath === entry.path }"
                  @click="toggleMenu(entry.path, $event)"
                >⋮</span>
                <div v-if="menuPath === entry.path" class="files-menu files-menu-grid" @click.stop>
                  <button type="button" @click="openEntry(entry)">Open</button>
                  <button type="button" @click="showInfo(entry)">Details</button>
                  <button v-if="!entry.is_dir" type="button" @click="downloadEntry(entry)">Download</button>
                  <template v-if="canWrite">
                    <button type="button" @click="startRename(entry)">Rename</button>
                    <button type="button" @click="startMove(entry)">Move</button>
                    <button type="button" @click="chmodEntry(entry)">Permissions</button>
                    <button v-if="entry.name.toLowerCase().endsWith('.zip')" type="button" @click="unzip(entry)">Unzip</button>
                    <button type="button" class="is-danger" @click="remove(entry)">Delete</button>
                  </template>
                </div>
              </button>
            </div>
          </div>
        </div>

        <aside v-if="infoPanel || selected" class="files-details">
          <div class="sticky top-0 space-y-4">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <p class="text-xs uppercase tracking-wide text-surface-muted">Details</p>
                <h2 class="truncate text-sm font-semibold text-slate-900 dark:text-white">{{ infoPanel?.name || selected?.name }}</h2>
              </div>
              <button type="button" class="files-btn !px-2 !py-1 text-xs" @click="selected = null; infoPanel = null">Close</button>
            </div>

            <div
              class="files-icon files-icon-xl mx-auto"
              :class="kindClass(fileKind(selected || { name: infoPanel?.name || '', path: '', is_dir: !!infoPanel?.is_dir }))"
            >
              <IconFolder v-if="infoPanel?.is_dir || selected?.is_dir" :size="36" />
              <span v-else class="text-sm font-semibold">{{ extension(infoPanel?.name || selected?.name || '').slice(0, 4) || 'FILE' }}</span>
            </div>

            <dl class="space-y-2 text-xs">
              <div>
                <dt class="text-surface-muted">Path</dt>
                <dd class="break-all font-mono text-[11px]">{{ infoPanel?.path || selected?.path }}</dd>
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div><dt class="text-surface-muted">Size</dt><dd>{{ formatBytes(infoPanel?.size_bytes ?? selected?.size_bytes) }}</dd></div>
                <div><dt class="text-surface-muted">Mode</dt><dd class="font-mono">{{ infoPanel?.mode || selected?.mode || '—' }}</dd></div>
                <div><dt class="text-surface-muted">Owner</dt><dd>{{ infoPanel?.owner || selected?.owner || '—' }}</dd></div>
                <div><dt class="text-surface-muted">Group</dt><dd>{{ infoPanel?.group || selected?.group || '—' }}</dd></div>
              </div>
              <div>
                <dt class="text-surface-muted">Modified</dt>
                <dd>{{ formatDate(infoPanel?.modified || selected?.modified) }}</dd>
              </div>
            </dl>

            <div class="flex flex-wrap gap-2">
              <button type="button" class="files-btn-primary flex-1 text-xs" @click="selected && openEntry(selected)">Open</button>
              <button v-if="selected && !selected.is_dir" type="button" class="files-btn flex-1 text-xs" @click="downloadEntry(selected)">Download</button>
            </div>
            <div v-if="canWrite && selected" class="flex flex-wrap gap-2">
              <button type="button" class="files-btn text-xs" @click="startRename(selected)">Rename</button>
              <button type="button" class="files-btn text-xs" @click="startMove(selected)">Move</button>
              <button type="button" class="files-btn text-xs" @click="chmodEntry(selected)">chmod</button>
              <button v-if="selected.name.toLowerCase().endsWith('.zip')" type="button" class="files-btn text-xs" @click="unzip(selected)">Unzip</button>
              <button type="button" class="files-btn text-xs text-red-600" @click="remove(selected)">Delete</button>
            </div>
          </div>
        </aside>
      </div>

      <div v-if="renameTarget && canWrite" class="files-dialog">
        <div class="files-dialog-panel">
          <h3 class="text-sm font-semibold">Rename</h3>
          <p class="mt-1 text-xs text-surface-muted">{{ renameTarget.name }}</p>
          <input v-model="renameValue" class="files-input mt-3 w-full" @keydown.enter="confirmRename" />
          <div class="mt-3 flex justify-end gap-2">
            <button type="button" class="files-btn" @click="renameTarget = null">Cancel</button>
            <button type="button" class="files-btn-primary" @click="confirmRename">Save</button>
          </div>
        </div>
      </div>

      <div v-if="moveTarget && canWrite" class="files-dialog">
        <div class="files-dialog-panel">
          <h3 class="text-sm font-semibold">Move</h3>
          <p class="mt-1 text-xs text-surface-muted">{{ moveTarget.name }}</p>
          <input v-model="moveDestination" class="files-input mt-3 w-full font-mono text-xs" @keydown.enter="confirmMove" />
          <div class="mt-3 flex justify-end gap-2">
            <button type="button" class="files-btn" @click="moveTarget = null">Cancel</button>
            <button type="button" class="files-btn-primary" @click="confirmMove">Move</button>
          </div>
        </div>
      </div>

      <div v-if="editorOpen" class="files-dialog">
        <div class="files-dialog-panel files-editor">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span class="truncate font-mono text-sm">{{ editorPath }}</span>
            <Badge v-if="editorMeta?.mode" size="sm">{{ editorMeta.mode }} · {{ editorMeta.owner }}:{{ editorMeta.group }}</Badge>
          </div>
          <textarea
            v-model="editorContent"
            class="h-[min(50vh,24rem)] w-full rounded-lg border border-surface-border bg-slate-950/95 p-3 font-mono text-xs text-slate-100"
            :readonly="!canWrite"
          />
          <div class="mt-3 flex justify-end gap-2">
            <button type="button" class="files-btn" @click="editorOpen = false">Close</button>
            <button v-if="canWrite" type="button" class="files-btn-primary" :disabled="actionKey === 'save'" @click="saveFile">Save</button>
          </div>
        </div>
      </div>

      <FileTransferQueue />
    </div>
  </DashboardLayout>
</template>

<style scoped>
.files-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 0.875rem;
  background:
    linear-gradient(135deg, rgb(15 23 42 / 0.02), transparent 40%),
    var(--color-surface-raised);
}
.dark .files-toolbar {
  background:
    linear-gradient(135deg, rgb(45 212 191 / 0.05), transparent 45%),
    var(--color-surface-raised);
}
.files-input {
  border-radius: 0.625rem;
  border: 1px solid var(--color-border);
  background: transparent;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
}
.files-btn,
.files-btn-primary,
.files-more,
.files-view-btn {
  border-radius: 0.625rem;
  border: 1px solid var(--color-border);
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}
.files-btn:hover:not(:disabled),
.files-more:hover,
.files-view-btn:hover { background: rgb(148 163 184 / 0.12); }
.files-btn:disabled { opacity: 0.45; }
.files-btn-primary {
  border-color: transparent;
  background: #0f766e;
  color: white;
  font-weight: 500;
}
.files-btn-primary:hover { background: #0d9488; }
.files-view-toggle {
  display: inline-flex;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 0.625rem;
}
.files-view-btn { border: 0; border-radius: 0; padding: 0.45rem 0.65rem; }
.files-view-btn.is-active { background: rgb(15 118 110 / 0.12); color: #0f766e; }
.dark .files-view-btn.is-active { color: #5eead4; }
.files-crumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
}
.files-crumb {
  border-radius: 0.375rem;
  padding: 0.15rem 0.4rem;
  color: var(--color-text-muted);
}
.files-crumb:hover { background: rgb(148 163 184 / 0.12); color: inherit; }
.files-crumb.is-current { color: inherit; font-weight: 600; }
.files-workspace { display: grid; gap: 1rem; min-height: 0; }
@media (min-width: 1024px) {
  .files-workspace { grid-template-columns: minmax(0, 1fr) 17rem; align-items: start; }
}
.files-browser {
  min-height: 20rem;
  max-height: min(70vh, 36rem);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 0.875rem;
  background: var(--color-surface-raised);
}
.files-scroll { height: 100%; max-height: min(70vh, 36rem); overflow: auto; }
.files-row {
  border-bottom: 1px solid color-mix(in srgb, var(--color-border) 70%, transparent);
  cursor: default;
  transition: background 0.12s ease;
}
.files-row:hover,
.files-row.is-selected { background: rgb(15 118 110 / 0.06); }
.files-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr));
  gap: 0.75rem;
}
.files-tile {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  border: 1px solid transparent;
  border-radius: 0.875rem;
  padding: 1rem 0.75rem 0.85rem;
  text-align: center;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
.files-tile:hover {
  border-color: var(--color-border);
  background: rgb(148 163 184 / 0.08);
  transform: translateY(-1px);
}
.files-tile.is-selected {
  border-color: rgb(15 118 110 / 0.45);
  background: rgb(15 118 110 / 0.08);
}
.files-icon {
  display: inline-flex;
  height: 2.25rem;
  width: 2.25rem;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 0.65rem;
}
.files-icon-lg { height: 3.25rem; width: 3.25rem; }
.files-icon-xl { height: 4.25rem; width: 4.25rem; }
.kind-folder { background: rgb(14 165 233 / 0.14); color: #0284c7; }
.kind-image { background: rgb(244 63 94 / 0.12); color: #e11d48; }
.kind-video { background: rgb(6 182 212 / 0.14); color: #0891b2; }
.kind-audio { background: rgb(234 179 8 / 0.14); color: #ca8a04; }
.kind-archive { background: rgb(245 158 11 / 0.14); color: #d97706; }
.kind-code { background: rgb(16 185 129 / 0.14); color: #059669; }
.kind-text { background: rgb(100 116 139 / 0.14); color: #475569; }
.kind-doc { background: rgb(59 130 246 / 0.14); color: #2563eb; }
.kind-file { background: rgb(148 163 184 / 0.14); color: #64748b; }
.files-more {
  display: inline-flex;
  height: 1.75rem;
  width: 1.75rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.5rem;
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  line-height: 1;
}
.files-menu {
  position: absolute;
  right: 0.5rem;
  top: 2.25rem;
  z-index: 20;
  min-width: 9rem;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-elevated);
}
.files-menu-grid { right: 0.35rem; top: 2.1rem; text-align: left; }
.files-menu button {
  display: block;
  width: 100%;
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-size: 0.75rem;
}
.files-menu button:hover { background: rgb(148 163 184 / 0.12); }
.files-menu button.is-danger { color: #dc2626; }
.files-details {
  border: 1px solid var(--color-border);
  border-radius: 0.875rem;
  background: var(--color-surface-raised);
  padding: 1rem;
  max-height: min(70vh, 36rem);
  overflow: auto;
}
.files-dialog {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgb(15 23 42 / 0.45);
  backdrop-filter: blur(4px);
}
.files-dialog-panel {
  width: min(32rem, 100%);
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  background: var(--color-surface-raised);
  padding: 1.25rem;
  box-shadow: var(--shadow-elevated);
  animation: files-pop 0.18s ease-out;
}
.files-editor { width: min(56rem, 100%); }
@keyframes files-pop {
  from { opacity: 0; transform: translateY(6px) scale(0.98); }
  to { opacity: 1; transform: none; }
}
</style>

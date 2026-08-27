<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import IconFolder from '@/components/icons/IconFolder.vue'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { useFileTransferStore } from '@/stores/fileTransfers'
import '@/assets/portal.css'

type Entry = {
  name: string
  path: string
  is_dir: boolean
  size_bytes?: number | null
  modified?: string | null
  mode?: string | null
}

type ClipboardMode = 'copy' | 'cut' | null

const route = useRoute()
const router = useRouter()
const transfers = useFileTransferStore()

const envId = computed(
  () => String(route.params.environmentId || route.query.env || ''),
)
const loading = ref(true)
const entries = ref<Entry[]>([])
const currentPath = ref(String(route.query.path || '.') || '.')
const parentPath = ref<string | null>(null)
const msg = ref('')
const err = ref('')
const usageLabel = ref('')
const usagePct = ref(0)
const newFolder = ref('')
const newFileName = ref('')
const showMkdir = ref(false)
const showNewFile = ref(false)
const showNewMenu = ref(false)
const showMobileNav = ref(false)
const showOverflow = ref(false)
const domain = ref('')
const stackLabel = ref('')
const search = ref('')
const selectedPaths = ref<Set<string>>(new Set())
const anchorPath = ref<string | null>(null)
const folderTree = ref<string[]>(['.', 'public'])
const clipboard = ref<{ mode: ClipboardMode; paths: string[] }>({ mode: null, paths: [] })
const ctx = ref<{
  open: boolean
  x: number
  y: number
  entry: Entry | null
}>({ open: false, x: 0, y: 0, entry: null })
const movePromptOpen = ref(false)
const moveDestination = ref('')
const moveBrowsePath = ref('.')
const moveBrowseEntries = ref<Entry[]>([])
const moveBrowseLoading = ref(false)
const moveBrowseParent = ref<string | null>(null)
const moveBusy = ref(false)

const breadcrumbs = computed(() => {
  const parts = currentPath.value === '.' ? [] : currentPath.value.split('/').filter(Boolean)
  const crumbs: Array<{ label: string; path: string }> = [{ label: 'Home', path: '.' }]
  let acc = ''
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part
    crumbs.push({ label: part, path: acc })
  }
  return crumbs
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  let list = [...entries.value]
  if (q) list = list.filter((e) => e.name.toLowerCase().includes(q))
  list.sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  return list
})

const selectedEntries = computed(() =>
  filtered.value.filter((e) => selectedPaths.value.has(e.path)),
)

const selectionCount = computed(() => selectedPaths.value.size)

const allVisibleSelected = computed(
  () => filtered.value.length > 0 && filtered.value.every((e) => selectedPaths.value.has(e.path)),
)

const sidebarFolders = computed(() => {
  const set = new Set<string>(['.', 'public', ...folderTree.value])
  if (currentPath.value && currentPath.value !== '.') set.add(currentPath.value)
  return [...set].sort((a, b) => {
    if (a === '.') return -1
    if (b === '.') return 1
    return a.localeCompare(b)
  })
})

const ctxTargets = computed(() => {
  if (ctx.value.entry && selectedPaths.value.has(ctx.value.entry.path) && selectedPaths.value.size > 1) {
    return selectedEntries.value
  }
  if (ctx.value.entry) return [ctx.value.entry]
  return selectedEntries.value
})

const ctxIsArchive = computed(() => {
  const t = ctxTargets.value
  return t.length === 1 && !t[0].is_dir && /\.(zip|tar|gz|tgz|rar|7z)$/i.test(t[0].name)
})

const ctxCanEdit = computed(() => {
  const t = ctxTargets.value
  return t.length === 1 && !t[0].is_dir
})

function formatSize(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso?: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

function fileType(entry: Entry) {
  if (entry.is_dir) return 'Folder'
  const i = entry.name.lastIndexOf('.')
  if (i <= 0) return 'File'
  return entry.name.slice(i + 1).toUpperCase()
}

function closeMenus() {
  showNewMenu.value = false
  showOverflow.value = false
  ctx.value = { ...ctx.value, open: false }
}

function closeContext() {
  ctx.value = { ...ctx.value, open: false }
}

async function loadUsage() {
  if (!envId.value) return
  try {
    const { data } = await customersApi.getEnvUsage(envId.value)
    const used = Number(data.storage_used_gb || 0)
    const limit = Number(data.storage_limit_gb || 0)
    usageLabel.value = `${used.toFixed(2)} / ${limit.toFixed(2)} GB`
    usagePct.value = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  } catch {
    usageLabel.value = ''
    usagePct.value = 0
  }
}

async function loadStack() {
  if (!envId.value) return
  try {
    const { data } = await customersApi.listEnvStacks(envId.value)
    const cur = data.current as { stack?: string; name?: string; stack_name?: string } | null
    stackLabel.value =
      cur && (cur.stack_name || cur.name || cur.stack)
        ? String(cur.stack_name || cur.name || cur.stack)
        : ''
  } catch {
    stackLabel.value = ''
  }
}

async function load() {
  if (!envId.value) {
    err.value = 'Missing environment. Open Files from Hosting Panel or your account.'
    loading.value = false
    return
  }
  loading.value = true
  err.value = ''
  closeContext()
  try {
    const { data } = await customersApi.listEnvFiles(envId.value, currentPath.value)
    entries.value = (data.entries || []) as Entry[]
    parentPath.value = data.parent
    currentPath.value = data.path || currentPath.value
    selectedPaths.value = new Set()
    anchorPath.value = null
    for (const e of entries.value) {
      if (e.is_dir) folderTree.value = [...new Set([...folderTree.value, e.path])].slice(0, 40)
    }
    document.title = `Files · ${domain.value || currentPath.value} · IFNOTUS`
    if (route.name === 'hosting-files') {
      void router.replace({
        name: 'hosting-files',
        params: { environmentId: envId.value },
        query: { path: currentPath.value },
      })
    } else {
      void router.replace({
        name: 'portal-files',
        query: { env: envId.value, path: currentPath.value },
      })
    }
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not load files.')
  } finally {
    loading.value = false
  }
}

async function hydrateEnv() {
  try {
    const { data } = await customersApi.environments()
    const hit = data.find((e) => e.id === envId.value) || data[0]
    domain.value = hit?.domain || ''
    return data
  } catch {
    domain.value = ''
    return [] as Array<{ id: string; domain?: string }>
  }
}

async function ensureEnvironment(): Promise<boolean> {
  if (envId.value) return true
  const list = await hydrateEnv()
  const first = list[0]
  if (!first?.id) {
    err.value = 'No hosting site found yet. Open your account and finish setup first.'
    loading.value = false
    return false
  }
  await router.replace({
    name: 'hosting-files',
    params: { environmentId: first.id },
    query: route.query.path ? { path: String(route.query.path) } : {},
  })
  return false
}

function openDir(path: string) {
  currentPath.value = path || '.'
  showMobileNav.value = false
  closeMenus()
  void load()
}

function selectRow(entry: Entry, ev?: MouseEvent) {
  closeMenus()
  const list = filtered.value
  if (ev?.shiftKey && anchorPath.value) {
    const a = list.findIndex((e) => e.path === anchorPath.value)
    const b = list.findIndex((e) => e.path === entry.path)
    if (a >= 0 && b >= 0) {
      const [lo, hi] = a < b ? [a, b] : [b, a]
      const next = new Set(selectedPaths.value)
      for (let i = lo; i <= hi; i++) next.add(list[i].path)
      selectedPaths.value = next
      return
    }
  }
  if (ev?.metaKey || ev?.ctrlKey) {
    const next = new Set(selectedPaths.value)
    if (next.has(entry.path)) next.delete(entry.path)
    else next.add(entry.path)
    selectedPaths.value = next
    anchorPath.value = entry.path
    return
  }
  selectedPaths.value = new Set([entry.path])
  anchorPath.value = entry.path
}

function togglePath(entry: Entry) {
  const next = new Set(selectedPaths.value)
  if (next.has(entry.path)) next.delete(entry.path)
  else next.add(entry.path)
  selectedPaths.value = next
  anchorPath.value = entry.path
}

function toggleSelectAll() {
  if (allVisibleSelected.value) {
    selectedPaths.value = new Set()
    anchorPath.value = null
    return
  }
  selectedPaths.value = new Set(filtered.value.map((e) => e.path))
}

function openEntry(entry: Entry) {
  closeContext()
  if (entry.is_dir) {
    openDir(entry.path)
    return
  }
  const href = `/account/files/edit?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(entry.path)}`
  window.open(href, `ifnotus-editor-${entry.path}`)
}

function onContextMenu(entry: Entry, ev: MouseEvent) {
  ev.preventDefault()
  ev.stopPropagation()
  if (!selectedPaths.value.has(entry.path)) {
    selectedPaths.value = new Set([entry.path])
    anchorPath.value = entry.path
  }
  const pad = 8
  const menuW = 220
  const menuH = 320
  let x = ev.clientX
  let y = ev.clientY
  if (x + menuW > window.innerWidth - pad) x = window.innerWidth - menuW - pad
  if (y + menuH > window.innerHeight - pad) y = window.innerHeight - menuH - pad
  ctx.value = { open: true, x, y, entry }
  showNewMenu.value = false
  showOverflow.value = false
}

function onBlankContext(ev: MouseEvent) {
  ev.preventDefault()
  ctx.value = { open: true, x: ev.clientX, y: ev.clientY, entry: null }
}

function setClipboard(mode: 'copy' | 'cut') {
  const paths = ctxTargets.value.map((e) => e.path)
  if (!paths.length) return
  clipboard.value = { mode, paths }
  msg.value = mode === 'copy' ? `Copied ${paths.length} item(s)` : `Cut ${paths.length} item(s)`
  closeContext()
}

async function pasteClipboard() {
  if (!clipboard.value.mode || !clipboard.value.paths.length) return
  const destDir = currentPath.value || '.'
  try {
    for (const source of clipboard.value.paths) {
      const name = source.includes('/') ? source.slice(source.lastIndexOf('/') + 1) : source
      const destination = destDir === '.' ? name : `${destDir}/${name}`
      if (clipboard.value.mode === 'copy') {
        await customersApi.copyEnvFile(envId.value, source, destination)
      } else {
        await customersApi.moveEnvFile(envId.value, source, destination)
      }
    }
    msg.value =
      clipboard.value.mode === 'copy'
        ? `Pasted ${clipboard.value.paths.length} item(s)`
        : `Moved ${clipboard.value.paths.length} item(s)`
    if (clipboard.value.mode === 'cut') clipboard.value = { mode: null, paths: [] }
    closeContext()
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Paste failed.')
  }
}

const moveBrowseFolders = computed(() =>
  moveBrowseEntries.value.filter((e) => e.is_dir).sort((a, b) => a.name.localeCompare(b.name)),
)

const moveBrowseCrumbs = computed(() => {
  const parts = moveBrowsePath.value === '.' ? [] : moveBrowsePath.value.split('/').filter(Boolean)
  const crumbs: Array<{ label: string; path: string }> = [{ label: 'Home', path: '.' }]
  let acc = ''
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part
    crumbs.push({ label: part, path: acc })
  }
  return crumbs
})

async function loadMoveBrowse(path: string) {
  if (!envId.value) return
  moveBrowseLoading.value = true
  try {
    const { data } = await customersApi.listEnvFiles(envId.value, path || '.')
    moveBrowseEntries.value = (data.entries || []) as Entry[]
    moveBrowsePath.value = data.path || path || '.'
    moveBrowseParent.value = data.parent ?? (moveBrowsePath.value === '.' ? null : '.')
    moveDestination.value = moveBrowsePath.value === '.' ? '.' : moveBrowsePath.value
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not browse folders.')
  } finally {
    moveBrowseLoading.value = false
  }
}

function beginMove() {
  const targets = ctxTargets.value
  if (!targets.length) return
  const start = currentPath.value || '.'
  moveDestination.value = start
  moveBrowsePath.value = start
  movePromptOpen.value = true
  closeContext()
  void loadMoveBrowse(start)
}

function closeMovePrompt() {
  movePromptOpen.value = false
  moveBusy.value = false
}

async function confirmMove() {
  const destRaw = moveDestination.value.trim().replace(/\/+$/, '')
  const dest = destRaw || '.'
  const targets = selectedEntries.value.length ? selectedEntries.value : ctxTargets.value
  if (!targets.length) return
  // Don't move a folder into itself or a descendant.
  for (const entry of targets) {
    if (entry.is_dir) {
      if (dest === entry.path || dest.startsWith(`${entry.path}/`)) {
        err.value = `Cannot move “${entry.name}” into itself.`
        return
      }
    }
    if (dest === (entry.path.includes('/') ? entry.path.slice(0, entry.path.lastIndexOf('/')) || '.' : '.')) {
      // Same folder — skip quietly for that item later
    }
  }
  moveBusy.value = true
  err.value = ''
  try {
    let moved = 0
    for (const entry of targets) {
      const parent = entry.path.includes('/')
        ? entry.path.slice(0, entry.path.lastIndexOf('/')) || '.'
        : '.'
      if (parent === dest) continue
      const destination = dest === '.' ? entry.name : `${dest}/${entry.name}`
      await customersApi.moveEnvFile(envId.value, entry.path, destination)
      moved += 1
    }
    msg.value = moved ? `Moved ${moved} item(s) to ${dest === '.' ? 'Home' : dest}` : 'Items are already in that folder.'
    closeMovePrompt()
    await load()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Move failed.')
  } finally {
    moveBusy.value = false
  }
}

async function createFolder() {
  const name = newFolder.value.trim().replace(/^\/+|\/+$/g, '')
  if (!name) return
  const path = currentPath.value === '.' ? name : `${currentPath.value}/${name}`
  try {
    await customersApi.mkdirEnv(envId.value, path)
    msg.value = `Created folder ${name}`
    newFolder.value = ''
    showMkdir.value = false
    showNewMenu.value = false
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not create folder.')
  }
}

async function createFile() {
  let name = newFileName.value.trim().replace(/^\/+|\/+$/g, '')
  if (!name) return
  if (name.includes('..') || name.includes('/')) {
    err.value = 'Use a simple file name (no folders in the name).'
    return
  }
  if (!name.includes('.')) name = `${name}.txt`
  const path = currentPath.value === '.' ? name : `${currentPath.value}/${name}`
  try {
    await customersApi.writeEnvFile(envId.value, path, '')
    msg.value = `Created ${name}`
    newFileName.value = ''
    showNewFile.value = false
    showNewMenu.value = false
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not create file.')
  }
}

async function removeTargets(targets: Entry[]) {
  if (!targets.length) return
  const label = targets.length === 1 ? targets[0].name : `${targets.length} items`
  if (!confirm(`Delete ${label}?`)) return
  try {
    for (const entry of targets) await customersApi.deleteEnvFile(envId.value, entry.path)
    msg.value = `Deleted ${targets.length} item(s)`
    closeContext()
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Delete failed.')
  }
}

async function renameEntry(entry: Entry) {
  const next = prompt('New name', entry.name)?.trim()
  if (!next || next === entry.name) return
  if (next.includes('/') || next.includes('..')) {
    err.value = 'Use a simple name without folders.'
    return
  }
  const parent = entry.path.includes('/') ? entry.path.slice(0, entry.path.lastIndexOf('/')) : '.'
  const destination = parent === '.' ? next : `${parent}/${next}`
  try {
    await customersApi.moveEnvFile(envId.value, entry.path, destination)
    msg.value = `Renamed to ${next}`
    closeContext()
    await load()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Rename failed.')
  }
}

async function unzipEntry(entry: Entry, extractHere = false) {
  try {
    await customersApi.unzipEnvFile(envId.value, entry.path, { extractHere })
    msg.value = extractHere ? `Extracted ${entry.name} here` : `Extracted ${entry.name}`
    closeContext()
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Extract failed.')
  }
}

async function compressTargets(targets: Entry[]) {
  const paths = targets.map((e) => e.path)
  if (!paths.length) return
  try {
    await customersApi.compressEnvFiles(envId.value, paths, {
      destinationDir: currentPath.value || '.',
    })
    msg.value = 'Archive created'
    closeContext()
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Compress failed.')
  }
}

function downloadEntry(entry: Entry) {
  if (entry.is_dir) return
  transfers.enqueueDownload(entry.path, entry.name, entry.size_bytes || 0, {
    environmentId: envId.value,
  })
  msg.value = `Queued download: ${entry.name}`
  closeContext()
}

function pickUpload() {
  if (!envId.value) return
  const href = `/account/files/upload?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(currentPath.value || '.')}`
  window.open(href, `ifnotus-upload-${envId.value}`)
}

function backToHosting() {
  if (!envId.value) {
    void router.push({ name: 'portal-dashboard' })
    return
  }
  void router.push({ name: 'hosting-panel', params: { environmentId: envId.value } })
}

function onKeydown(ev: KeyboardEvent) {
  const tag = (ev.target as HTMLElement | null)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'a') {
    ev.preventDefault()
    selectedPaths.value = new Set(filtered.value.map((e) => e.path))
  }
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'c') {
    ev.preventDefault()
    if (selectedEntries.value.length) {
      clipboard.value = { mode: 'copy', paths: selectedEntries.value.map((e) => e.path) }
      msg.value = `Copied ${selectedEntries.value.length} item(s)`
    }
  }
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'x') {
    ev.preventDefault()
    if (selectedEntries.value.length) {
      clipboard.value = { mode: 'cut', paths: selectedEntries.value.map((e) => e.path) }
      msg.value = `Cut ${selectedEntries.value.length} item(s)`
    }
  }
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'v') {
    ev.preventDefault()
    void pasteClipboard()
  }
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    if (selectedEntries.value.length) {
      ev.preventDefault()
      void removeTargets(selectedEntries.value)
    }
  }
  if (ev.key === 'Escape') closeMenus()
  if (ev.key === 'Enter' && selectedEntries.value.length === 1) {
    openEntry(selectedEntries.value[0])
  }
}

watch(
  () => [route.query.env, route.params.environmentId],
  () => {
    void (async () => {
      if (!(await ensureEnvironment())) return
      await hydrateEnv()
      await load()
      await loadUsage()
      await loadStack()
    })()
  },
)

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('click', closeContext)
  if (!(await ensureEnvironment())) return
  await hydrateEnv()
  await load()
  await loadUsage()
  await loadStack()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('click', closeContext)
})
</script>

<template>
  <div class="fm" @click="closeMenus">
    <header class="fm-bar" @click.stop>
      <div class="identity">
        <button type="button" class="nav-toggle" aria-label="Folders" @click="showMobileNav = !showMobileNav">
          ☰
        </button>
        <button type="button" class="mark" @click="backToHosting">IF</button>
        <div class="id-text">
          <strong>File manager</strong>
          <p>{{ domain || 'Your site' }}<span v-if="stackLabel"> · {{ stackLabel }}</span></p>
        </div>
      </div>

      <nav class="crumbs" aria-label="Path">
        <button
          v-for="(c, i) in breadcrumbs"
          :key="c.path"
          type="button"
          @click="openDir(c.path)"
        >
          <span v-if="i" class="sep">/</span>{{ c.label }}
        </button>
      </nav>

      <div class="tools">
        <label class="search">
          <span class="sr">Search</span>
          <input v-model="search" type="search" placeholder="Search this folder" />
        </label>
        <div v-if="usageLabel" class="usage" :title="usageLabel">
          <div class="usage-bar"><i :style="{ width: `${usagePct}%` }" /></div>
          <span>{{ usageLabel }}</span>
        </div>
        <span v-if="selectionCount" class="sel-pill">{{ selectionCount }} selected</span>
        <button type="button" class="btn" @click="load">Refresh</button>
        <div class="new-wrap">
          <button type="button" class="btn" @click.stop="showNewMenu = !showNewMenu; showOverflow = false">
            New
          </button>
          <div v-if="showNewMenu" class="menu" @click.stop>
            <button type="button" @click="showMkdir = true; showNewFile = false; showNewMenu = false">Folder</button>
            <button type="button" @click="showNewFile = true; showMkdir = false; showNewMenu = false">File</button>
          </div>
        </div>
        <button type="button" class="btn primary" :disabled="!envId" @click="pickUpload">Upload</button>
        <button type="button" class="btn more" aria-label="More" @click.stop="showOverflow = !showOverflow">⋯</button>
        <div v-if="showOverflow" class="menu overflow" @click.stop>
          <button type="button" :disabled="!selectionCount" @click="compressTargets(selectedEntries); showOverflow = false">
            Compress selected
          </button>
          <button type="button" :disabled="!clipboard.mode" @click="pasteClipboard(); showOverflow = false">
            Paste here
          </button>
          <button type="button" :disabled="!selectionCount" @click="removeTargets(selectedEntries); showOverflow = false">
            Delete selected
          </button>
          <button type="button" @click="backToHosting(); showOverflow = false">Hosting panel</button>
        </div>
      </div>
    </header>

    <div v-if="showMkdir" class="inline-form" @click.stop>
      <input v-model="newFolder" placeholder="Folder name" @keyup.enter="createFolder" />
      <button type="button" class="btn primary" @click="createFolder">Create</button>
      <button type="button" class="btn" @click="showMkdir = false">Cancel</button>
    </div>
    <div v-if="showNewFile" class="inline-form" @click.stop>
      <input v-model="newFileName" placeholder="File name (e.g. index.html)" @keyup.enter="createFile" />
      <button type="button" class="btn primary" @click="createFile">Create</button>
      <button type="button" class="btn" @click="showNewFile = false">Cancel</button>
    </div>
    <div v-if="movePromptOpen" class="move-modal" @click.self="closeMovePrompt">
      <div class="move-dialog" @click.stop>
        <header class="move-head">
          <h3>Move {{ selectionCount || ctxTargets.length }} item(s)</h3>
          <button type="button" class="btn" @click="closeMovePrompt">Close</button>
        </header>
        <nav class="move-crumbs" aria-label="Destination path">
          <button
            v-for="c in moveBrowseCrumbs"
            :key="c.path"
            type="button"
            class="crumb"
            @click="loadMoveBrowse(c.path)"
          >
            {{ c.label }}
          </button>
        </nav>
        <p class="move-dest muted">
          Destination:
          <strong>{{ moveDestination === '.' ? 'Home' : moveDestination }}</strong>
        </p>
        <div class="move-list">
          <p v-if="moveBrowseLoading" class="muted pad">Loading folders…</p>
          <template v-else>
            <button
              v-if="moveBrowseParent != null"
              type="button"
              class="move-row"
              @click="loadMoveBrowse(moveBrowseParent || '.')"
            >
              <IconFolder :size="18" variant="windows" />
              ↑ Parent folder
            </button>
            <button
              v-for="folder in moveBrowseFolders"
              :key="folder.path"
              type="button"
              class="move-row"
              @click="loadMoveBrowse(folder.path)"
              @dblclick="loadMoveBrowse(folder.path)"
            >
              <IconFolder :size="18" variant="windows" />
              <span>{{ folder.name }}</span>
              <span class="move-open">Open</span>
            </button>
            <p v-if="!moveBrowseFolders.length" class="muted pad">No subfolders here. You can move into this folder.</p>
          </template>
        </div>
        <footer class="move-foot">
          <button type="button" class="btn primary" :disabled="moveBusy" @click="confirmMove">
            {{ moveBusy ? 'Moving…' : 'Move here' }}
          </button>
          <button type="button" class="btn" :disabled="moveBusy" @click="closeMovePrompt">Cancel</button>
        </footer>
      </div>
    </div>

    <p v-if="msg" class="flash ok">{{ msg }}</p>
    <p v-if="err" class="flash bad">{{ err }}</p>

    <div class="fm-body">
      <aside class="nav" :class="{ open: showMobileNav }" @click.stop>
        <p class="nav-label">Places</p>
        <button type="button" class="nav-item" :class="{ on: currentPath === '.' }" @click="openDir('.')">
          <IconFolder :size="18" variant="windows" /> Home
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ on: currentPath === 'public' }"
          @click="openDir('public')"
        >
          <IconFolder :size="18" variant="windows" /> public
        </button>
        <p class="nav-label">Folders</p>
        <button
          v-for="folder in sidebarFolders.filter((f) => f !== '.' && f !== 'public')"
          :key="folder"
          type="button"
          class="nav-item"
          :class="{ on: currentPath === folder }"
          @click="openDir(folder)"
        >
          <IconFolder :size="18" variant="windows" />
          <span class="truncate">{{ folder }}</span>
        </button>
      </aside>
      <div v-if="showMobileNav" class="nav-backdrop" @click="showMobileNav = false" />

      <main class="pane" @contextmenu="onBlankContext">
        <FileTransferQueue class="queue" />
        <p class="hint pad">
          Click to select · Ctrl/Cmd+click multi-select · Shift+click range · Double-click to open · Right-click for actions
        </p>
        <p v-if="loading" class="muted pad">Loading…</p>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th class="check">
                  <input
                    type="checkbox"
                    :checked="allVisibleSelected"
                    :indeterminate="selectionCount > 0 && !allVisibleSelected"
                    aria-label="Select all"
                    @change="toggleSelectAll"
                    @click.stop
                  />
                </th>
                <th class="name">Name</th>
                <th class="type hide-sm">Type</th>
                <th class="size">Size</th>
                <th class="mod hide-sm">Modified</th>
                <th class="mode hide-md">Mode</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="parentPath != null" class="parent">
                <td colspan="6">
                  <button type="button" class="row-open" @click="openDir(parentPath || '.')">
                    ↑ Parent folder
                  </button>
                </td>
              </tr>
              <tr
                v-for="entry in filtered"
                :key="entry.path"
                :class="{ selected: selectedPaths.has(entry.path) }"
                @click.stop="selectRow(entry, $event)"
                @dblclick.stop="openEntry(entry)"
                @contextmenu="onContextMenu(entry, $event)"
              >
                <td class="check" @click.stop>
                  <input
                    type="checkbox"
                    :checked="selectedPaths.has(entry.path)"
                    :aria-label="`Select ${entry.name}`"
                    @change="togglePath(entry)"
                  />
                </td>
                <td class="name">
                  <span class="row-label">
                    <IconFolder v-if="entry.is_dir" :size="20" variant="windows" />
                    <span v-else class="file-badge">{{ fileType(entry).slice(0, 4) }}</span>
                    <span>{{ entry.name }}</span>
                  </span>
                </td>
                <td class="type hide-sm">{{ fileType(entry) }}</td>
                <td class="size mono">{{ entry.is_dir ? '—' : formatSize(entry.size_bytes) }}</td>
                <td class="mod hide-sm mono">{{ formatDate(entry.modified) }}</td>
                <td class="mode hide-md mono">{{ entry.mode || '—' }}</td>
              </tr>
              <tr v-if="!filtered.length">
                <td colspan="6" class="muted pad">This folder is empty. Upload files or create a folder.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </main>
    </div>

    <div
      v-if="ctx.open"
      class="ctx-menu"
      :style="{ left: `${ctx.x}px`, top: `${ctx.y}px` }"
      @click.stop
      @contextmenu.prevent
    >
      <template v-if="ctxTargets.length">
        <button
          v-if="ctxTargets.length === 1"
          type="button"
          @click="openEntry(ctxTargets[0])"
        >
          {{ ctxTargets[0].is_dir ? 'Open folder' : 'Open / edit' }}
        </button>
        <button v-if="ctxCanEdit" type="button" @click="downloadEntry(ctxTargets[0])">Download</button>
        <hr />
        <button type="button" @click="setClipboard('copy')">Copy</button>
        <button type="button" @click="setClipboard('cut')">Cut</button>
        <button type="button" :disabled="!clipboard.mode" @click="pasteClipboard">Paste</button>
        <button type="button" @click="beginMove">Move to…</button>
        <button
          v-if="ctxTargets.length === 1"
          type="button"
          @click="renameEntry(ctxTargets[0])"
        >
          Rename
        </button>
        <hr />
        <button type="button" @click="compressTargets(ctxTargets)">Compress</button>
        <button
          v-if="ctxIsArchive"
          type="button"
          @click="unzipEntry(ctxTargets[0], false)"
        >
          Extract
        </button>
        <button
          v-if="ctxIsArchive"
          type="button"
          @click="unzipEntry(ctxTargets[0], true)"
        >
          Extract here
        </button>
        <hr />
        <button type="button" class="danger" @click="removeTargets(ctxTargets)">Delete</button>
      </template>
      <template v-else>
        <button type="button" :disabled="!clipboard.mode" @click="pasteClipboard">Paste</button>
        <button type="button" @click="showMkdir = true; closeContext()">New folder</button>
        <button type="button" @click="showNewFile = true; closeContext()">New file</button>
        <button type="button" @click="pickUpload(); closeContext()">Upload</button>
        <button type="button" @click="load(); closeContext()">Refresh</button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.fm {
  --fm-bg: #e8eef4;
  --fm-panel: #ffffff;
  --fm-ink: #0f172a;
  --fm-muted: #64748b;
  --fm-line: #d5dde8;
  --fm-accent: #1e3a5f;
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #eef3f8 0%, var(--fm-bg) 40%, #e4ebf3 100%);
  color: var(--fm-ink);
  font-family: Figtree, "Segoe UI", sans-serif;
  overflow-x: hidden;
  user-select: none;
}
.fm-bar {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.4fr) minmax(0, 1.6fr);
  gap: 0.65rem;
  align-items: center;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--fm-line);
  background: color-mix(in srgb, var(--fm-panel) 92%, transparent);
  backdrop-filter: blur(8px);
  position: sticky;
  top: 0;
  z-index: 20;
}
.identity { display: flex; align-items: center; gap: 0.55rem; min-width: 0; }
.mark {
  width: 2.1rem;
  height: 2.1rem;
  border: none;
  border-radius: 0.45rem;
  background: var(--fm-accent);
  color: #fff;
  font-weight: 800;
  font-size: 0.7rem;
  cursor: pointer;
  flex-shrink: 0;
}
.id-text { min-width: 0; }
.id-text strong { display: block; font-size: 0.9rem; }
.id-text p {
  margin: 0;
  font-size: 0.72rem;
  color: var(--fm-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nav-toggle {
  display: none;
  border: 1px solid var(--fm-line);
  background: var(--fm-panel);
  border-radius: 0.4rem;
  width: 2rem;
  height: 2rem;
  cursor: pointer;
}
.crumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.1rem;
  min-width: 0;
}
.crumbs button {
  border: none;
  background: none;
  color: var(--fm-accent);
  font-weight: 650;
  font-size: 0.82rem;
  cursor: pointer;
  padding: 0.15rem 0.2rem;
}
.sep { color: #94a3b8; margin-right: 0.15rem; }
.tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  justify-content: flex-end;
  position: relative;
}
.search input {
  width: min(11rem, 28vw);
  border: 1px solid var(--fm-line);
  border-radius: 0.4rem;
  padding: 0.4rem 0.55rem;
  font-size: 0.8rem;
  background: var(--fm-panel);
}
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.usage {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
  color: var(--fm-muted);
  background: var(--fm-panel);
  border: 1px solid var(--fm-line);
  border-radius: 999px;
  padding: 0.25rem 0.55rem;
}
.usage-bar {
  width: 2.5rem;
  height: 0.35rem;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}
.usage-bar i {
  display: block;
  height: 100%;
  background: var(--fm-accent);
}
.sel-pill {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--fm-accent);
  background: #e8f1fb;
  border-radius: 999px;
  padding: 0.28rem 0.55rem;
}
.btn {
  border: 1px solid var(--fm-line);
  background: var(--fm-panel);
  color: #334155;
  border-radius: 0.4rem;
  font-size: 0.78rem;
  font-weight: 650;
  padding: 0.4rem 0.65rem;
  cursor: pointer;
}
.btn.primary { background: var(--fm-accent); color: #fff; border-color: transparent; }
.btn.more { padding-inline: 0.5rem; }
.new-wrap { position: relative; }
.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 0.25rem);
  min-width: 10rem;
  background: var(--fm-panel);
  border: 1px solid var(--fm-line);
  border-radius: 0.5rem;
  box-shadow: 0 10px 30px rgb(15 23 42 / 0.1);
  z-index: 30;
  padding: 0.3rem;
  display: grid;
}
.menu button {
  border: none;
  background: none;
  text-align: left;
  padding: 0.45rem 0.55rem;
  border-radius: 0.35rem;
  font-size: 0.8rem;
  cursor: pointer;
}
.menu button:hover { background: #f1f5f9; }
.menu button:disabled { opacity: 0.45; cursor: not-allowed; }
.inline-form {
  display: flex;
  gap: 0.45rem;
  padding: 0.55rem 0.85rem;
  border-bottom: 1px solid var(--fm-line);
  background: var(--fm-panel);
}
.inline-form input {
  flex: 1;
  border: 1px solid var(--fm-line);
  border-radius: 0.4rem;
  padding: 0.45rem 0.6rem;
}
.flash { margin: 0; padding: 0.45rem 0.85rem; font-size: 0.82rem; }
.flash.ok { color: #047857; background: #ecfdf5; }
.flash.bad { color: #b91c1c; background: #fef2f2; }
.fm-body {
  flex: 1;
  display: grid;
  grid-template-columns: 14rem minmax(0, 1fr);
  min-height: 0;
}
.nav {
  border-right: 1px solid var(--fm-line);
  background: color-mix(in srgb, var(--fm-panel) 88%, #e8eef4);
  padding: 0.75rem 0.55rem;
  overflow: auto;
}
.nav-label {
  margin: 0.65rem 0.45rem 0.25rem;
  font-size: 0.65rem;
  font-weight: 750;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--fm-muted);
}
.nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  border: none;
  background: none;
  text-align: left;
  padding: 0.4rem 0.45rem;
  border-radius: 0.4rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: inherit;
  cursor: pointer;
}
.nav-item:hover, .nav-item.on { background: #dfe8f2; }
.nav-backdrop { display: none; }
.pane { min-width: 0; display: flex; flex-direction: column; overflow: auto; }
.queue { margin: 0.65rem 0.85rem 0; }
.hint {
  margin: 0.35rem 0.85rem 0;
  font-size: 0.74rem;
  color: var(--fm-muted);
}
.table-wrap { padding: 0.65rem 0.85rem 1.5rem; }
.table {
  width: 100%;
  border-collapse: collapse;
  background: var(--fm-panel);
  border: 1px solid var(--fm-line);
  border-radius: 0.65rem;
  overflow: hidden;
}
.table th, .table td {
  padding: 0.55rem 0.7rem;
  border-bottom: 1px solid #eef2f6;
  text-align: left;
  font-size: 0.84rem;
}
.table th {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fm-muted);
  background: #f8fafc;
}
.table tr.selected { background: #e8f1fb; }
.table tbody tr { cursor: default; }
.table tbody tr:hover { background: #f4f8fc; }
.table tbody tr.selected:hover { background: #dde9f8; }
.check { width: 2.2rem; }
.row-open, .row-label {
  border: none;
  background: none;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font: inherit;
  color: inherit;
  padding: 0;
  max-width: 100%;
}
.row-open { cursor: pointer; }
.file-badge {
  display: inline-flex;
  min-width: 2rem;
  justify-content: center;
  font-size: 0.62rem;
  font-weight: 800;
  color: var(--fm-accent);
  background: #e8eef5;
  border-radius: 0.3rem;
  padding: 0.15rem 0.3rem;
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; color: var(--fm-muted); }
.muted { color: var(--fm-muted); }
.pad { padding: 1rem; }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ctx-menu {
  position: fixed;
  z-index: 80;
  min-width: 12rem;
  background: var(--fm-panel);
  border: 1px solid var(--fm-line);
  border-radius: 0.55rem;
  box-shadow: 0 14px 40px rgb(15 23 42 / 0.16);
  padding: 0.3rem;
  display: grid;
}
.ctx-menu button {
  border: none;
  background: none;
  text-align: left;
  padding: 0.48rem 0.65rem;
  border-radius: 0.35rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: inherit;
  cursor: pointer;
}
.ctx-menu button:hover { background: #eef3f8; }
.ctx-menu button:disabled { opacity: 0.4; cursor: not-allowed; }
.ctx-menu button.danger { color: #b91c1c; }
.ctx-menu hr {
  border: none;
  border-top: 1px solid var(--fm-line);
  margin: 0.25rem 0.35rem;
}

.move-modal {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgb(15 23 42 / 0.45);
}
.move-dialog {
  width: min(28rem, 100%);
  max-height: min(34rem, 88vh);
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  background: var(--fm-panel);
  border: 1px solid var(--fm-line);
  border-radius: 0.75rem;
  box-shadow: 0 18px 50px rgb(15 23 42 / 0.25);
  padding: 0.85rem;
}
.move-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.move-head h3 {
  margin: 0;
  font-size: 1rem;
}
.move-crumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.move-crumbs .crumb {
  border: none;
  background: #eef3f8;
  color: var(--fm-accent);
  border-radius: 0.35rem;
  padding: 0.25rem 0.5rem;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}
.move-crumbs .crumb:hover { background: #dfe8f2; }
.move-dest {
  margin: 0;
  font-size: 0.82rem;
}
.move-list {
  flex: 1;
  min-height: 10rem;
  max-height: 18rem;
  overflow: auto;
  border: 1px solid var(--fm-line);
  border-radius: 0.5rem;
  background: #f8fafc;
}
.move-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.55rem 0.7rem;
  border: none;
  border-bottom: 1px solid var(--fm-line);
  background: transparent;
  text-align: left;
  cursor: pointer;
  font-size: 0.88rem;
  color: inherit;
}
.move-row:hover { background: #eef3f8; }
.move-row .move-open {
  margin-left: auto;
  font-size: 0.72rem;
  color: var(--fm-muted);
}
.move-foot {
  display: flex;
  gap: 0.45rem;
  justify-content: flex-end;
}

@media (max-width: 1100px) {
  .fm-bar { grid-template-columns: 1fr; }
  .tools { justify-content: flex-start; }
  .hide-md { display: none; }
}
@media (max-width: 860px) {
  .nav-toggle { display: inline-flex; align-items: center; justify-content: center; }
  .fm-body { grid-template-columns: 1fr; }
  .nav {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(16rem, 86vw);
    z-index: 40;
    transform: translateX(-105%);
    transition: transform 0.2s ease;
    box-shadow: 8px 0 30px rgb(15 23 42 / 0.15);
  }
  .nav.open { transform: translateX(0); }
  .nav-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: rgb(15 23 42 / 0.35);
    z-index: 35;
  }
  .hide-sm { display: none; }
  .search input { width: 100%; min-width: 8rem; }
}
</style>

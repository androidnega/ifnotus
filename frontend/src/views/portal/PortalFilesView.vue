<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { useFileTransferStore } from '@/stores/fileTransfers'
import { hostnameNow, isCustomerCpanelHost } from '@/lib/platformHosts'
import '@/assets/portal.css'

type Entry = {
  name: string
  path: string
  is_dir: boolean
  size_bytes?: number | null
  modified?: string | null
  mode?: string | null
}

type TrashEntry = {
  trash_id: string
  original_path: string
  display_name: string
  item_type: string
  size_bytes?: number | null
  deleted_at: string
  deleted_by?: string | null
}

type ClipboardMode = 'copy' | 'cut' | null

const route = useRoute()
const transfers = useFileTransferStore()

const props = withDefaults(
  defineProps<{
    environmentId?: string
    embedded?: boolean
  }>(),
  {
    environmentId: '',
    embedded: false,
  },
)

const fileInputRef = ref<HTMLInputElement | null>(null)

const resolvedEnvId = ref('')
const envId = computed(() => {
  if (props.environmentId) return props.environmentId
  if (route.params.environmentId) return String(route.params.environmentId)
  if (route.query.env) return String(route.query.env)
  if (resolvedEnvId.value) return resolvedEnvId.value
  const stored = typeof window !== 'undefined' ? localStorage.getItem('tenant_env_id') : ''
  return stored || ''
})

function normalizeVirtualPath(pathStr: string): string {
  if (!pathStr) return '.'
  if (pathStr === '__trash__') return '__trash__'
  let clean = pathStr.replace(/^[./\\]+/, '').replace(/[/\\]+$/, '')
  if (!clean || clean === 'public' || clean === 'public_html' || clean === 'web') return '.'
  return clean
}

const loading = ref(true)
const entries = ref<Entry[]>([])
const trashEntries = ref<TrashEntry[]>([])
const trashTotalBytes = ref(0)
const currentPath = ref(normalizeVirtualPath(String(route.query.path || '.')))
const manualPath = ref('/')
const isTrashMode = computed(() => currentPath.value === '__trash__')
const parentPath = ref<string | null>(null)
const msg = ref('')
const err = ref('')
const lastMovedTrash = ref<{ name: string; paths: string[] } | null>(null)
const usageLabel = ref('')
const newFolder = ref('')
const newFileName = ref('')
const showMkdirModal = ref(false)
const showNewFileModal = ref(false)
const domain = ref('')
const search = ref('')
const selectedPaths = ref<Set<string>>(new Set())
const anchorPath = ref<string | null>(null)
const folderTree = ref<string[]>(['.'])
const treeCollapsed = ref(false)
const clipboard = ref<{ mode: ClipboardMode; paths: string[] }>({ mode: null, paths: [] })

// Navigation history
const historyStack = ref<string[]>(['.'])
const historyIndex = ref(0)

const ctx = ref<{
  open: boolean
  x: number
  y: number
  entry: Entry | null
  trashEntry: TrashEntry | null
}>({ open: false, x: 0, y: 0, entry: null, trashEntry: null })

// Modals
const movePromptOpen = ref(false)
const moveDestination = ref('.')
const moveBrowsePath = ref('.')
const moveBrowseEntries = ref<Entry[]>([])
const moveBrowseLoading = ref(false)
const moveBrowseParent = ref<string | null>(null)
const moveBusy = ref(false)

const renameModal = ref<{
  open: boolean
  entry: Entry | null
  newName: string
  busy: boolean
}>({ open: false, entry: null, newName: '', busy: false })

const chmodModal = ref<{
  open: boolean
  entry: Entry | null
  u_r: boolean
  u_w: boolean
  u_x: boolean
  g_r: boolean
  g_w: boolean
  g_x: boolean
  o_r: boolean
  o_w: boolean
  o_x: boolean
  busy: boolean
}>({
  open: false,
  entry: null,
  u_r: true,
  u_w: true,
  u_x: false,
  g_r: true,
  g_w: false,
  g_x: false,
  o_r: true,
  o_w: false,
  o_x: false,
  busy: false,
})

const viewModal = ref<{
  open: boolean
  entry: Entry | null
  content: string
  loading: boolean
}>({
  open: false,
  entry: null,
  content: '',
  loading: false,
})

const conflictModal = ref<{
  open: boolean
  trashEntry: TrashEntry | null
  busy: boolean
}>({ open: false, trashEntry: null, busy: false })

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (isTrashMode.value) {
    let list = [...trashEntries.value]
    if (q) {
      list = list.filter(
        (e) =>
          e.display_name.toLowerCase().includes(q) || e.original_path.toLowerCase().includes(q),
      )
    }
    return list
  }
  let list = [...entries.value]
  if (q) list = list.filter((e) => e.name.toLowerCase().includes(q))
  list.sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  return list
})

const selectedEntries = computed(() => {
  if (isTrashMode.value) return []
  return (filtered.value as Entry[]).filter((e) => selectedPaths.value.has(e.path))
})

const selectedTrashEntries = computed(() => {
  if (!isTrashMode.value) return []
  return (filtered.value as TrashEntry[]).filter((e) => selectedPaths.value.has(e.trash_id))
})

const selectionCount = computed(() => selectedPaths.value.size)

const allVisibleSelected = computed(() => {
  if (filtered.value.length === 0) return false
  if (isTrashMode.value) {
    return (filtered.value as TrashEntry[]).every((e) => selectedPaths.value.has(e.trash_id))
  }
  return (filtered.value as Entry[]).every((e) => selectedPaths.value.has(e.path))
})

const sidebarFolders = computed(() => {
  const set = new Set<string>(folderTree.value)
  if (currentPath.value && currentPath.value !== '.' && currentPath.value !== '__trash__') {
    set.add(currentPath.value)
  }
  return [...set]
    .filter((f) => f && f !== '.' && f !== '__trash__' && f !== 'public' && f !== 'public_html')
    .sort((a, b) => a.localeCompare(b))
})

const ctxTargets = computed(() => {
  if (ctx.value.entry && selectedPaths.value.has(ctx.value.entry.path) && selectedPaths.value.size > 1) {
    return selectedEntries.value
  }
  if (ctx.value.entry) return [ctx.value.entry]
  return selectedEntries.value
})

const ctxTrashTargets = computed(() => {
  if (ctx.value.trashEntry && selectedPaths.value.has(ctx.value.trashEntry.trash_id) && selectedPaths.value.size > 1) {
    return selectedTrashEntries.value
  }
  if (ctx.value.trashEntry) return [ctx.value.trashEntry]
  return selectedTrashEntries.value
})

const ctxIsArchive = computed(() => {
  const t = ctxTargets.value
  if (t.length !== 1 || t[0].is_dir) return false
  return t[0].name.toLowerCase().endsWith('.zip')
})

const chmodOctal = computed(() => {
  const u = (chmodModal.value.u_r ? 4 : 0) + (chmodModal.value.u_w ? 2 : 0) + (chmodModal.value.u_x ? 1 : 0)
  const g = (chmodModal.value.g_r ? 4 : 0) + (chmodModal.value.g_w ? 2 : 0) + (chmodModal.value.g_x ? 1 : 0)
  const o = (chmodModal.value.o_r ? 4 : 0) + (chmodModal.value.o_w ? 2 : 0) + (chmodModal.value.o_x ? 1 : 0)
  return `0${u}${g}${o}`
})

function formatSize(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fileType(entry: Entry) {
  if (entry.is_dir) return 'httpd/unix-directory'
  const ext = entry.name.includes('.') ? entry.name.split('.').pop()?.toLowerCase() : ''
  switch (ext) {
    case 'php': return 'text/x-php'
    case 'html':
    case 'htm': return 'text/html'
    case 'css': return 'text/css'
    case 'js':
    case 'mjs': return 'application/javascript'
    case 'json': return 'application/json'
    case 'svg': return 'image/svg+xml'
    case 'png': return 'image/png'
    case 'jpg':
    case 'jpeg': return 'image/jpeg'
    case 'zip': return 'application/zip'
    case 'sql': return 'application/x-sql'
    case 'txt': return 'text/plain'
    default: return 'text/plain'
  }
}

function fileIconClass(entry: Entry) {
  if (entry.is_dir) return 'fas fa-folder folder-icon'
  const ext = entry.name.includes('.') ? entry.name.split('.').pop()?.toLowerCase() : ''
  switch (ext) {
    case 'php': return 'fab fa-php php-icon'
    case 'html':
    case 'htm': return 'fab fa-html5 html-icon'
    case 'css': return 'fab fa-css3-alt css-icon'
    case 'js': return 'fab fa-js js-icon'
    case 'zip':
    case 'tar':
    case 'gz': return 'fas fa-file-archive archive-icon'
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'svg':
    case 'gif': return 'fas fa-file-image img-icon'
    case 'sql': return 'fas fa-database db-icon'
    default: return 'fas fa-file-alt file-icon'
  }
}

function closeMenus() {
  ctx.value.open = false
}

function closeContext() {
  ctx.value.open = false
}

async function loadUsage() {
  if (!envId.value) return
  try {
    const { data } = await customersApi.environments()
    const found = data.find((x) => x.id === envId.value)
    if (found?.storage_limit_gb) {
      usageLabel.value = `${found.storage_limit_gb} GB storage`
    }
  } catch {
    // Usage optional
  }
}

async function loadStack() {
  // stack name resolved from env
}

async function loadTrash() {
  if (!envId.value) return
  loading.value = true
  err.value = ''
  try {
    const { data } = await customersApi.listEnvTrash(envId.value)
    trashEntries.value = (data?.entries || []).map((e: any) => ({
      trash_id: e.trash_id,
      original_path: e.original_path,
      display_name: e.display_name,
      item_type: e.item_type,
      size_bytes: e.size_bytes,
      deleted_at: e.deleted_at,
      deleted_by: e.deleted_by,
    }))
    trashTotalBytes.value = data?.total_size_bytes || 0
    selectedPaths.value.clear()
    currentPath.value = '__trash__'
    manualPath.value = 'Trash'
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Could not load Trash.')
  } finally {
    loading.value = false
  }
}

async function load(recordHistory = true) {
  if (!envId.value) {
    const ok = await ensureEnvironment()
    if (!ok) {
      loading.value = false
      return
    }
  }
  if (isTrashMode.value) {
    await loadTrash()
    return
  }
  loading.value = true
  err.value = ''
  try {
    const p = currentPath.value === '.' ? '' : currentPath.value
    const { data } = await customersApi.listEnvFiles(envId.value, p)
    const raw = data.entries || []
    entries.value = raw.map((e: any) => ({
      name: e.name,
      path: e.path,
      is_dir: e.is_dir,
      size_bytes: e.size_bytes,
      modified: e.modified,
      mode: e.mode || (e.is_dir ? '0755' : '0644'),
    }))
    parentPath.value = data.parent ? normalizeVirtualPath(data.parent) : null
    selectedPaths.value.clear()

    manualPath.value = currentPath.value === '.' ? '/' : `/${currentPath.value}`

    // Update history
    if (recordHistory) {
      if (historyStack.value[historyIndex.value] !== currentPath.value) {
        historyStack.value = historyStack.value.slice(0, historyIndex.value + 1)
        historyStack.value.push(currentPath.value)
        historyIndex.value = historyStack.value.length - 1
      }
    }

    // Add subfolders to directory tree
    for (const e of entries.value) {
      if (e.is_dir && !folderTree.value.includes(e.path)) {
        folderTree.value.push(e.path)
      }
    }
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Could not load files.')
  } finally {
    loading.value = false
  }
}

async function hydrateEnv() {
  if (!envId.value) return
  try {
    const { data } = await customersApi.environments()
    const found = data.find((e) => e.id === envId.value)
    if (found?.domain) domain.value = found.domain
  } catch {
    // optional
  }
}

async function ensureEnvironment(): Promise<boolean> {
  if (envId.value) return true
  if (isCustomerCpanelHost()) {
    try {
      const { data } = await customersApi.resolvePanelAlias(hostnameNow())
      if (data?.environment_id) {
        resolvedEnvId.value = data.environment_id
        if (typeof window !== 'undefined') {
          localStorage.setItem('tenant_env_id', data.environment_id)
        }
        if (data.domain) domain.value = data.domain
        return true
      }
    } catch {
      // Continue to next check
    }
  }
  try {
    const { data } = await customersApi.environments()
    const first = data?.[0]
    if (first?.id) {
      resolvedEnvId.value = first.id
      if (typeof window !== 'undefined') {
        localStorage.setItem('tenant_env_id', first.id)
      }
      if (first.domain) domain.value = first.domain
      return true
    }
  } catch {
    // Ignore
  }
  return false
}

function openDir(path: string, recordHistory = true) {
  const norm = normalizeVirtualPath(path)
  currentPath.value = norm
  void load(recordHistory)
}

function openTrash() {
  currentPath.value = '__trash__'
  void loadTrash()
}

function goBack() {
  if (historyIndex.value > 0) {
    historyIndex.value--
    openDir(historyStack.value[historyIndex.value], false)
  }
}

function goForward() {
  if (historyIndex.value < historyStack.value.length - 1) {
    historyIndex.value++
    openDir(historyStack.value[historyIndex.value], false)
  }
}

function upOneLevel() {
  if (isTrashMode.value) {
    openDir('.')
    return
  }
  openDir(parentPath.value || '.')
}

function jumpToManualPath() {
  let p = manualPath.value.trim().replace(/^\/+/, '').replace(/\/+$/, '')
  if (p.toLowerCase() === 'trash' || p === '__trash__') {
    openTrash()
    return
  }
  openDir(p || '.')
}

function selectRow(item: Entry | TrashEntry, ev?: MouseEvent) {
  const key = 'trash_id' in item ? item.trash_id : item.path
  if (ev && (ev.metaKey || ev.ctrlKey)) {
    if (selectedPaths.value.has(key)) selectedPaths.value.delete(key)
    else selectedPaths.value.add(key)
    anchorPath.value = key
    return
  }
  if (ev && ev.shiftKey && anchorPath.value) {
    const list = filtered.value
    const anchorIdx = list.findIndex((e) => ('trash_id' in e ? e.trash_id : e.path) === anchorPath.value)
    const targetIdx = list.findIndex((e) => ('trash_id' in e ? e.trash_id : e.path) === key)
    if (anchorIdx >= 0 && targetIdx >= 0) {
      const [start, end] = anchorIdx < targetIdx ? [anchorIdx, targetIdx] : [targetIdx, anchorIdx]
      selectedPaths.value.clear()
      for (let i = start; i <= end; i++) {
        const it = list[i]
        selectedPaths.value.add('trash_id' in it ? it.trash_id : it.path)
      }
      return
    }
  }
  selectedPaths.value.clear()
  selectedPaths.value.add(key)
  anchorPath.value = key
}

function togglePath(key: string) {
  if (selectedPaths.value.has(key)) selectedPaths.value.delete(key)
  else selectedPaths.value.add(key)
  anchorPath.value = key
}

function toggleSelectAll() {
  if (allVisibleSelected.value) {
    selectedPaths.value.clear()
  } else {
    if (isTrashMode.value) {
      selectedPaths.value = new Set((filtered.value as TrashEntry[]).map((e) => e.trash_id))
    } else {
      selectedPaths.value = new Set((filtered.value as Entry[]).map((e) => e.path))
    }
  }
}

function unselectAll() {
  selectedPaths.value.clear()
}

function openEntry(entry: Entry) {
  closeContext()
  if (entry.is_dir) {
    openDir(entry.path)
    return
  }
  const href = `https://ifnotus.space/account/files/edit?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(entry.path)}`
  window.open(href, `ifnotus-editor-${entry.path}`)
}

function onContextMenu(entry: Entry, ev: MouseEvent) {
  ev.preventDefault()
  if (!selectedPaths.value.has(entry.path)) {
    selectedPaths.value.clear()
    selectedPaths.value.add(entry.path)
  }
  anchorPath.value = entry.path
  ctx.value = {
    open: true,
    x: Math.min(ev.clientX, window.innerWidth - 220),
    y: Math.min(ev.clientY, window.innerHeight - 300),
    entry,
    trashEntry: null,
  }
}

function onTrashContextMenu(entry: TrashEntry, ev: MouseEvent) {
  ev.preventDefault()
  if (!selectedPaths.value.has(entry.trash_id)) {
    selectedPaths.value.clear()
    selectedPaths.value.add(entry.trash_id)
  }
  anchorPath.value = entry.trash_id
  ctx.value = {
    open: true,
    x: Math.min(ev.clientX, window.innerWidth - 220),
    y: Math.min(ev.clientY, window.innerHeight - 200),
    entry: null,
    trashEntry: entry,
  }
}

function onBlankContext(ev: MouseEvent) {
  if ((ev.target as HTMLElement).closest('.table-wrap tr')) return
  ev.preventDefault()
  ctx.value = {
    open: true,
    x: Math.min(ev.clientX, window.innerWidth - 220),
    y: Math.min(ev.clientY, window.innerHeight - 200),
    entry: null,
    trashEntry: null,
  }
}

function setClipboard(mode: 'copy' | 'cut') {
  const targets = ctxTargets.value
  const paths = targets.map((e) => e.path)
  if (!paths.length) return
  clipboard.value = { mode, paths }
  msg.value = `${mode === 'copy' ? 'Copied' : 'Cut'} ${paths.length} item(s) to clipboard.`
  closeContext()
}

async function pasteClipboard() {
  if (!clipboard.value.mode || !clipboard.value.paths.length) return
  const dest = currentPath.value || '.'
  const mode = clipboard.value.mode
  try {
    for (const src of clipboard.value.paths) {
      if (mode === 'copy') {
        await customersApi.copyEnvFile(envId.value, src, dest)
      } else {
        await customersApi.moveEnvFile(envId.value, src, dest)
      }
    }
    msg.value = `Pasted ${clipboard.value.paths.length} item(s).`
    if (mode === 'cut') {
      clipboard.value = { mode: null, paths: [] }
    }
    closeContext()
    await load()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Paste failed.')
  }
}

// Chmod modal logic
function openChmod(entry?: Entry | null) {
  const target = entry || selectedEntries.value[0]
  if (!target) return
  closeContext()
  const rawMode = (target.mode || '0755').replace(/^0+/, '') || '755'
  const u = parseInt(rawMode[0] || '7', 10)
  const g = parseInt(rawMode[1] || '5', 10)
  const o = parseInt(rawMode[2] || '5', 10)

  chmodModal.value = {
    open: true,
    entry: target,
    u_r: (u & 4) !== 0,
    u_w: (u & 2) !== 0,
    u_x: (u & 1) !== 0,
    g_r: (g & 4) !== 0,
    g_w: (g & 2) !== 0,
    g_x: (g & 1) !== 0,
    o_r: (o & 4) !== 0,
    o_w: (o & 2) !== 0,
    o_x: (o & 1) !== 0,
    busy: false,
  }
}

async function submitChmod() {
  if (!chmodModal.value.entry) return
  chmodModal.value.busy = true
  try {
    await customersApi.chmodEnvFile(envId.value, chmodModal.value.entry.path, chmodOctal.value)
    msg.value = `Updated permissions for ${chmodModal.value.entry.name} to ${chmodOctal.value}`
    chmodModal.value.open = false
    await load()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Change permissions failed.')
  } finally {
    chmodModal.value.busy = false
  }
}

// Rename modal logic
function openRename(entry?: Entry | null) {
  const target = entry || selectedEntries.value[0]
  if (!target) return
  closeContext()
  renameModal.value = {
    open: true,
    entry: target,
    newName: target.name,
    busy: false,
  }
}

async function submitRename() {
  if (!renameModal.value.entry || !renameModal.value.newName.trim()) return
  const next = renameModal.value.newName.trim()
  if (next === renameModal.value.entry.name) {
    renameModal.value.open = false
    return
  }
  if (next.includes('/') || next.includes('..')) {
    err.value = 'Use a simple name without slashes.'
    return
  }
  renameModal.value.busy = true
  const parent = renameModal.value.entry.path.includes('/')
    ? renameModal.value.entry.path.slice(0, renameModal.value.entry.path.lastIndexOf('/'))
    : '.'
  const destination = parent === '.' ? next : `${parent}/${next}`
  try {
    await customersApi.moveEnvFile(envId.value, renameModal.value.entry.path, destination)
    msg.value = `Renamed to ${next}`
    renameModal.value.open = false
    await load()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Rename failed.')
  } finally {
    renameModal.value.busy = false
  }
}

// View modal logic
async function openView(entry?: Entry | null) {
  const target = entry || selectedEntries.value[0]
  if (!target || target.is_dir) return
  closeContext()
  viewModal.value = {
    open: true,
    entry: target,
    content: '',
    loading: true,
  }
  try {
    const { data } = await customersApi.readEnvFile(envId.value, target.path)
    viewModal.value.content = (data as any)?.content || ''
  } catch (e: unknown) {
    viewModal.value.content = `Error reading file: ${getApiErrorMessage(e)}`
  } finally {
    viewModal.value.loading = false
  }
}

// Move modal logic
const moveBrowseFolders = computed(() =>
  moveBrowseEntries.value.filter((e) => e.is_dir).sort((a, b) => a.name.localeCompare(b.name)),
)

async function loadMoveBrowse(path: string) {
  if (!envId.value) return
  moveBrowseLoading.value = true
  try {
    const norm = normalizeVirtualPath(path)
    const queryPath = norm === '.' ? '' : norm
    const { data } = await customersApi.listEnvFiles(envId.value, queryPath)
    const raw = data.entries || []
    moveBrowseEntries.value = raw.map((e: any) => ({
      name: e.name,
      path: e.path,
      is_dir: e.is_dir,
      size_bytes: e.size_bytes,
      modified: e.modified,
    }))
    moveBrowseParent.value = data.parent ? normalizeVirtualPath(data.parent) : null
    moveBrowsePath.value = norm
    moveDestination.value = norm
  } catch {
    // ignore
  } finally {
    moveBrowseLoading.value = false
  }
}

function beginMove() {
  const targets = ctxTargets.value
  if (!targets.length) return
  closeContext()
  moveDestination.value = currentPath.value || '.'
  moveBrowsePath.value = currentPath.value || '.'
  movePromptOpen.value = true
  void loadMoveBrowse(moveBrowsePath.value)
}

function closeMovePrompt() {
  movePromptOpen.value = false
  moveBusy.value = false
}

async function confirmMove() {
  const targets = ctxTargets.value
  if (!targets.length || !envId.value) return
  const dest = moveDestination.value.trim() || '.'
  moveBusy.value = true
  err.value = ''
  try {
    for (const t of targets) {
      await customersApi.moveEnvFile(envId.value, t.path, dest)
    }
    msg.value = `Moved ${targets.length} item(s) to ${dest === '.' ? 'Home' : dest}`
    closeMovePrompt()
    await load()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Move failed.')
    moveBusy.value = false
  }
}

async function createFolder() {
  const name = newFolder.value.trim()
  if (!name) return
  if (name.includes('/') || name.includes('..')) {
    err.value = 'Use a simple folder name.'
    return
  }
  const rel = currentPath.value === '.' ? name : `${currentPath.value}/${name}`
  try {
    await customersApi.mkdirEnv(envId.value, rel)
    msg.value = `Created folder ${name}`
    newFolder.value = ''
    showMkdirModal.value = false
    await load()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Create folder failed.')
  }
}

async function createFile() {
  const name = newFileName.value.trim()
  if (!name) return
  if (name.includes('/') || name.includes('..')) {
    err.value = 'Use a simple file name.'
    return
  }
  const rel = currentPath.value === '.' ? name : `${currentPath.value}/${name}`
  try {
    await customersApi.writeEnvFile(envId.value, rel, '')
    msg.value = `Created file ${name}`
    newFileName.value = ''
    showNewFileModal.value = false
    await load()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Create file failed.')
  }
}

async function removeTargets(targets: Entry[]) {
  const paths = targets.map((e) => e.path)
  if (!paths.length) return
  closeContext()
  try {
    await customersApi.moveToTrash(envId.value, paths)
    lastMovedTrash.value = {
      name: targets.length === 1 ? targets[0].name : `${targets.length} items`,
      paths,
    }
    msg.value = `Moved ${targets.length} item(s) to Trash`
    await load()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Delete failed.')
  }
}

async function undoLastTrash() {
  if (!lastMovedTrash.value || !envId.value) return
  const info = lastMovedTrash.value
  lastMovedTrash.value = null
  try {
    for (const p of info.paths) {
      await customersApi.restoreTrash(envId.value, p, 'replace')
    }
    msg.value = `Restored ${info.name}`
    await load()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Undo restore failed.')
  }
}

async function restoreTrashTargets(targets: TrashEntry[]) {
  if (!targets.length || !envId.value) return
  closeContext()
  try {
    for (const t of targets) {
      try {
        await customersApi.restoreTrash(envId.value, t.trash_id, 'copy')
      } catch (e: unknown) {
        const errorMsg = getApiErrorMessage(e)
        if (errorMsg.includes('already exists') || errorMsg.includes('Conflict')) {
          conflictModal.value = {
            open: true,
            trashEntry: t,
            busy: false,
          }
          return
        }
        throw e
      }
    }
    msg.value = `Restored ${targets.length} item(s)`
    await loadTrash()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Restore failed.')
  }
}

async function resolveConflict(conflictMode: 'copy' | 'replace') {
  const entry = conflictModal.value.trashEntry
  if (!entry || !envId.value) return
  conflictModal.value.busy = true
  try {
    await customersApi.restoreTrash(envId.value, entry.trash_id, conflictMode)
    conflictModal.value.open = false
    msg.value = `Restored ${entry.display_name}`
    await loadTrash()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Restore failed.')
  } finally {
    conflictModal.value.busy = false
  }
}

async function permanentDeleteTargets(targets: TrashEntry[]) {
  if (!targets.length || !envId.value) return
  if (!confirm(`Permanently delete ${targets.length} item(s)? This cannot be undone.`)) return
  closeContext()
  try {
    for (const t of targets) {
      await customersApi.deleteTrashItem(envId.value, t.trash_id)
    }
    msg.value = `Permanently deleted ${targets.length} item(s)`
    await loadTrash()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Permanent delete failed.')
  }
}

async function emptyTrash() {
  if (!confirm('Permanently delete all items in Trash? This cannot be undone.')) return
  try {
    await customersApi.emptyTrash(envId.value)
    msg.value = 'Trash emptied.'
    closeContext()
    await load()
    await loadUsage()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Empty trash failed.')
  }
}

async function unzipEntry(entry: Entry, extractHere = false) {
  try {
    await customersApi.unzipEnvFile(envId.value, entry.path, { extractHere })
    msg.value = extractHere ? `Extracted ${entry.name} here` : `Extracted ${entry.name}`
    closeContext()
    await load()
    await loadUsage()
  } catch (e: unknown) {
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
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Compress failed.')
  }
}

function downloadEntry(entry?: Entry | null) {
  const target = entry || selectedEntries.value[0]
  if (!target || target.is_dir) return
  transfers.enqueueDownload(target.path, target.name, target.size_bytes || 0, {
    environmentId: envId.value,
  })
  msg.value = `Queued download: ${target.name}`
  closeContext()
}

function pickUpload() {
  if (fileInputRef.value) {
    fileInputRef.value.click()
    return
  }
  if (!envId.value) return
  const href = `https://ifnotus.space/account/files/upload?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(currentPath.value || '.')}`
  window.open(href, `ifnotus-upload-${envId.value}`)
}

function onFileInputChange(event: Event) {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files || !files.length || !envId.value) return
  const fileArray = Array.from(files)
  transfers.enqueueUploadMany(fileArray, currentPath.value || '.', {
    environmentId: envId.value,
  })
  msg.value = `Queued ${fileArray.length} file(s) for upload.`
  target.value = ''
}

function onKeydown(ev: KeyboardEvent) {
  const tag = (ev.target as HTMLElement | null)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'a') {
    ev.preventDefault()
    if (isTrashMode.value) {
      selectedPaths.value = new Set((filtered.value as TrashEntry[]).map((e) => e.trash_id))
    } else {
      selectedPaths.value = new Set((filtered.value as Entry[]).map((e) => e.path))
    }
  }
}

watch(
  () => props.environmentId,
  (next) => {
    if (next) void load()
  },
)

watch(
  () => route.query.path,
  (p) => {
    const norm = normalizeVirtualPath(String(p || '.'))
    if (norm !== currentPath.value) {
      currentPath.value = norm
      void load()
    }
  },
)

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await ensureEnvironment()
  await hydrateEnv()
  await load()
  await loadUsage()
  await loadStack()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="cpanel-fm" :class="{ embedded }" @click="closeMenus">
    <input
      ref="fileInputRef"
      type="file"
      multiple
      style="display: none"
      @change="onFileInputChange"
    />

    <!-- TOP PRIMARY ACTION TOOLBAR -->
    <header class="cp-toolbar" @click.stop>
      <button type="button" class="cp-tool-btn" @click="showNewFileModal = true" title="New File">
        <i class="fas fa-file-alt" />
        <span>+ File</span>
      </button>
      <button type="button" class="cp-tool-btn" @click="showMkdirModal = true" title="New Folder">
        <i class="fas fa-folder-plus" />
        <span>+ Folder</span>
      </button>
      <span class="cp-tool-sep" />
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="!selectionCount || isTrashMode"
        @click="setClipboard('copy')"
        title="Copy Selected"
      >
        <i class="fas fa-copy" />
        <span>Copy</span>
      </button>
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="!selectionCount || isTrashMode"
        @click="beginMove"
        title="Move Selected"
      >
        <i class="fas fa-arrows-alt" />
        <span>Move</span>
      </button>
      <span class="cp-tool-sep" />
      <button
        type="button"
        class="cp-tool-btn highlight"
        :disabled="!envId || isTrashMode"
        @click="pickUpload"
        title="Upload Files"
      >
        <i class="fas fa-upload" />
        <span>Upload</span>
      </button>
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="selectionCount !== 1 || isTrashMode || selectedEntries[0]?.is_dir"
        @click="downloadEntry(selectedEntries[0])"
        title="Download File"
      >
        <i class="fas fa-download" />
        <span>Download</span>
      </button>
      <button
        type="button"
        class="cp-tool-btn danger"
        :disabled="!selectionCount"
        @click="isTrashMode ? permanentDeleteTargets(selectedTrashEntries) : removeTargets(selectedEntries)"
        title="Delete Selected"
      >
        <i class="fas fa-trash-alt" />
        <span>Delete</span>
      </button>
      <button
        v-if="isTrashMode"
        type="button"
        class="cp-tool-btn"
        :disabled="!selectionCount"
        @click="restoreTrashTargets(selectedTrashEntries)"
        title="Restore Selected"
      >
        <i class="fas fa-undo" />
        <span>Restore</span>
      </button>
      <span class="cp-tool-sep" />
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="selectionCount !== 1 || isTrashMode"
        @click="openRename(selectedEntries[0])"
        title="Rename Item"
      >
        <i class="fas fa-i-cursor" />
        <span>Rename</span>
      </button>
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="selectionCount !== 1 || isTrashMode || selectedEntries[0]?.is_dir"
        @click="openEntry(selectedEntries[0])"
        title="Edit Code"
      >
        <i class="fas fa-edit" />
        <span>Edit</span>
      </button>
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="selectionCount !== 1 || isTrashMode"
        @click="openChmod(selectedEntries[0])"
        title="Permissions (chmod)"
      >
        <i class="fas fa-key" />
        <span>Permissions</span>
      </button>
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="selectionCount !== 1 || isTrashMode || selectedEntries[0]?.is_dir"
        @click="openView(selectedEntries[0])"
        title="Quick View"
      >
        <i class="fas fa-eye" />
        <span>View</span>
      </button>
      <span class="cp-tool-sep" />
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="selectionCount !== 1 || isTrashMode || !ctxIsArchive"
        @click="unzipEntry(selectedEntries[0], false)"
        title="Extract Archive"
      >
        <i class="fas fa-file-archive" />
        <span>Extract</span>
      </button>
      <button
        type="button"
        class="cp-tool-btn"
        :disabled="!selectionCount || isTrashMode"
        @click="compressTargets(selectedEntries)"
        title="Compress into Zip"
      >
        <i class="fas fa-file-zipper" />
        <span>Compress</span>
      </button>
    </header>

    <!-- SUB-BAR (LOCATION, NAVIGATION & ACTIONS) -->
    <div class="cp-subbar" @click.stop>
      <div class="sub-location">
        <button type="button" class="sub-home-icon" @click="openDir('.')" title="Home">
          <i class="fas fa-home" />
        </button>
        <div class="path-input-group">
          <input
            v-model="manualPath"
            type="text"
            class="cp-path-input"
            @keyup.enter="jumpToManualPath"
          />
          <button type="button" class="cp-go-btn" @click="jumpToManualPath">Go</button>
        </div>
      </div>

      <div class="sub-nav-actions">
        <button type="button" class="sub-act-btn" @click="openDir('.')">
          <i class="fas fa-home" /> Home
        </button>
        <button type="button" class="sub-act-btn" :disabled="currentPath === '.'" @click="upOneLevel">
          <i class="fas fa-level-up-alt" /> Up One Level
        </button>
        <button type="button" class="sub-act-btn" :disabled="historyIndex <= 0" @click="goBack">
          <i class="fas fa-arrow-left" /> Back
        </button>
        <button
          type="button"
          class="sub-act-btn"
          :disabled="historyIndex >= historyStack.length - 1"
          @click="goForward"
        >
          <i class="fas fa-arrow-right" /> Forward
        </button>
        <button type="button" class="sub-act-btn" @click="load()">
          <i class="fas fa-sync-alt" /> Reload
        </button>
        <span class="sub-sep" />
        <button type="button" class="sub-act-btn" @click="toggleSelectAll">
          <i class="fas fa-check-square" /> Select All
        </button>
        <button type="button" class="sub-act-btn" :disabled="!selectionCount" @click="unselectAll">
          <i class="far fa-square" /> Unselect All
        </button>
        <span class="sub-sep" />
        <button
          type="button"
          class="sub-act-btn"
          :class="{ active: isTrashMode }"
          @click="isTrashMode ? openDir('.') : openTrash()"
        >
          <i class="fas fa-trash" /> {{ isTrashMode ? 'Exit Trash' : 'View Trash' }}
        </button>
        <button
          v-if="isTrashMode && trashEntries.length"
          type="button"
          class="sub-act-btn danger"
          @click="emptyTrash"
        >
          <i class="fas fa-trash-restore" /> Empty Trash
        </button>
      </div>
    </div>

    <!-- FLASH MESSAGES -->
    <p v-if="msg" class="cp-flash ok">
      <span>{{ msg }}</span>
      <button v-if="lastMovedTrash" type="button" class="undo-btn" @click="undoLastTrash">Undo</button>
    </p>
    <p v-if="err" class="cp-flash bad">{{ err }}</p>

    <!-- MAIN TWO-PANE BODY -->
    <div class="cp-body">
      <!-- LEFT DIRECTORY TREE -->
      <aside class="cp-tree-pane" :class="{ collapsed: treeCollapsed }">
        <div class="tree-header">
          <button type="button" class="btn-toggle-tree" @click="treeCollapsed = !treeCollapsed">
            {{ treeCollapsed ? 'Expand All' : 'Collapse All' }}
          </button>
        </div>

        <div v-if="!treeCollapsed" class="tree-content">
          <div
            class="tree-node"
            :class="{ active: currentPath === '.' }"
            @click="openDir('.')"
          >
            <i class="fas fa-minus-square tree-expander" />
            <i class="fas fa-home tree-icon" />
            <span class="tree-label">/ ({{ domain || 'home' }})</span>
          </div>

          <div
            v-for="folder in sidebarFolders"
            :key="folder"
            class="tree-node sub"
            :class="{ active: currentPath === folder }"
            :style="{ paddingLeft: `${(folder.split('/').length + 1) * 0.9}rem` }"
            @click="openDir(folder)"
          >
            <i class="fas fa-folder tree-icon" />
            <span class="tree-label">{{ folder.includes('/') ? folder.slice(folder.lastIndexOf('/') + 1) : folder }}</span>
          </div>

          <div
            class="tree-node trash-node"
            :class="{ active: isTrashMode }"
            @click="openTrash"
          >
            <i class="fas fa-trash tree-icon" />
            <span class="tree-label">.trash</span>
            <span v-if="trashTotalBytes > 0" class="trash-size-badge">{{ formatSize(trashTotalBytes) }}</span>
          </div>
        </div>
      </aside>

      <!-- RIGHT FILE LIST TABLE -->
      <main class="cp-file-pane" @contextmenu="onBlankContext">
        <FileTransferQueue class="queue" />

        <div v-if="loading" class="cp-loading">
          <i class="fas fa-spinner fa-spin" /> Loading files…
        </div>

        <div v-else class="cp-table-wrap">
          <table class="cp-table">
            <thead>
              <tr>
                <th class="col-check">
                  <input
                    type="checkbox"
                    :checked="allVisibleSelected"
                    :indeterminate="selectionCount > 0 && !allVisibleSelected"
                    @change="toggleSelectAll"
                    @click.stop
                  />
                </th>
                <th class="col-name">Name</th>
                <th class="col-size">Size</th>
                <th class="col-mod">Last Modified</th>
                <th class="col-type">Type</th>
                <th class="col-mode">Permissions</th>
              </tr>
            </thead>
            <tbody>
              <!-- PARENT ROW -->
              <tr v-if="parentPath != null && currentPath !== '.' && !isTrashMode" class="row-parent">
                <td class="col-check"></td>
                <td colspan="5">
                  <button type="button" class="btn-parent-dir" @click="openDir(parentPath || '.')">
                    <i class="fas fa-level-up-alt" /> Up One Level
                  </button>
                </td>
              </tr>

              <!-- TRASH ENTRIES -->
              <template v-if="isTrashMode">
                <tr
                  v-for="item in (filtered as TrashEntry[])"
                  :key="item.trash_id"
                  :class="{ selected: selectedPaths.has(item.trash_id) }"
                  @click.stop="selectRow(item, $event)"
                  @contextmenu="onTrashContextMenu(item, $event)"
                >
                  <td class="col-check" @click.stop>
                    <input
                      type="checkbox"
                      :checked="selectedPaths.has(item.trash_id)"
                      @change="togglePath(item.trash_id)"
                    />
                  </td>
                  <td class="col-name">
                    <div class="file-name-cell">
                      <i :class="item.item_type === 'dir' ? 'fas fa-folder folder-icon' : 'fas fa-file-alt file-icon'" />
                      <span>{{ item.display_name }}</span>
                    </div>
                  </td>
                  <td class="col-size mono">{{ item.item_type === 'dir' ? '4 KB' : formatSize(item.size_bytes) }}</td>
                  <td class="col-mod">{{ formatDate(item.deleted_at) }}</td>
                  <td class="col-type">{{ item.item_type === 'dir' ? 'httpd/unix-directory' : 'file' }}</td>
                  <td class="col-mode mono">0700</td>
                </tr>
                <tr v-if="!filtered.length">
                  <td colspan="6" class="cp-empty-cell">Trash is empty.</td>
                </tr>
              </template>

              <!-- NORMAL FILE ENTRIES -->
              <template v-else>
                <tr
                  v-for="entry in (filtered as Entry[])"
                  :key="entry.path"
                  :class="{ selected: selectedPaths.has(entry.path) }"
                  @click.stop="selectRow(entry, $event)"
                  @dblclick.stop="openEntry(entry)"
                  @contextmenu="onContextMenu(entry, $event)"
                >
                  <td class="col-check" @click.stop>
                    <input
                      type="checkbox"
                      :checked="selectedPaths.has(entry.path)"
                      @change="togglePath(entry.path)"
                    />
                  </td>
                  <td class="col-name">
                    <div class="file-name-cell">
                      <i :class="fileIconClass(entry)" />
                      <span class="file-title">{{ entry.name }}</span>
                    </div>
                  </td>
                  <td class="col-size mono">{{ entry.is_dir ? '4 KB' : formatSize(entry.size_bytes) }}</td>
                  <td class="col-mod">{{ formatDate(entry.modified) }}</td>
                  <td class="col-type">{{ fileType(entry) }}</td>
                  <td class="col-mode mono">{{ entry.mode || (entry.is_dir ? '0755' : '0644') }}</td>
                </tr>
                <tr v-if="!filtered.length">
                  <td colspan="6" class="cp-empty-cell">
                    This directory is empty. Use <strong>+ File</strong>, <strong>+ Folder</strong> or <strong>Upload</strong> to add files.
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </main>
    </div>

    <!-- CONTEXT MENU -->
    <div
      v-if="ctx.open"
      class="cp-ctx-menu"
      :style="{ left: `${ctx.x}px`, top: `${ctx.y}px` }"
      @click.stop
      @contextmenu.prevent
    >
      <template v-if="isTrashMode">
        <button type="button" @click="restoreTrashTargets(ctxTrashTargets)">
          <i class="fas fa-undo" /> Restore
        </button>
        <hr />
        <button type="button" class="danger" @click="permanentDeleteTargets(ctxTrashTargets)">
          <i class="fas fa-trash-alt" /> Delete Permanently
        </button>
      </template>
      <template v-else>
        <template v-if="ctxTargets.length === 1">
          <button type="button" @click="openEntry(ctxTargets[0])">
            <i :class="ctxTargets[0].is_dir ? 'fas fa-folder-open' : 'fas fa-edit'" />
            {{ ctxTargets[0].is_dir ? 'Open Folder' : 'Edit' }}
          </button>
          <button v-if="!ctxTargets[0].is_dir" type="button" @click="openView(ctxTargets[0])">
            <i class="fas fa-eye" /> View
          </button>
          <button v-if="!ctxTargets[0].is_dir" type="button" @click="downloadEntry(ctxTargets[0])">
            <i class="fas fa-download" /> Download
          </button>
          <hr />
          <button type="button" @click="openRename(ctxTargets[0])">
            <i class="fas fa-i-cursor" /> Rename
          </button>
          <button type="button" @click="openChmod(ctxTargets[0])">
            <i class="fas fa-key" /> Change Permissions
          </button>
        </template>
        <button type="button" @click="setClipboard('copy')">
          <i class="fas fa-copy" /> Copy
        </button>
        <button type="button" @click="beginMove">
          <i class="fas fa-arrows-alt" /> Move
        </button>
        <button type="button" :disabled="!clipboard.mode" @click="pasteClipboard">
          <i class="fas fa-paste" /> Paste
        </button>
        <hr />
        <button type="button" @click="compressTargets(ctxTargets)">
          <i class="fas fa-file-zipper" /> Compress
        </button>
        <button v-if="ctxIsArchive" type="button" @click="unzipEntry(ctxTargets[0], false)">
          <i class="fas fa-file-archive" /> Extract
        </button>
        <hr />
        <button type="button" class="danger" @click="removeTargets(ctxTargets)">
          <i class="fas fa-trash-alt" /> Delete
        </button>
      </template>
    </div>

    <!-- NEW FILE MODAL -->
    <div v-if="showNewFileModal" class="cp-modal-backdrop" @click.self="showNewFileModal = false">
      <div class="cp-modal-card">
        <div class="modal-head">
          <h3>Create New File</h3>
          <button type="button" class="btn-close" @click="showNewFileModal = false">✕</button>
        </div>
        <p class="modal-desc">Enter the new file name (e.g. <code>index.php</code>, <code>styles.css</code>):</p>
        <input v-model="newFileName" class="cp-modal-input" placeholder="file_name.php" @keyup.enter="createFile" />
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="showNewFileModal = false">Cancel</button>
          <button type="button" class="btn-primary" @click="createFile">Create New File</button>
        </div>
      </div>
    </div>

    <!-- NEW FOLDER MODAL -->
    <div v-if="showMkdirModal" class="cp-modal-backdrop" @click.self="showMkdirModal = false">
      <div class="cp-modal-card">
        <div class="modal-head">
          <h3>Create New Folder</h3>
          <button type="button" class="btn-close" @click="showMkdirModal = false">✕</button>
        </div>
        <p class="modal-desc">Enter the new folder name:</p>
        <input v-model="newFolder" class="cp-modal-input" placeholder="folder_name" @keyup.enter="createFolder" />
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="showMkdirModal = false">Cancel</button>
          <button type="button" class="btn-primary" @click="createFolder">Create New Folder</button>
        </div>
      </div>
    </div>

    <!-- RENAME MODAL -->
    <div v-if="renameModal.open" class="cp-modal-backdrop" @click.self="renameModal.open = false">
      <div class="cp-modal-card">
        <div class="modal-head">
          <h3>Rename Item</h3>
          <button type="button" class="btn-close" @click="renameModal.open = false">✕</button>
        </div>
        <p class="modal-desc">Enter a new name for <strong>{{ renameModal.entry?.name }}</strong>:</p>
        <input v-model="renameModal.newName" class="cp-modal-input" @keyup.enter="submitRename" />
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="renameModal.open = false">Cancel</button>
          <button type="button" class="btn-primary" :disabled="renameModal.busy" @click="submitRename">
            {{ renameModal.busy ? 'Renaming…' : 'Rename File' }}
          </button>
        </div>
      </div>
    </div>

    <!-- CHMOD / PERMISSIONS MODAL -->
    <div v-if="chmodModal.open" class="cp-modal-backdrop" @click.self="chmodModal.open = false">
      <div class="cp-modal-card chmod-card">
        <div class="modal-head">
          <h3>Change Permissions</h3>
          <button type="button" class="btn-close" @click="chmodModal.open = false">✕</button>
        </div>
        <p class="modal-desc">Item: <strong>{{ chmodModal.entry?.name }}</strong></p>

        <div class="chmod-matrix">
          <table>
            <thead>
              <tr>
                <th>Permission</th>
                <th>User</th>
                <th>Group</th>
                <th>World</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Read</td>
                <td><input v-model="chmodModal.u_r" type="checkbox" /></td>
                <td><input v-model="chmodModal.g_r" type="checkbox" /></td>
                <td><input v-model="chmodModal.o_r" type="checkbox" /></td>
              </tr>
              <tr>
                <td>Write</td>
                <td><input v-model="chmodModal.u_w" type="checkbox" /></td>
                <td><input v-model="chmodModal.g_w" type="checkbox" /></td>
                <td><input v-model="chmodModal.o_w" type="checkbox" /></td>
              </tr>
              <tr>
                <td>Execute</td>
                <td><input v-model="chmodModal.u_x" type="checkbox" /></td>
                <td><input v-model="chmodModal.g_x" type="checkbox" /></td>
                <td><input v-model="chmodModal.o_x" type="checkbox" /></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="chmod-value-bar">
          <span>Permission Value:</span>
          <span class="chmod-badge mono">{{ chmodOctal }}</span>
        </div>

        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="chmodModal.open = false">Cancel</button>
          <button type="button" class="btn-primary" :disabled="chmodModal.busy" @click="submitChmod">
            {{ chmodModal.busy ? 'Saving…' : 'Change Permissions' }}
          </button>
        </div>
      </div>
    </div>

    <!-- QUICK VIEW MODAL -->
    <div v-if="viewModal.open" class="cp-modal-backdrop" @click.self="viewModal.open = false">
      <div class="cp-modal-card view-card">
        <div class="modal-head">
          <h3>Viewing: {{ viewModal.entry?.name }}</h3>
          <button type="button" class="btn-close" @click="viewModal.open = false">✕</button>
        </div>
        <div v-if="viewModal.loading" class="cp-loading">Loading content…</div>
        <pre v-else class="cp-view-content mono">{{ viewModal.content }}</pre>
        <div class="modal-foot">
          <button type="button" class="btn-primary" @click="viewModal.open = false">Close</button>
        </div>
      </div>
    </div>

    <!-- MOVE MODAL -->
    <div v-if="movePromptOpen" class="cp-modal-backdrop" @click.self="closeMovePrompt">
      <div class="cp-modal-card move-card">
        <div class="modal-head">
          <h3>Move {{ selectionCount || ctxTargets.length }} item(s)</h3>
          <button type="button" class="btn-close" @click="closeMovePrompt">✕</button>
        </div>
        <p class="modal-desc">
          Current destination: <strong>{{ moveDestination === '.' ? 'Home (/)' : `/${moveDestination}` }}</strong>
        </p>
        <div class="move-tree">
          <button type="button" class="move-folder-item" @click="loadMoveBrowse('.')">
            <i class="fas fa-home" /> Home (/)
          </button>
          <button
            v-for="folder in moveBrowseFolders"
            :key="folder.path"
            type="button"
            class="move-folder-item"
            @click="loadMoveBrowse(folder.path)"
          >
            <i class="fas fa-folder" /> /{{ folder.path }}
          </button>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="closeMovePrompt">Cancel</button>
          <button type="button" class="btn-primary" :disabled="moveBusy" @click="confirmMove">
            {{ moveBusy ? 'Moving…' : 'Move Files' }}
          </button>
        </div>
      </div>
    </div>

    <!-- CONFLICT MODAL -->
    <div v-if="conflictModal.open" class="cp-modal-backdrop" @click.self="conflictModal.open = false">
      <div class="cp-modal-card">
        <div class="modal-head">
          <h3>File Already Exists</h3>
          <button type="button" class="btn-close" @click="conflictModal.open = false">✕</button>
        </div>
        <p class="modal-desc">
          An item named <strong>“{{ conflictModal.trashEntry?.display_name }}”</strong> already exists at
          <strong>{{ conflictModal.trashEntry?.original_path || 'Home' }}</strong>.
        </p>
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="conflictModal.open = false">Cancel</button>
          <button type="button" class="btn-primary" @click="resolveConflict('copy')">Restore as Copy</button>
          <button type="button" class="btn-primary danger" @click="resolveConflict('replace')">Replace Existing</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cpanel-fm {
  display: flex;
  flex-direction: column;
  background: #f1f5f9;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 0.85rem;
  color: #1e293b;
  min-height: 80vh;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  overflow: hidden;
}

.cpanel-fm.embedded {
  min-height: calc(100vh - 4rem);
}

/* TOP CPANEL TOOLBAR */
.cp-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
  background: #f8fafc;
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid #cbd5e1;
}

.cp-tool-btn {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.2rem;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  padding: 0.35rem 0.65rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  min-width: 3.5rem;
  transition: all 0.12s ease;
}

.cp-tool-btn i {
  font-size: 0.95rem;
  color: #475569;
}

.cp-tool-btn:hover:not(:disabled) {
  background: #e2e8f0;
  border-color: #94a3b8;
  color: #0f172a;
}

.cp-tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  background: #f1f5f9;
}

.cp-tool-btn.highlight {
  background: #0284c7;
  color: #fff;
  border-color: #0284c7;
}

.cp-tool-btn.highlight i {
  color: #fff;
}

.cp-tool-btn.highlight:hover:not(:disabled) {
  background: #0369a1;
}

.cp-tool-btn.danger {
  color: #dc2626;
}

.cp-tool-btn.danger i {
  color: #dc2626;
}

.cp-tool-sep {
  width: 1px;
  height: 1.75rem;
  background: #cbd5e1;
  margin: 0 0.2rem;
}

/* SUB-BAR */
.cp-subbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  background: #fff;
  padding: 0.35rem 0.6rem;
  border-bottom: 1px solid #cbd5e1;
}

.sub-location {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex: 1 1 18rem;
  max-width: 30rem;
}

.sub-home-icon {
  background: transparent;
  border: none;
  font-size: 1.1rem;
  color: #0284c7;
  cursor: pointer;
  padding: 0.2rem 0.4rem;
}

.path-input-group {
  display: flex;
  align-items: center;
  flex: 1;
}

.cp-path-input {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-right: none;
  border-radius: 0.3rem 0 0 0.3rem;
  padding: 0.3rem 0.5rem;
  font-size: 0.8rem;
  font-family: monospace;
  background: #f8fafc;
}

.cp-go-btn {
  background: #0284c7;
  color: #fff;
  border: 1px solid #0284c7;
  border-radius: 0 0.3rem 0.3rem 0;
  padding: 0.3rem 0.65rem;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.sub-nav-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}

.sub-act-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.3rem;
  padding: 0.3rem 0.55rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #475569;
  cursor: pointer;
}

.sub-act-btn:hover:not(:disabled) {
  background: #e2e8f0;
  color: #0f172a;
}

.sub-act-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.sub-act-btn.active {
  background: #0284c7;
  color: #fff;
  border-color: #0284c7;
}

.sub-act-btn.danger {
  color: #dc2626;
}

.sub-sep {
  width: 1px;
  height: 1.25rem;
  background: #e2e8f0;
  margin: 0 0.15rem;
}

/* FLASH MESSAGES */
.cp-flash {
  margin: 0;
  padding: 0.4rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cp-flash.ok {
  background: #ecfdf5;
  color: #065f46;
  border-bottom: 1px solid #a7f3d0;
}

.cp-flash.bad {
  background: #fef2f2;
  color: #991b1b;
  border-bottom: 1px solid #fecaca;
}

.undo-btn {
  background: #065f46;
  color: #fff;
  border: none;
  border-radius: 0.25rem;
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
}

/* TWO-PANE BODY */
.cp-body {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  background: #fff;
}

/* LEFT TREE PANE */
.cp-tree-pane {
  width: 18rem;
  min-width: 14rem;
  border-right: 1px solid #cbd5e1;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.cp-tree-pane.collapsed {
  width: auto;
  min-width: 0;
}

.tree-header {
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f1f5f9;
}

.btn-toggle-tree {
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 0.25rem;
  padding: 0.2rem 0.5rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  width: 100%;
}

.tree-content {
  padding: 0.35rem 0;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.6rem;
  font-size: 0.8rem;
  color: #334155;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tree-node:hover {
  background: #e2e8f0;
}

.tree-node.active {
  background: #0284c7;
  color: #fff;
}

.tree-expander {
  font-size: 0.75rem;
  color: #64748b;
}

.tree-icon {
  font-size: 0.85rem;
  color: #0284c7;
}

.tree-node.active .tree-icon,
.tree-node.active .tree-expander {
  color: #fff;
}

.trash-node {
  margin-top: 0.5rem;
  border-top: 1px solid #e2e8f0;
}

.trash-size-badge {
  margin-left: auto;
  font-size: 0.68rem;
  background: #e2e8f0;
  color: #475569;
  padding: 0.1rem 0.35rem;
  border-radius: 0.2rem;
}

/* RIGHT FILE PANE */
.cp-file-pane {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  overflow-x: auto;
  overflow-y: auto;
  background: #fff;
  position: relative;
}

.cp-loading {
  padding: 2.5rem;
  text-align: center;
  color: #64748b;
  font-size: 0.95rem;
}

.cp-table-wrap {
  width: 100%;
  flex: 1;
}

.cp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.cp-table th {
  background: #f8fafc;
  color: #0284c7;
  font-weight: 600;
  text-align: left;
  padding: 0.45rem 0.65rem;
  border-bottom: 1px solid #cbd5e1;
  white-space: nowrap;
}

.cp-table td {
  padding: 0.4rem 0.65rem;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
  white-space: nowrap;
}

.cp-table tr:hover td {
  background: #f1f5f9;
}

.cp-table tr.selected td {
  background: #e0f2fe;
}

.col-check {
  width: 2rem;
  text-align: center;
}

.col-name {
  min-width: 15rem;
}

.col-size {
  width: 6rem;
}

.col-mod {
  width: 12rem;
}

.col-type {
  width: 10rem;
}

.col-mode {
  width: 5rem;
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.folder-icon { color: #0284c7; }
.php-icon { color: #8892bf; }
.html-icon { color: #e44d26; }
.css-icon { color: #264de4; }
.js-icon { color: #f7df1e; }
.archive-icon { color: #f59e0b; }
.img-icon { color: #10b981; }
.db-icon { color: #6366f1; }
.file-icon { color: #64748b; }

.row-parent td {
  background: #fafafa;
}

.btn-parent-dir {
  background: transparent;
  border: none;
  font-weight: 600;
  color: #0284c7;
  cursor: pointer;
  padding: 0.15rem 0;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.cp-empty-cell {
  text-align: center;
  padding: 3rem 1rem;
  color: #64748b;
  font-size: 0.875rem;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* CONTEXT MENU */
.cp-ctx-menu {
  position: fixed;
  z-index: 2000;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 0.4rem;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);
  padding: 0.3rem 0;
  min-width: 12rem;
}

.cp-ctx-menu button {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.35rem 0.75rem;
  background: transparent;
  border: none;
  font-size: 0.8rem;
  color: #334155;
  text-align: left;
  cursor: pointer;
}

.cp-ctx-menu button:hover {
  background: #0284c7;
  color: #fff;
}

.cp-ctx-menu button.danger {
  color: #dc2626;
}

.cp-ctx-menu button.danger:hover {
  background: #dc2626;
  color: #fff;
}

.cp-ctx-menu hr {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 0.25rem 0;
}

/* MODALS */
.cp-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(2px);
  z-index: 2500;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.cp-modal-card {
  background: #fff;
  border-radius: 0.6rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15);
  width: 100%;
  max-width: 28rem;
  padding: 1.5rem;
}

.chmod-card {
  max-width: 24rem;
}

.view-card {
  max-width: 48rem;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.move-card {
  max-width: 28rem;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.modal-head h3 {
  font-size: 1.1rem;
  font-weight: 700;
  margin: 0;
}

.btn-close {
  background: transparent;
  border: none;
  font-size: 1.1rem;
  color: #64748b;
  cursor: pointer;
}

.modal-desc {
  font-size: 0.82rem;
  color: #475569;
  margin-bottom: 0.85rem;
}

.cp-modal-input {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  padding: 0.45rem 0.65rem;
  font-size: 0.875rem;
  margin-bottom: 1rem;
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.btn-ghost {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 0.4rem 0.85rem;
  border-radius: 0.35rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
}

.btn-primary {
  background: #0284c7;
  border: 1px solid #0284c7;
  color: #fff;
  padding: 0.4rem 0.95rem;
  border-radius: 0.35rem;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary.danger {
  background: #dc2626;
  border-color: #dc2626;
}

.chmod-matrix table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 1rem;
}

.chmod-matrix th,
.chmod-matrix td {
  padding: 0.4rem;
  text-align: center;
  border: 1px solid #e2e8f0;
}

.chmod-matrix th:first-child,
.chmod-matrix td:first-child {
  text-align: left;
  font-weight: 600;
}

.chmod-value-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
  font-weight: 600;
}

.chmod-badge {
  font-size: 1.1rem;
  background: #f1f5f9;
  padding: 0.2rem 0.6rem;
  border-radius: 0.3rem;
  border: 1px solid #cbd5e1;
}

.cp-view-content {
  background: #0f172a;
  color: #f8fafc;
  padding: 1rem;
  border-radius: 0.4rem;
  font-size: 0.8rem;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.move-tree {
  max-height: 14rem;
  overflow-y: auto;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  padding: 0.35rem;
  margin-bottom: 1rem;
}

.move-folder-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.35rem 0.5rem;
  border: none;
  background: transparent;
  font-size: 0.8rem;
  color: #334155;
  text-align: left;
  cursor: pointer;
  border-radius: 0.25rem;
}

.move-folder-item:hover {
  background: #e0f2fe;
}
</style>

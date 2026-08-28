<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import IconFolder from '@/components/icons/IconFolder.vue'
import IconTrash from '@/components/icons/IconTrash.vue'
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
const router = useRouter()
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

const emit = defineEmits<{
  (e: 'back'): void
}>()

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
const isTrashMode = computed(() => currentPath.value === '__trash__')
const parentPath = ref<string | null>(null)
const msg = ref('')
const err = ref('')
const lastMovedTrash = ref<{ name: string; paths: string[] } | null>(null)
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
const folderTree = ref<string[]>(['.'])
const clipboard = ref<{ mode: ClipboardMode; paths: string[] }>({ mode: null, paths: [] })
const ctx = ref<{
  open: boolean
  x: number
  y: number
  entry: Entry | null
  trashEntry: TrashEntry | null
}>({ open: false, x: 0, y: 0, entry: null, trashEntry: null })

const movePromptOpen = ref(false)
const moveDestination = ref('.')
const moveBrowsePath = ref('.')
const moveBrowseEntries = ref<Entry[]>([])
const moveBrowseLoading = ref(false)
const moveBrowseParent = ref<string | null>(null)
const moveBusy = ref(false)

const conflictModal = ref<{
  open: boolean
  trashEntry: TrashEntry | null
  busy: boolean
}>({ open: false, trashEntry: null, busy: false })

const breadcrumbs = computed(() => {
  if (isTrashMode.value) {
    return [{ label: 'Trash', path: '__trash__' }]
  }
  const p = currentPath.value === '.' ? '' : currentPath.value
  const parts = p ? p.split('/').filter(Boolean) : []
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

async function loadTrash() {
  if (!envId.value) return
  loading.value = true
  err.value = ''
  closeContext()
  try {
    const { data } = await customersApi.listEnvTrash(envId.value)
    trashEntries.value = data.entries || []
    trashTotalBytes.value = data.total_size_bytes || 0
    selectedPaths.value = new Set()
    anchorPath.value = null
    document.title = `Trash · ${domain.value || 'Files'} · IFNOTUS`
    if (!props.embedded) {
      if (isCustomerCpanelHost() || route.name === 'cpanel-files' || route.path === '/files') {
        void router.replace({
          path: '/files',
          query: { path: '__trash__' },
        })
      } else if (route.name === 'hosting-files') {
        void router.replace({
          name: 'hosting-files',
          params: { environmentId: envId.value },
          query: { path: '__trash__' },
        })
      } else {
        void router.replace({
          name: 'portal-files',
          query: { env: envId.value, path: '__trash__' },
        })
      }
    }
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not load Trash.')
    trashEntries.value = []
  } finally {
    loading.value = false
  }
}

async function load() {
  if (!envId.value) {
    err.value = 'Missing environment. Open Files from Hosting Panel or your account.'
    loading.value = false
    return
  }
  if (isTrashMode.value) {
    await loadTrash()
    return
  }
  loading.value = true
  err.value = ''
  closeContext()
  try {
    const reqPath = currentPath.value || '.'
    const { data } = await customersApi.listEnvFiles(envId.value, reqPath)
    entries.value = (data.entries || []) as Entry[]
    parentPath.value = data.parent
    currentPath.value = data.path || reqPath
    selectedPaths.value = new Set()
    anchorPath.value = null
    for (const e of entries.value) {
      if (e.is_dir) folderTree.value = [...new Set([...folderTree.value, e.path])].slice(0, 40)
    }
    document.title = `Files · ${domain.value || 'Home'} · IFNOTUS`
    if (!props.embedded) {
      if (isCustomerCpanelHost() || route.name === 'cpanel-files' || route.path === '/files') {
        void router.replace({
          path: '/files',
          query: currentPath.value === '.' ? {} : { path: currentPath.value },
        })
      } else if (route.name === 'hosting-files') {
        void router.replace({
          name: 'hosting-files',
          params: { environmentId: envId.value },
          query: currentPath.value === '.' ? {} : { path: currentPath.value },
        })
      } else {
        void router.replace({
          name: 'portal-files',
          query: { env: envId.value, ...(currentPath.value === '.' ? {} : { path: currentPath.value }) },
        })
      }
    }
  } catch (e) {
    if (currentPath.value !== '.') {
      err.value = 'This folder no longer exists. Returned to Home.'
      currentPath.value = '.'
      try {
        const { data } = await customersApi.listEnvFiles(envId.value, '.')
        entries.value = (data.entries || []) as Entry[]
        parentPath.value = data.parent
        currentPath.value = '.'
      } catch {
        entries.value = []
      }
    } else {
      entries.value = []
      err.value = getApiErrorMessage(e, 'Could not load files.')
    }
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
  if (isCustomerCpanelHost()) {
    const host = hostnameNow()
    try {
      const { data: aliasData } = await customersApi.resolvePanelAlias(host)
      if (aliasData.environment_id) {
        resolvedEnvId.value = aliasData.environment_id
        localStorage.setItem('tenant_env_id', aliasData.environment_id)
        return true
      }
    } catch {
      // fallback
    }
  }
  const first = list[0]
  if (!first?.id) {
    err.value = 'No hosting site found yet. Open your account and finish setup first.'
    loading.value = false
    return false
  }
  resolvedEnvId.value = first.id
  localStorage.setItem('tenant_env_id', first.id)
  if (isCustomerCpanelHost()) {
    return true
  }
  await router.replace({
    name: 'hosting-files',
    params: { environmentId: first.id },
    query: route.query.path ? { path: String(route.query.path) } : {},
  })
  return false
}

function openDir(path: string) {
  const norm = normalizeVirtualPath(path)
  currentPath.value = norm
  showMobileNav.value = false
  closeMenus()
  void load()
}

function openTrash() {
  currentPath.value = '__trash__'
  showMobileNav.value = false
  closeMenus()
  void load()
}

function selectRow(item: Entry | TrashEntry, ev?: MouseEvent) {
  closeMenus()
  const key = 'trash_id' in item ? item.trash_id : item.path
  if (ev?.shiftKey && anchorPath.value) {
    const list = filtered.value
    const a = list.findIndex((e) => ('trash_id' in e ? e.trash_id : e.path) === anchorPath.value)
    const b = list.findIndex((e) => ('trash_id' in e ? e.trash_id : e.path) === key)
    if (a >= 0 && b >= 0) {
      const [lo, hi] = a < b ? [a, b] : [b, a]
      const next = new Set(selectedPaths.value)
      for (let i = lo; i <= hi; i++) {
        const itemKey = 'trash_id' in list[i] ? (list[i] as TrashEntry).trash_id : (list[i] as Entry).path
        next.add(itemKey)
      }
      selectedPaths.value = next
      return
    }
  }
  if (ev?.metaKey || ev?.ctrlKey) {
    const next = new Set(selectedPaths.value)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    selectedPaths.value = next
    anchorPath.value = key
    return
  }
  selectedPaths.value = new Set([key])
  anchorPath.value = key
}

function togglePath(key: string) {
  const next = new Set(selectedPaths.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selectedPaths.value = next
  anchorPath.value = key
}

function toggleSelectAll() {
  if (allVisibleSelected.value) {
    selectedPaths.value = new Set()
    anchorPath.value = null
    return
  }
  const keys = filtered.value.map((e) => ('trash_id' in e ? e.trash_id : e.path))
  selectedPaths.value = new Set(keys)
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
  ctx.value = { open: true, x, y, entry, trashEntry: null }
  showNewMenu.value = false
  showOverflow.value = false
}

function onTrashContextMenu(entry: TrashEntry, ev: MouseEvent) {
  ev.preventDefault()
  ev.stopPropagation()
  if (!selectedPaths.value.has(entry.trash_id)) {
    selectedPaths.value = new Set([entry.trash_id])
    anchorPath.value = entry.trash_id
  }
  const pad = 8
  const menuW = 220
  const menuH = 200
  let x = ev.clientX
  let y = ev.clientY
  if (x + menuW > window.innerWidth - pad) x = window.innerWidth - menuW - pad
  if (y + menuH > window.innerHeight - pad) y = window.innerHeight - menuH - pad
  ctx.value = { open: true, x, y, entry: null, trashEntry: entry }
  showNewMenu.value = false
  showOverflow.value = false
}

function onBlankContext(ev: MouseEvent) {
  ev.preventDefault()
  ctx.value = { open: true, x: ev.clientX, y: ev.clientY, entry: null, trashEntry: null }
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
  for (const entry of targets) {
    if (entry.is_dir) {
      if (dest === entry.path || dest.startsWith(`${entry.path}/`)) {
        err.value = `Cannot move “${entry.name}” into itself.`
        return
      }
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
  const label = targets.length === 1 ? `"${targets[0].name}"` : `${targets.length} items`
  if (!confirm(`Move ${label} to Trash?`)) return
  try {
    const paths = targets.map((t) => t.path)
    await customersApi.moveToTrash(envId.value, paths)
    lastMovedTrash.value = { name: label, paths }
    msg.value = `Moved ${label} to Trash`
    closeContext()
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not move to Trash.')
  }
}

async function undoLastTrash() {
  if (!lastMovedTrash.value) return
  try {
    const { data } = await customersApi.listEnvTrash(envId.value)
    const matching = data.entries.filter((e) =>
      lastMovedTrash.value?.paths.includes(e.original_path),
    )
    for (const item of matching) {
      await customersApi.restoreTrash(envId.value, item.trash_id, 'copy')
    }
    msg.value = `Restored ${lastMovedTrash.value.name}`
    lastMovedTrash.value = null
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Undo restore failed.')
  }
}

async function restoreTrashTargets(targets: TrashEntry[]) {
  if (!targets.length) return
  try {
    for (const item of targets) {
      await customersApi.restoreTrash(envId.value, item.trash_id, 'copy')
    }
    msg.value =
      targets.length === 1
        ? `Restored "${targets[0].display_name}"`
        : `Restored ${targets.length} items`
    closeContext()
    await load()
    await loadUsage()
  } catch (e) {
    const errText = getApiErrorMessage(e, 'Restore failed.')
    if (errText.includes('already exists') && targets.length === 1) {
      conflictModal.value = { open: true, trashEntry: targets[0], busy: false }
    } else {
      err.value = errText
    }
  }
}

async function resolveConflict(conflictMode: 'copy' | 'replace') {
  if (!conflictModal.value.trashEntry) return
  conflictModal.value.busy = true
  try {
    await customersApi.restoreTrash(
      envId.value,
      conflictModal.value.trashEntry.trash_id,
      conflictMode,
    )
    msg.value = `Restored "${conflictModal.value.trashEntry.display_name}" (${conflictMode === 'copy' ? 'as copy' : 'replaced'})`
    conflictModal.value = { open: false, trashEntry: null, busy: false }
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Restore failed.')
    conflictModal.value.busy = false
  }
}

async function permanentDeleteTargets(targets: TrashEntry[]) {
  if (!targets.length) return
  const label =
    targets.length === 1
      ? `"${targets[0].display_name}"`
      : `${targets.length} items`
  if (!confirm(`Permanently delete ${label}? This cannot be undone.`)) return
  try {
    for (const item of targets) {
      await customersApi.deleteTrashItem(envId.value, item.trash_id)
    }
    msg.value = `Permanently deleted ${label}`
    closeContext()
    await load()
    await loadUsage()
  } catch (e) {
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
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Empty trash failed.')
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

function backToHosting() {
  if (props.embedded) {
    emit('back')
    return
  }
  if (isCustomerCpanelHost()) {
    void router.push('/')
    return
  }
  if (!envId.value) {
    window.location.href = 'https://ifnotus.space/account'
    return
  }
  void router.push({ name: 'hosting-panel', params: { environmentId: envId.value } })
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
  if (!isTrashMode.value && (ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'c') {
    ev.preventDefault()
    if (selectedEntries.value.length) {
      clipboard.value = { mode: 'copy', paths: selectedEntries.value.map((e) => e.path) }
      msg.value = `Copied ${selectedEntries.value.length} item(s)`
    }
  }
  if (!isTrashMode.value && (ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'x') {
    ev.preventDefault()
    if (selectedEntries.value.length) {
      clipboard.value = { mode: 'cut', paths: selectedEntries.value.map((e) => e.path) }
      msg.value = `Cut ${selectedEntries.value.length} item(s)`
    }
  }
  if (!isTrashMode.value && (ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'v') {
    ev.preventDefault()
    void pasteClipboard()
  }
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    if (isTrashMode.value && selectedTrashEntries.value.length) {
      ev.preventDefault()
      void permanentDeleteTargets(selectedTrashEntries.value)
    } else if (!isTrashMode.value && selectedEntries.value.length) {
      ev.preventDefault()
      void removeTargets(selectedEntries.value)
    }
  }
  if (ev.key === 'Escape') closeMenus()
  if (ev.key === 'Enter' && !isTrashMode.value && selectedEntries.value.length === 1) {
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
  <div class="fm" :class="{ embedded }" @click="closeMenus">
    <input
      ref="fileInputRef"
      type="file"
      multiple
      style="display: none"
      @change="onFileInputChange"
    />
    <header class="fm-bar" @click.stop>
      <div class="identity">
        <button type="button" class="nav-toggle" aria-label="Folders" @click="showMobileNav = !showMobileNav">
          ☰
        </button>
        <button v-if="!embedded" type="button" class="mark" title="Back to hosting dashboard" @click="backToHosting">IF</button>
        <div class="id-text">
          <strong>File manager</strong>
          <p>{{ domain || 'Your site' }}<span v-if="stackLabel"> · {{ stackLabel }}</span></p>
        </div>
      </div>

      <nav class="crumbs" aria-label="Path">
        <button
          v-if="!isTrashMode && currentPath !== '.'"
          type="button"
          class="crumb-btn back-crumb"
          title="Go to parent folder"
          @click="openDir(parentPath || '.')"
        >
          ↑
        </button>
        <button
          v-for="(c, i) in breadcrumbs"
          :key="c.path"
          type="button"
          class="crumb-btn"
          :class="{ active: i === breadcrumbs.length - 1 }"
          @click="isTrashMode ? openTrash() : openDir(c.path)"
        >
          <span v-if="i" class="sep">/</span>{{ c.label }}
        </button>
      </nav>

      <div class="tools">
        <label class="search">
          <span class="sr">Search</span>
          <input
            v-model="search"
            type="search"
            :placeholder="isTrashMode ? 'Search Trash' : 'Search this folder'"
          />
        </label>
        <div v-if="usageLabel" class="usage" :title="usageLabel">
          <div class="usage-bar"><i :style="{ width: `${usagePct}%` }" /></div>
          <span>{{ usageLabel }}</span>
        </div>
        <span v-if="selectionCount" class="sel-pill">{{ selectionCount }} selected</span>

        <template v-if="isTrashMode">
          <button type="button" class="btn" title="Refresh Trash" @click="loadTrash">Refresh</button>
          <button
            v-if="selectionCount"
            type="button"
            class="btn primary"
            @click="restoreTrashTargets(selectedTrashEntries)"
          >
            Restore
          </button>
          <button
            v-if="selectionCount"
            type="button"
            class="btn danger-btn"
            @click="permanentDeleteTargets(selectedTrashEntries)"
          >
            Delete permanently
          </button>
          <button
            v-if="trashEntries.length"
            type="button"
            class="btn danger-btn"
            title="Empty all items in Trash"
            @click="emptyTrash"
          >
            Empty Trash
          </button>
        </template>
        <template v-else>
          <button type="button" class="btn" title="Refresh current folder" @click="load">Refresh</button>
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
              Move to Trash
            </button>
            <button type="button" @click="backToHosting(); showOverflow = false">Hosting panel</button>
          </div>
        </template>
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

    <!-- Conflict Resolution Modal -->
    <div v-if="conflictModal.open" class="move-modal" @click.self="conflictModal.open = false">
      <div class="move-dialog" @click.stop>
        <header class="move-head">
          <h3>File Already Exists</h3>
          <button type="button" class="btn" @click="conflictModal.open = false">Close</button>
        </header>
        <div class="pad">
          <p>
            An item named <strong>“{{ conflictModal.trashEntry?.display_name }}”</strong> already exists at
            <strong>{{ conflictModal.trashEntry?.original_path || 'Home' }}</strong>.
          </p>
          <p class="muted">How would you like to restore this item?</p>
        </div>
        <footer class="move-foot">
          <button
            type="button"
            class="btn primary"
            :disabled="conflictModal.busy"
            @click="resolveConflict('copy')"
          >
            Restore as copy
          </button>
          <button
            type="button"
            class="btn danger-btn"
            :disabled="conflictModal.busy"
            @click="resolveConflict('replace')"
          >
            Replace existing
          </button>
          <button
            type="button"
            class="btn"
            :disabled="conflictModal.busy"
            @click="conflictModal.open = false"
          >
            Cancel
          </button>
        </footer>
      </div>
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

    <p v-if="msg" class="flash ok">
      <span>{{ msg }}</span>
      <button v-if="lastMovedTrash" type="button" class="undo-btn" @click="undoLastTrash">Undo</button>
    </p>
    <p v-if="err" class="flash bad">{{ err }}</p>

    <div class="fm-body">
      <aside class="nav" :class="{ open: showMobileNav }" @click.stop>
        <p class="nav-label">Places</p>
        <button
          type="button"
          class="nav-item"
          :class="{ on: currentPath === '.' }"
          @click="openDir('.')"
        >
          <IconFolder :size="18" variant="windows" /> Home
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ on: isTrashMode }"
          @click="openTrash"
        >
          <IconTrash :size="18" /> Trash
          <span v-if="trashTotalBytes > 0" class="trash-badge">{{ formatSize(trashTotalBytes) }}</span>
        </button>

        <p v-if="sidebarFolders.length" class="nav-label">Folders</p>
        <button
          v-for="folder in sidebarFolders"
          :key="folder"
          type="button"
          class="nav-item"
          :class="{ on: currentPath === folder }"
          @click="openDir(folder)"
        >
          <IconFolder :size="18" variant="windows" />
          <span class="truncate">{{ folder.includes('/') ? folder.slice(folder.lastIndexOf('/') + 1) : folder }}</span>
        </button>
      </aside>
      <div v-if="showMobileNav" class="nav-backdrop" @click="showMobileNav = false" />

      <main class="pane" @contextmenu="onBlankContext">
        <FileTransferQueue class="queue" />
        <p class="hint pad">
          {{ isTrashMode ? 'Click items to select · Right-click for Restore / Permanent Delete' : 'Click to select · Ctrl/Cmd+click multi-select · Shift+click range · Double-click to open · Right-click for actions' }}
        </p>
        <p v-if="loading" class="muted pad">Loading…</p>
        <div v-else class="table-wrap">
          <!-- TRASH TABLE -->
          <table v-if="isTrashMode" class="table">
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
                <th class="orig hide-sm">Original location</th>
                <th class="mod">Deleted</th>
                <th class="size">Size</th>
                <th class="type hide-md">Type</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in (filtered as TrashEntry[])"
                :key="item.trash_id"
                :class="{ selected: selectedPaths.has(item.trash_id) }"
                @click.stop="selectRow(item, $event)"
                @contextmenu="onTrashContextMenu(item, $event)"
              >
                <td class="check" @click.stop>
                  <input
                    type="checkbox"
                    :checked="selectedPaths.has(item.trash_id)"
                    :aria-label="`Select ${item.display_name}`"
                    @change="togglePath(item.trash_id)"
                  />
                </td>
                <td class="name">
                  <span class="row-label">
                    <IconFolder v-if="item.item_type === 'dir'" :size="20" variant="windows" />
                    <span v-else class="file-badge">FILE</span>
                    <span>{{ item.display_name }}</span>
                  </span>
                </td>
                <td class="orig hide-sm mono">{{ item.original_path === '.' ? 'Home' : item.original_path }}</td>
                <td class="mod mono">{{ formatDate(item.deleted_at) }}</td>
                <td class="size mono">{{ item.item_type === 'dir' ? '—' : formatSize(item.size_bytes) }}</td>
                <td class="type hide-md">{{ item.item_type === 'dir' ? 'Folder' : 'File' }}</td>
              </tr>
              <tr v-if="!filtered.length && !loading">
                <td colspan="6" class="empty-cell">
                  <div class="empty-state-box">
                    <IconTrash :size="36" class="empty-icon" />
                    <p class="empty-title">Trash is empty</p>
                    <p class="empty-subtitle">Deleted files and folders will appear here.</p>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- NORMAL DIRECTORY TABLE -->
          <table v-else class="table">
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
              <tr v-if="parentPath != null && currentPath !== '.'" class="parent">
                <td colspan="6">
                  <button type="button" class="row-open" @click="openDir(parentPath || '.')">
                    ↑ Parent folder
                  </button>
                </td>
              </tr>
              <tr
                v-for="entry in (filtered as Entry[])"
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
                    @change="togglePath(entry.path)"
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
              <tr v-if="!filtered.length && !loading">
                <td colspan="6" class="empty-cell">
                  <div class="empty-state-box">
                    <IconFolder :size="32" variant="windows" class="empty-icon" />
                    <p class="empty-title">This folder is empty</p>
                    <p class="empty-subtitle">Upload files or create a subfolder to get started.</p>
                    <div class="empty-actions">
                      <button type="button" class="btn primary" @click="pickUpload">Upload files</button>
                      <button type="button" class="btn" @click="showMkdir = true">New folder</button>
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </main>
    </div>

    <!-- Context Menus -->
    <div
      v-if="ctx.open"
      class="ctx-menu"
      :style="{ left: `${ctx.x}px`, top: `${ctx.y}px` }"
      @click.stop
      @contextmenu.prevent
    >
      <template v-if="isTrashMode">
        <template v-if="ctxTrashTargets.length">
          <button type="button" @click="restoreTrashTargets(ctxTrashTargets)">Restore</button>
          <hr />
          <button type="button" class="danger" @click="permanentDeleteTargets(ctxTrashTargets)">
            Delete permanently
          </button>
        </template>
        <template v-else>
          <button type="button" @click="loadTrash">Refresh</button>
          <button v-if="trashEntries.length" type="button" class="danger" @click="emptyTrash">
            Empty Trash
          </button>
        </template>
      </template>
      <template v-else>
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
            Extract archive…
          </button>
          <button
            v-if="ctxIsArchive"
            type="button"
            @click="unzipEntry(ctxTargets[0], true)"
          >
            Extract here
          </button>
          <hr />
          <button type="button" class="danger" @click="removeTargets(ctxTargets)">Move to Trash</button>
        </template>
        <template v-else>
          <button type="button" @click="showMkdir = true">New folder</button>
          <button type="button" @click="showNewFile = true">New file</button>
          <button type="button" :disabled="!clipboard.mode" @click="pasteClipboard">Paste</button>
          <hr />
          <button type="button" @click="pickUpload">Upload</button>
          <button type="button" @click="load">Refresh</button>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.fm {
  --fm-bg: #f1f5f9;
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
.fm.embedded {
  min-height: calc(100vh - 3rem);
  border-radius: 0.75rem;
  border: 1px solid var(--fm-line);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
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
  gap: 0.15rem;
  align-items: center;
  min-width: 0;
}
.crumbs button {
  border: none;
  background: none;
  color: var(--fm-accent);
  font-weight: 650;
  font-size: 0.82rem;
  cursor: pointer;
  padding: 0.15rem 0.25rem;
  border-radius: 0.25rem;
}
.crumbs button:hover {
  background: #e2e8f0;
}
.crumbs button.active {
  color: var(--fm-ink);
  cursor: default;
}
.crumbs button.back-crumb {
  font-weight: bold;
  padding: 0.15rem 0.4rem;
  background: #e2e8f0;
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
.btn.danger-btn { background: #fee2e2; color: #b91c1c; border-color: #fca5a5; }
.btn.danger-btn:hover { background: #fecaca; }
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
.flash {
  margin: 0;
  padding: 0.45rem 0.85rem;
  font-size: 0.82rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.flash.ok { color: #047857; background: #ecfdf5; }
.flash.bad { color: #b91c1c; background: #fef2f2; }
.undo-btn {
  border: 1px solid #059669;
  background: #ffffff;
  color: #047857;
  font-weight: 700;
  border-radius: 0.3rem;
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
  margin-left: 0.5rem;
}
.undo-btn:hover { background: #f0fdf4; }
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
.trash-badge {
  margin-left: auto;
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--fm-muted);
  background: #e2e8f0;
  padding: 0.1rem 0.35rem;
  border-radius: 999px;
}
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
.table tr.selected { background: #eaf2fc !important; }
.table tr:hover:not(.selected) { background: #f8fafc; }
.table tr.parent { background: #fafbfc; }
.row-open {
  border: none;
  background: none;
  font-weight: 700;
  color: var(--fm-accent);
  cursor: pointer;
  padding: 0.2rem 0;
}
.row-label { display: inline-flex; align-items: center; gap: 0.45rem; font-weight: 600; }
.file-badge {
  font-size: 0.62rem;
  font-weight: 800;
  color: #475569;
  background: #e2e8f0;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
}
.mono { font-family: ui-monospace, monospace; font-size: 0.78rem; color: var(--fm-muted); }
.empty-cell {
  padding: 3rem 1.5rem !important;
  text-align: center !important;
}
.empty-state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
}
.empty-icon {
  opacity: 0.4;
  margin-bottom: 0.25rem;
}
.empty-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--fm-ink);
  margin: 0;
}
.empty-subtitle {
  font-size: 0.8rem;
  color: var(--fm-muted);
  margin: 0 0 0.5rem;
}
.empty-actions {
  display: flex;
  gap: 0.5rem;
}
.pad { padding: 0.85rem; margin: 0; }
.muted { color: var(--fm-muted); }
.ctx-menu {
  position: fixed;
  z-index: 50;
  min-width: 12.5rem;
  background: var(--fm-panel);
  border: 1px solid var(--fm-line);
  border-radius: 0.55rem;
  box-shadow: 0 16px 40px rgb(15 23 42 / 0.16);
  padding: 0.35rem;
  display: grid;
}
.ctx-menu button {
  border: none;
  background: none;
  text-align: left;
  padding: 0.45rem 0.6rem;
  border-radius: 0.35rem;
  font-size: 0.82rem;
  cursor: pointer;
}
.ctx-menu button:hover { background: #f1f5f9; }
.ctx-menu button.danger { color: #b91c1c; }
.ctx-menu button:disabled { opacity: 0.4; cursor: not-allowed; }
.ctx-menu hr { border: none; border-top: 1px solid #eef2f6; margin: 0.25rem 0; }
.move-modal {
  position: fixed;
  inset: 0;
  z-index: 45;
  background: rgb(15 23 42 / 0.4);
  display: grid;
  place-items: center;
  padding: 1rem;
}
.move-dialog {
  width: min(28rem, 94vw);
  background: var(--fm-panel);
  border: 1px solid var(--fm-line);
  border-radius: 0.75rem;
  box-shadow: 0 20px 50px rgb(15 23 42 / 0.2);
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}
.move-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 0.95rem;
  border-bottom: 1px solid var(--fm-line);
}
.move-head h3 { margin: 0; font-size: 0.95rem; }
.move-crumbs {
  padding: 0.45rem 0.95rem;
  border-bottom: 1px solid #eef2f6;
  font-size: 0.78rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}
.move-crumbs .crumb {
  border: none;
  background: none;
  color: var(--fm-accent);
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}
.move-dest { margin: 0; padding: 0.45rem 0.95rem; font-size: 0.75rem; }
.move-list { flex: 1; overflow-y: auto; padding: 0.45rem 0.6rem; max-height: 14rem; }
.move-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  border: none;
  background: none;
  text-align: left;
  padding: 0.4rem 0.45rem;
  border-radius: 0.4rem;
  font-size: 0.82rem;
  cursor: pointer;
}
.move-row:hover { background: #f1f5f9; }
.move-open { margin-left: auto; font-size: 0.7rem; color: var(--fm-accent); font-weight: 700; }
.move-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.45rem;
  padding: 0.65rem 0.95rem;
  border-top: 1px solid var(--fm-line);
}
@media (max-width: 900px) {
  .fm-bar { grid-template-columns: 1fr; gap: 0.45rem; }
  .fm-body { grid-template-columns: 1fr; }
  .nav-toggle { display: inline-flex; align-items: center; justify-content: center; }
  .nav {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    width: 15rem;
    z-index: 35;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    box-shadow: 0 0 30px rgb(0 0 0 / 0.15);
  }
  .nav.open { transform: translateX(0); }
  .nav-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.35);
    z-index: 30;
  }
}
@media (max-width: 640px) {
  .hide-sm { display: none; }
}
@media (max-width: 800px) {
  .hide-md { display: none; }
}
</style>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { useFileTransferStore } from '@/stores/fileTransfers'
import { hostnameNow, isTenantPanelHost, isStaffPanelHost } from '@/lib/platformHosts'
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
const modalFileInputRef = ref<HTMLInputElement | null>(null)
const showUploadModal = ref(false)
const uploadDragOver = ref(false)
const MAX_UPLOAD_SIZE = 512 * 1024 * 1024 // 512 MB

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
  const clean = pathStr.replace(/^[./\\]+/, '').replace(/[/\\]+$/, '')
  if (!clean || clean === 'public') return clean || '.'
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
const unixUsername = ref('')
const search = ref('')
const selectedPaths = ref<Set<string>>(new Set())
const anchorPath = ref<string | null>(null)
const folderTree = ref<string[]>(['.'])
const treeCollapsed = ref(false)

const STANDARD_FPANEL_ROOT_DIRS = [
  'public_html',
  'www',
  'tmp',
]

/** Names hidden from the customer File Manager (sidebar + listing). */
const HIDDEN_FILE_MANAGER_NAMES = new Set([
  '.caldav',
  '.cl.selector',
  '.config',
  '.fpaddons',
  '.fpanel',
  '.cpanel',
  '.htpasswds',
  '.local',
  '.pip',
  '.putty',
  '.razor',
  '.sitepad',
  '.softaculous',
  '.spamassassin',
  '.ssh',
  '.subaccounts',
  '.trash',
  '.cache',
  '.bash_history',
  '.bash_logout',
  '.bash_profile',
  '.bashrc',
  '.ifnotus',
  '.ifnotus-trash',
  'etc',
  'logs',
  'mail',
  'public_ftp',
  'ssl',
  'virtualenv',
  'cgi-bin',
])


interface FolderTreeNode {
  name: string
  path: string
  hasChildren: boolean
  children?: FolderTreeNode[]
}

const rootExpanded = ref(true)
const expandedFolderPaths = ref<Set<string>>(new Set())
const folderChildrenMap = ref<Record<string, FolderTreeNode[]>>({})
const dynamicRootDirs = ref<string[]>([])

const hostingUsername = ref('')

const homeDisplayLabel = computed(() => {
  let u = hostingUsername.value || unixUsername.value
  if (!u && domain.value) {
    u = domain.value.split('.')[0].replace(/[^a-zA-Z0-9]/g, '').toLowerCase().slice(0, 8)
  }
  return `(/home3/${u || 'user'})`
})

function treeFolderIcon(name: string) {
  if (name === 'public_html' || name === 'www') return 'fas fa-globe cp-icon-globe text-sky-600'
  if (name === 'public_ftp') return 'fas fa-exchange-alt cp-icon-ftp text-emerald-600'
  if (name === 'mail') return 'fas fa-envelope cp-icon-mail text-blue-600'
  if (name === '.trash' || name === '__trash__') return 'fas fa-trash trash-icon text-slate-500'
  return 'fas fa-folder folder-icon text-amber-500'
}

const rootTreeFolders = computed<FolderTreeNode[]>(() => {
  const seen = new Set<string>()
  const result: FolderTreeNode[] = []

  const allNames = Array.from(new Set([...STANDARD_FPANEL_ROOT_DIRS, ...dynamicRootDirs.value]))
    .filter((n) => n !== '.trash' && n !== '__trash__')
  allNames.sort((a, b) => a.localeCompare(b))

  for (const name of allNames) {
    if (seen.has(name)) continue
    seen.add(name)
    const children = folderChildrenMap.value[name] || []
    result.push({
      name,
      path: name,
      hasChildren: children.length > 0 || name === 'public_html' || name === 'app' || name === 'ssl' || name === '.fpanel',
      children,
    })
  }
  return result
})

async function toggleFolderExpand(folder: FolderTreeNode) {
  if (expandedFolderPaths.value.has(folder.path)) {
    expandedFolderPaths.value.delete(folder.path)
    return
  }
  expandedFolderPaths.value.add(folder.path)
  if (!folderChildrenMap.value[folder.path] && envId.value) {
    try {
      const { data } = await customersApi.listEnvFiles(envId.value, folder.path)
      const raw = data.entries || []
      const subdirs = raw
        .filter((e: any) => e.is_dir)
        .map((e: any) => ({
          name: e.name,
          path: e.path,
          hasChildren: false,
          children: folderChildrenMap.value[e.path] || [],
        }))
      folderChildrenMap.value[folder.path] = subdirs
    } catch {
      folderChildrenMap.value[folder.path] = []
    }
  }
}

function isFolderExpanded(path: string): boolean {
  return expandedFolderPaths.value.has(path)
}

function toggleRootExpand() {
  rootExpanded.value = !rootExpanded.value
}

function toggleCollapseAll() {
  if (expandedFolderPaths.value.size > 0 || rootExpanded.value) {
    expandedFolderPaths.value.clear()
    rootExpanded.value = false
  } else {
    rootExpanded.value = true
    for (const f of rootTreeFolders.value) {
      expandedFolderPaths.value.add(f.path)
    }
  }
}

const allCollapsed = computed(() => !rootExpanded.value && expandedFolderPaths.value.size === 0)

function openInNewWindow() {
  if (isTenantPanelHost()) {
    window.open('/files', '_blank')
  } else if (envId.value && !isStaffPanelHost()) {
    window.open(`/hosting/${encodeURIComponent(envId.value)}/files`, '_blank')
  } else {
    window.open('/files', '_blank')
  }
}
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
/** Snapshot of items to move — ctxTargets clears when the context menu closes. */
const moveTargets = ref<Entry[]>([])

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

const passwordProtectModal = ref<{
  open: boolean
  entry: Entry | null
  enabled: boolean
  authName: string
  username: string
  password: string
  busy: boolean
  msg: string
}>({
  open: false,
  entry: null,
  enabled: true,
  authName: 'Protected Area',
  username: '',
  password: '',
  busy: false,
  msg: '',
})

const leechProtectModal = ref<{
  open: boolean
  entry: Entry | null
  enabled: boolean
  redirectUrl: string
  allowedDomains: string
  busy: boolean
  msg: string
}>({
  open: false,
  entry: null,
  enabled: true,
  redirectUrl: '',
  allowedDomains: '',
  busy: false,
  msg: '',
})

const manageIndicesModal = ref<{
  open: boolean
  entry: Entry | null
  indexMode: 'default' | 'no_index' | 'standard' | 'fancy'
  busy: boolean
  msg: string
}>({
  open: false,
  entry: null,
  indexMode: 'default',
  busy: false,
  msg: '',
})

const htmlEditorModal = ref<{
  open: boolean
  entry: Entry | null
  content: string
  preview: boolean
  loading: boolean
  saving: boolean
}>({
  open: false,
  entry: null,
  content: '',
  preview: false,
  loading: false,
  saving: false,
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
  let list = entries.value.filter((e) => !HIDDEN_FILE_MANAGER_NAMES.has(e.name))
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
    .filter((f) => f && f !== '.' && f !== '__trash__')
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
  if (n === 0) return '0 bytes'
  if (n === 1) return '1 byte'
  if (n < 1024) return `${n} bytes`
  if (n < 1024 * 1024) {
    const kb = n / 1024
    return kb === Math.floor(kb) ? `${kb} KB` : `${kb.toFixed(2)} KB`
  }
  const mb = n / (1024 * 1024)
  return mb === Math.floor(mb) ? `${mb} MB` : `${mb.toFixed(2)} MB`
}

function formatDate(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const timeStr = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }).toUpperCase()
  if (isToday) {
    return `Today, ${timeStr}`
  }
  const yesterday = new Date()
  yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) {
    return `Yesterday, ${timeStr}`
  }
  return (
    d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }) + `, ${timeStr}`
  )
}

function formatPermissions(entry: Entry) {
  if (entry.mode) {
    const raw = String(entry.mode).trim()
    if (/^\d{3,4}$/.test(raw)) {
      return raw.length === 3 ? `0${raw}` : raw
    }
  }
  if (entry.is_dir) {
    if (entry.name === 'logs' || entry.name === 'ssl' || entry.name === '.trash' || entry.name === '.ssh') return '0700'
    if (entry.name === 'public_ftp' || entry.name === 'etc' || entry.name === '.htpasswds') return '0750'
    if (entry.name === 'mail') return '0751'
    return '0755'
  }
  if (entry.name === '.bash_history') return '0600'
  return '0644'
}

function fileType(entry: Entry) {
  if (entry.is_dir) {
    if (entry.name === 'public_html' || entry.name === 'www') return 'publichtml'
    if (entry.name === 'public_ftp') return 'publicftp'
    if (entry.name === 'mail') return 'mail'
    return 'httpd/unix-directory'
  }
  if (entry.name.startsWith('.bash_') || entry.name === '.bashrc' || entry.name === '.profile') {
    return 'text/x-generic'
  }
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
    case 'htaccess':
    case 'conf':
    case 'ini': return 'text/plain'
    default: return 'text/plain'
  }
}

function fileIconClass(entry: Entry) {
  if (entry.is_dir) {
    if (entry.name === 'public_html' || entry.name === 'www') return 'fas fa-globe cp-icon-globe text-sky-600'
    if (entry.name === 'public_ftp') return 'fas fa-exchange-alt cp-icon-ftp text-emerald-600'
    if (entry.name === 'mail') return 'fas fa-envelope cp-icon-mail text-blue-600'
    if (entry.name === '.trash' || entry.name === '__trash__') return 'fas fa-trash trash-icon text-slate-500'
    return 'fas fa-folder folder-icon text-amber-500'
  }
  if (entry.name.startsWith('.bash_') || entry.name === '.bashrc') {
    return 'fas fa-file-code text-purple-600'
  }
  const ext = entry.name.includes('.') ? entry.name.split('.').pop()?.toLowerCase() : ''
  switch (ext) {
    case 'php': return 'fab fa-php php-icon text-indigo-600'
    case 'html':
    case 'htm': return 'fab fa-html5 html-icon text-amber-600'
    case 'css': return 'fab fa-css3-alt css-icon text-blue-500'
    case 'js': return 'fab fa-js js-icon text-yellow-500'
    case 'zip':
    case 'tar':
    case 'gz': return 'fas fa-file-archive archive-icon text-amber-600'
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'svg':
    case 'gif': return 'fas fa-file-image img-icon text-teal-600'
    case 'sql': return 'fas fa-database db-icon text-sky-700'
    default: return 'fas fa-file-alt file-icon text-slate-500'
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
    if (currentPath.value === '.') {
      for (const e of entries.value) {
        if (
          e.is_dir &&
          !HIDDEN_FILE_MANAGER_NAMES.has(e.name) &&
          !dynamicRootDirs.value.includes(e.name)
        ) {
          dynamicRootDirs.value.push(e.name)
        }
      }
    } else {
      const subdirs = entries.value
        .filter((e) => e.is_dir)
        .map((e) => ({
          name: e.name,
          path: e.path,
          hasChildren: false,
          children: folderChildrenMap.value[e.path] || [],
        }))
      folderChildrenMap.value[currentPath.value] = subdirs
    }
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
    if (found) {
      if (found.domain) domain.value = found.domain
      if ((found as any).hosting_name) hostingUsername.value = (found as any).hosting_name
      if (found.unix_username) unixUsername.value = found.unix_username
    }
  } catch {
    // optional
  }
}

async function ensureEnvironment(): Promise<boolean> {
  if (envId.value) return true
  if (isTenantPanelHost()) {
    try {
      const { data } = await customersApi.resolvePanelAlias(hostnameNow())
      if (data?.environment_id) {
        resolvedEnvId.value = data.environment_id
        if (typeof window !== 'undefined') {
          localStorage.setItem('tenant_env_id', data.environment_id)
        }
        if (data.domain) domain.value = data.domain
        if ((data as any).hosting_name) hostingUsername.value = (data as any).hosting_name
        if ((data as any).unix_username) unixUsername.value = (data as any).unix_username
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
      if ((first as any).hosting_name) hostingUsername.value = (first as any).hosting_name
      if (first.unix_username) unixUsername.value = first.unix_username
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
  if (norm !== '.' && norm !== '__trash__') {
    const segments = norm.split('/')
    let accum = ''
    for (const seg of segments) {
      accum = accum ? `${accum}/${seg}` : seg
      expandedFolderPaths.value.add(accum)
    }
  }
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
  if (/^home\d*\/[^/]+/i.test(p)) {
    p = p.replace(/^home\d*\/[^/]+\/?/i, '')
  }
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

function isImageName(name: string) {
  return /\.(png|jpe?g|gif|webp|svg|bmp|ico|avif)$/i.test(name)
}

function isPdfName(name: string) {
  return /\.pdf$/i.test(name)
}

function isMediaName(name: string) {
  return /\.(mp4|webm|ogg|mp3|wav|m4a)$/i.test(name)
}

async function openBinaryInNewTab(entry: Entry) {
  try {
    const token = localStorage.getItem('access_token')
    const res = await fetch(
      `/api/v1/customers/environments/${encodeURIComponent(envId.value)}/files/download?path=${encodeURIComponent(entry.path)}&inline=1`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
      },
    )
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const w = window.open(url, '_blank', 'noopener,noreferrer')
    if (!w) {
      // Popup blocked — fall back to download-style navigation
      const a = document.createElement('a')
      a.href = url
      a.target = '_blank'
      a.rel = 'noopener'
      a.click()
    }
    // Revoke later so the tab can load
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Could not open file.')
  }
}

function openEntry(entry: Entry) {
  closeContext()
  if (entry.is_dir) {
    openDir(entry.path)
    return
  }
  // Images / PDFs / media: open the real file in a new tab (not the code editor).
  if (isImageName(entry.name) || isPdfName(entry.name) || isMediaName(entry.name)) {
    void openBinaryInNewTab(entry)
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
  moveTargets.value = [...targets]
  closeContext()
  moveDestination.value = currentPath.value || '.'
  moveBrowsePath.value = currentPath.value || '.'
  movePromptOpen.value = true
  void loadMoveBrowse(moveBrowsePath.value)
}

function closeMovePrompt() {
  movePromptOpen.value = false
  moveBusy.value = false
  moveTargets.value = []
}

async function confirmMove() {
  const targets = moveTargets.value.length ? moveTargets.value : ctxTargets.value
  if (!targets.length || !envId.value) {
    err.value = 'Nothing selected to move.'
    return
  }
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

function openPasswordProtect(entry: Entry) {
  closeContext()
  passwordProtectModal.value = {
    open: true,
    entry,
    enabled: true,
    authName: 'Protected Directory',
    username: '',
    password: '',
    busy: false,
    msg: '',
  }
}

async function submitPasswordProtect() {
  if (!passwordProtectModal.value.entry || !envId.value) return
  passwordProtectModal.value.busy = true
  passwordProtectModal.value.msg = ''
  try {
    const dir = passwordProtectModal.value.entry.path
    const htaccessPath = dir === '.' ? '.htaccess' : `${dir}/.htaccess`
    const htpasswdPath = dir === '.' ? '.htpasswd' : `${dir}/.htpasswd`

    if (!passwordProtectModal.value.enabled) {
      let content = ''
      try {
        const { data } = await customersApi.readEnvFile(envId.value, htaccessPath)
        content = data.content || ''
      } catch {
        /* empty */
      }
      content = content.replace(/# --- BEGIN PASSWORD PROTECT ---[\s\S]*?# --- END PASSWORD PROTECT ---/g, '').trim()
      await customersApi.writeEnvFile(envId.value, htaccessPath, content)
      msg.value = `Disabled password protection for ${passwordProtectModal.value.entry.name}`
      passwordProtectModal.value.open = false
      await load()
      return
    }

    const authName = passwordProtectModal.value.authName.trim() || 'Protected Area'
    const user = passwordProtectModal.value.username.trim() || 'user'
    const pass = passwordProtectModal.value.password.trim() || 'pass'

    await customersApi.writeEnvFile(envId.value, htpasswdPath, `${user}:{PLAIN}${pass}\n`)

    let existingHtaccess = ''
    try {
      const { data } = await customersApi.readEnvFile(envId.value, htaccessPath)
      existingHtaccess = data.content || ''
    } catch {
      /* empty */
    }

    const authBlock = `# --- BEGIN PASSWORD PROTECT ---\nAuthType Basic\nAuthName "${authName}"\nAuthUserFile /home3/${domain.value || 'user'}/${htpasswdPath}\nRequire valid-user\n# --- END PASSWORD PROTECT ---`

    let newHtaccess = existingHtaccess.replace(/# --- BEGIN PASSWORD PROTECT ---[\s\S]*?# --- END PASSWORD PROTECT ---/g, '').trim()
    newHtaccess = `${newHtaccess}\n\n${authBlock}`.trim() + '\n'

    await customersApi.writeEnvFile(envId.value, htaccessPath, newHtaccess)
    msg.value = `Directory ${passwordProtectModal.value.entry.name} is now password protected.`
    passwordProtectModal.value.open = false
    await load()
  } catch (e: unknown) {
    passwordProtectModal.value.msg = getApiErrorMessage(e, 'Could not set password protection.')
  } finally {
    passwordProtectModal.value.busy = false
  }
}

function openLeechProtect(entry: Entry) {
  closeContext()
  leechProtectModal.value = {
    open: true,
    entry,
    enabled: true,
    redirectUrl: '',
    allowedDomains: domain.value || '',
    busy: false,
    msg: '',
  }
}

async function submitLeechProtect() {
  if (!leechProtectModal.value.entry || !envId.value) return
  leechProtectModal.value.busy = true
  leechProtectModal.value.msg = ''
  try {
    const dir = leechProtectModal.value.entry.path
    const htaccessPath = dir === '.' ? '.htaccess' : `${dir}/.htaccess`
    let existingHtaccess = ''
    try {
      const { data } = await customersApi.readEnvFile(envId.value, htaccessPath)
      existingHtaccess = data.content || ''
    } catch {
      /* empty */
    }

    let newHtaccess = existingHtaccess.replace(/# --- BEGIN LEECH PROTECT ---[\s\S]*?# --- END LEECH PROTECT ---/g, '').trim()

    if (leechProtectModal.value.enabled) {
      const domains = leechProtectModal.value.allowedDomains
        .split(/[,\n]/)
        .map((d) => d.trim())
        .filter(Boolean)
      const conds = domains.length
        ? domains.map((d) => `RewriteCond %{HTTP_REFERER} !^http(s)?://(www\\.)?${d.replace(/\./g, '\\.')} [NC]`).join('\n')
        : 'RewriteCond %{HTTP_REFERER} !^$'
      const redir = leechProtectModal.value.redirectUrl.trim()
      const rule = redir ? `RewriteRule .*(jpe?g|gif|bmp|png)$ ${redir} [R,NC]` : `RewriteRule .*(jpe?g|gif|bmp|png)$ - [F,NC]`
      const block = `# --- BEGIN LEECH PROTECT ---\nRewriteEngine on\nRewriteCond %{HTTP_REFERER} !^$\n${conds}\n${rule}\n# --- END LEECH PROTECT ---`
      newHtaccess = `${newHtaccess}\n\n${block}`.trim() + '\n'
    }

    await customersApi.writeEnvFile(envId.value, htaccessPath, newHtaccess)
    msg.value = leechProtectModal.value.enabled
      ? `Leech/hotlink protection enabled for ${leechProtectModal.value.entry.name}`
      : `Leech protection disabled.`
    leechProtectModal.value.open = false
    await load()
  } catch (e: unknown) {
    leechProtectModal.value.msg = getApiErrorMessage(e, 'Could not update leech protection.')
  } finally {
    leechProtectModal.value.busy = false
  }
}

function openManageIndices(entry: Entry) {
  closeContext()
  manageIndicesModal.value = {
    open: true,
    entry,
    indexMode: 'default',
    busy: false,
    msg: '',
  }
}

async function submitManageIndices() {
  if (!manageIndicesModal.value.entry || !envId.value) return
  manageIndicesModal.value.busy = true
  manageIndicesModal.value.msg = ''
  try {
    const dir = manageIndicesModal.value.entry.path
    const htaccessPath = dir === '.' ? '.htaccess' : `${dir}/.htaccess`
    let existingHtaccess = ''
    try {
      const { data } = await customersApi.readEnvFile(envId.value, htaccessPath)
      existingHtaccess = data.content || ''
    } catch {
      /* empty */
    }

    let newHtaccess = existingHtaccess.replace(/# --- BEGIN INDEX MANAGEMENT ---[\s\S]*?# --- END INDEX MANAGEMENT ---/g, '').trim()
    const mode = manageIndicesModal.value.indexMode
    if (mode !== 'default') {
      let opt = 'Options -Indexes'
      if (mode === 'standard') opt = 'Options +Indexes'
      else if (mode === 'fancy') opt = 'Options +Indexes\nIndexOptions +FancyIndexing'
      const block = `# --- BEGIN INDEX MANAGEMENT ---\n${opt}\n# --- END INDEX MANAGEMENT ---`
      newHtaccess = `${newHtaccess}\n\n${block}`.trim() + '\n'
    }

    await customersApi.writeEnvFile(envId.value, htaccessPath, newHtaccess)
    msg.value = `Indexing settings updated for ${manageIndicesModal.value.entry.name}.`
    manageIndicesModal.value.open = false
    await load()
  } catch (e: unknown) {
    manageIndicesModal.value.msg = getApiErrorMessage(e, 'Could not update index settings.')
  } finally {
    manageIndicesModal.value.busy = false
  }
}

async function openHtmlEditor(entry: Entry) {
  closeContext()
  if (entry.is_dir) return
  htmlEditorModal.value = {
    open: true,
    entry,
    content: '',
    preview: false,
    loading: true,
    saving: false,
  }
  try {
    const { data } = await customersApi.readEnvFile(envId.value, entry.path)
    htmlEditorModal.value.content = data.content || ''
  } catch {
    htmlEditorModal.value.content = '<!-- Error loading file content -->'
  } finally {
    htmlEditorModal.value.loading = false
  }
}

async function saveHtmlEditor() {
  if (!htmlEditorModal.value.entry || !envId.value) return
  htmlEditorModal.value.saving = true
  try {
    await customersApi.writeEnvFile(envId.value, htmlEditorModal.value.entry.path, htmlEditorModal.value.content)
    msg.value = `Saved ${htmlEditorModal.value.entry.name}`
    htmlEditorModal.value.open = false
    await load()
  } catch (e: unknown) {
    err.value = getApiErrorMessage(e, 'Save failed.')
  } finally {
    htmlEditorModal.value.saving = false
  }
}

async function removeTargets(targets: Entry[]) {
  const paths = targets.map((e) => e.path)
  if (!paths.length) return
  const label =
    targets.length === 1
      ? `"${targets[0].name}"`
      : `${targets.length} selected items`
  if (
    !window.confirm(
      `Move ${label} to Trash?\n\nYou can restore items from Trash later.`,
    )
  ) {
    return
  }
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
  const path = currentPath.value || '.'
  const href =
    `https://ifnotus.space/account/files/upload?env=${encodeURIComponent(envId.value)}` +
    `&path=${encodeURIComponent(path)}`
  window.open(href, 'ifnotus-upload-queue', 'noopener,noreferrer')
}

async function handleFilesToUpload(files: FileList | File[]) {
  if (!envId.value) return
  const fileArray = Array.from(files)
  if (!fileArray.length) return
  const valid: File[] = []
  for (const f of fileArray) {
    if (f.size > MAX_UPLOAD_SIZE) {
      msg.value = `"${f.name}" exceeds the maximum upload limit of 512 MB.`
    } else {
      valid.push(f)
    }
  }
  if (!valid.length) return

  // Duplicate check — ask before overriding existing files
  const dest = currentPath.value || '.'
  const existingNames = new Set(
    entries.value.filter((e) => !e.is_dir).map((e) => e.name.toLowerCase()),
  )
  const duplicates = valid.filter((f) => existingNames.has(f.name.toLowerCase()))
  let toUpload = valid
  if (duplicates.length) {
    const names = duplicates.map((f) => f.name).slice(0, 5).join(', ')
    const more = duplicates.length > 5 ? ` (+${duplicates.length - 5} more)` : ''
    const ok = window.confirm(
      `${duplicates.length} file(s) already exist in this folder (${names}${more}).\n\nOK = replace existing files\nCancel = skip duplicates`,
    )
    if (!ok) {
      const dupSet = new Set(duplicates.map((f) => f.name.toLowerCase()))
      toUpload = valid.filter((f) => !dupSet.has(f.name.toLowerCase()))
      if (!toUpload.length) {
        msg.value = 'Upload cancelled — duplicates skipped.'
        return
      }
    }
  }

  // Prefer dedicated upload queue page (blue → green statuses)
  const href =
    `https://ifnotus.space/account/files/upload?env=${encodeURIComponent(envId.value)}` +
    `&path=${encodeURIComponent(dest)}`
  // Enqueue in shared store so the upload tab / this tab can show progress
  transfers.enqueueUploadMany(toUpload, dest, { environmentId: envId.value })
  window.open(href, 'ifnotus-upload-queue', 'noopener,noreferrer')
  msg.value = `Queued ${toUpload.length} file(s) for upload.`
  showUploadModal.value = false
  void dest
}

function onFileInputChange(event: Event) {
  const target = event.target as HTMLInputElement
  if (target.files?.length) {
    handleFilesToUpload(target.files)
  }
  target.value = ''
}

function onModalFileInputChange(event: Event) {
  const target = event.target as HTMLInputElement
  if (target.files?.length) {
    handleFilesToUpload(target.files)
  }
  target.value = ''
}

function onDropFiles(ev: DragEvent) {
  uploadDragOver.value = false
  if (ev.dataTransfer?.files?.length) {
    handleFilesToUpload(ev.dataTransfer.files)
  }
}

watch(
  () => transfers.hasPending,
  (pending, wasPending) => {
    if (wasPending && !pending) {
      void load()
      void loadUsage()
    }
  },
)

function onKeydown(ev: KeyboardEvent) {
  const tag = (ev.target as HTMLElement | null)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
  
  const list = filtered.value
  if (!list.length) return

  const getKey = (item: Entry | TrashEntry) => ('trash_id' in item ? item.trash_id : item.path)

  // Select all: Ctrl+A / Cmd+A
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'a') {
    ev.preventDefault()
    if (isTrashMode.value) {
      selectedPaths.value = new Set((list as TrashEntry[]).map((e) => e.trash_id))
    } else {
      selectedPaths.value = new Set((list as Entry[]).map((e) => e.path))
    }
    return
  }

  // Clear selection / close context: Escape
  if (ev.key === 'Escape') {
    ev.preventDefault()
    selectedPaths.value.clear()
    closeMenus()
    return
  }

  // Open entry: Enter
  if (ev.key === 'Enter') {
    if (selectedEntries.value.length === 1 && !isTrashMode.value) {
      ev.preventDefault()
      openEntry(selectedEntries.value[0])
      return
    }
  }

  // Delete selection: Delete / Backspace
  if (ev.key === 'Delete' || (ev.key === 'Backspace' && (ev.metaKey || ev.ctrlKey))) {
    if (!isTrashMode.value && selectedEntries.value.length > 0) {
      ev.preventDefault()
      removeTargets(selectedEntries.value)
      return
    }
  }

  // Navigate / Multi-select with Arrow keys
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
    ev.preventDefault()
    const lastKey = anchorPath.value || Array.from(selectedPaths.value).pop()
    let currentIndex = list.findIndex((e) => getKey(e) === lastKey)
    if (currentIndex < 0) {
      currentIndex = ev.key === 'ArrowDown' ? 0 : list.length - 1
    } else {
      currentIndex = ev.key === 'ArrowDown' ? Math.min(list.length - 1, currentIndex + 1) : Math.max(0, currentIndex - 1)
    }

    const targetKey = getKey(list[currentIndex])

    if (ev.shiftKey && anchorPath.value) {
      const anchorIdx = list.findIndex((e) => getKey(e) === anchorPath.value)
      if (anchorIdx >= 0) {
        const [start, end] = anchorIdx < currentIndex ? [anchorIdx, currentIndex] : [currentIndex, anchorIdx]
        selectedPaths.value.clear()
        for (let i = start; i <= end; i++) {
          selectedPaths.value.add(getKey(list[i]))
        }
        return
      }
    }

    selectedPaths.value.clear()
    selectedPaths.value.add(targetKey)
    anchorPath.value = targetKey
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
        :disabled="selectionCount !== 1 || isTrashMode || selectedEntries[0]?.is_dir"
        @click="openHtmlEditor(selectedEntries[0])"
        title="HTML Editor"
      >
        <i class="fas fa-file-code" />
        <span>HTML Editor</span>
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
      <div class="cp-tool-spacer" />
      <button
        type="button"
        class="cp-tool-btn secondary"
        @click="openInNewWindow"
        title="Open File Manager in a new window"
      >
        <i class="fas fa-external-link-alt" />
        <span>New Window</span>
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
          <i class="fas fa-check-double" /> Select All
        </button>
        <button type="button" class="sub-act-btn" :disabled="!selectionCount" @click="unselectAll">
          <i class="fas fa-times" /> Unselect All
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
          <button type="button" class="btn-toggle-tree" @click="toggleCollapseAll">
            {{ allCollapsed ? 'Expand All' : 'Collapse All' }}
          </button>
        </div>

        <div v-if="!treeCollapsed" class="tree-content">
          <!-- ROOT HOME NODE -->
          <div
            class="tree-node root-node"
            :class="{ active: currentPath === '.' }"
            @click="openDir('.')"
          >
            <button
              type="button"
              class="tree-toggle-btn"
              @click.stop="toggleRootExpand"
            >
              <i class="fas" :class="rootExpanded ? 'fa-minus-square' : 'fa-plus-square'" />
            </button>
            <i class="fas fa-folder tree-icon folder-icon text-amber-500" />
            <i class="fas fa-home tree-icon home-icon text-slate-700 dark:text-slate-200" />
            <span class="tree-label">{{ homeDisplayLabel }}</span>
          </div>

          <!-- DIRECTORY TREE NODES -->
          <div v-if="rootExpanded" class="tree-children">
            <div
              v-for="folder in rootTreeFolders"
              :key="folder.path"
              class="tree-branch"
            >
              <div
                class="tree-node"
                :class="{ active: currentPath === folder.path }"
                :style="{ paddingLeft: '0.75rem' }"
                @click="openDir(folder.path)"
              >
                <button
                  v-if="folder.hasChildren || folder.children?.length"
                  type="button"
                  class="tree-toggle-btn"
                  @click.stop="toggleFolderExpand(folder)"
                >
                  <i class="fas" :class="isFolderExpanded(folder.path) ? 'fa-minus-square' : 'fa-plus-square'" />
                </button>
                <span v-else class="tree-toggle-spacer" />
                <i
                  class="tree-icon"
                  :class="treeFolderIcon(folder.name)"
                />
                <span class="tree-label" :class="{ 'highlight-web': folder.path === 'public_html' }">{{ folder.name }}</span>
              </div>

              <!-- Subfolder recursive children if expanded -->
              <div v-if="isFolderExpanded(folder.path) && folder.children?.length" class="tree-sub-children">
                <div
                  v-for="sub in folder.children"
                  :key="sub.path"
                  class="tree-node sub"
                  :class="{ active: currentPath === sub.path }"
                  :style="{ paddingLeft: `${(sub.path.split('/').length + 1) * 0.85}rem` }"
                  @click="openDir(sub.path)"
                >
                  <button
                    v-if="sub.hasChildren || sub.children?.length"
                    type="button"
                    class="tree-toggle-btn"
                    @click.stop="toggleFolderExpand(sub)"
                  >
                    <i class="fas" :class="isFolderExpanded(sub.path) ? 'fa-minus-square' : 'fa-plus-square'" />
                  </button>
                  <span v-else class="tree-toggle-spacer" />
                  <i
                    class="tree-icon"
                    :class="treeFolderIcon(sub.name)"
                  />
                  <span class="tree-label">{{ sub.name }}</span>
                </div>
              </div>
            </div>

            <!-- TRASH DIRECTORY NODE -->
            <div
              class="tree-node trash-node"
              :class="{ active: isTrashMode }"
              :style="{ paddingLeft: '0.75rem' }"
              @click="openTrash"
            >
              <span class="tree-toggle-spacer" />
              <i class="fas fa-trash tree-icon trash-icon" />
              <span class="tree-label">.trash</span>
              <span v-if="trashTotalBytes > 0" class="trash-size-badge">{{ formatSize(trashTotalBytes) }}</span>
            </div>
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
                  <td colspan="5" class="cp-empty-cell">Trash is empty.</td>
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
                  <td class="col-name">
                    <div class="file-name-cell">
                      <i :class="fileIconClass(entry)" />
                      <span class="file-title">{{ entry.name }}</span>
                    </div>
                  </td>
                  <td class="col-size mono">{{ entry.is_dir ? '4 KB' : formatSize(entry.size_bytes) }}</td>
                  <td class="col-mod">{{ formatDate(entry.modified) }}</td>
                  <td class="col-type">{{ fileType(entry) }}</td>
                  <td class="col-mode mono">{{ formatPermissions(entry) }}</td>
                </tr>
                <tr v-if="!filtered.length">
                  <td colspan="5" class="cp-empty-cell">
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
          <i class="fas fa-undo ctx-icon" /> Restore
        </button>
        <hr />
        <button type="button" class="danger" @click="permanentDeleteTargets(ctxTrashTargets)">
          <i class="fas fa-trash-alt ctx-icon" /> Delete Permanently
        </button>
      </template>

      <!-- FOLDER CONTEXT MENU (Exact order matching cPanel screenshot) -->
      <template v-else-if="ctxTargets.length === 1 && ctxTargets[0].is_dir">
        <button type="button" @click="beginMove">
          <i class="fas fa-arrows-alt ctx-icon" /> Move
        </button>
        <button type="button" @click="setClipboard('copy')">
          <i class="far fa-copy ctx-icon" /> Copy
        </button>
        <button type="button" @click="openRename(ctxTargets[0])">
          <i class="fas fa-file-alt ctx-icon" /> Rename
        </button>
        <button type="button" @click="openChmod(ctxTargets[0])">
          <i class="fas fa-key ctx-icon" /> Change Permissions
        </button>
        <button type="button" class="danger" @click="removeTargets(ctxTargets)">
          <i class="fas fa-times ctx-icon" /> Delete
        </button>
        <button type="button" @click="compressTargets(ctxTargets)">
          <i class="fas fa-thumbtack ctx-icon" /> Compress
        </button>
        <button type="button" @click="openPasswordProtect(ctxTargets[0])">
          <i class="fas fa-lock ctx-icon" /> Password Protect
        </button>
        <button type="button" @click="openLeechProtect(ctxTargets[0])">
          <i class="fas fa-shield-alt ctx-icon" /> Leech Protect
        </button>
        <button type="button" @click="openManageIndices(ctxTargets[0])">
          <i class="fas fa-wrench ctx-icon" /> Manage Indices
        </button>
      </template>

      <!-- FILE / MULTI-SELECT CONTEXT MENU -->
      <template v-else>
        <template v-if="ctxTargets.length === 1 && !ctxTargets[0].is_dir">
          <button type="button" @click="openEntry(ctxTargets[0])">
            <i class="fas fa-edit ctx-icon" /> Edit
          </button>
          <button type="button" @click="openHtmlEditor(ctxTargets[0])">
            <i class="fas fa-file-code ctx-icon" /> HTML Editor
          </button>
          <button type="button" @click="openView(ctxTargets[0])">
            <i class="fas fa-eye ctx-icon" /> View
          </button>
          <button type="button" @click="downloadEntry(ctxTargets[0])">
            <i class="fas fa-download ctx-icon" /> Download
          </button>
          <button v-if="ctxIsArchive" type="button" @click="unzipEntry(ctxTargets[0], false)">
            <i class="fas fa-file-archive ctx-icon" /> Extract
          </button>
          <hr />
        </template>
        <button type="button" @click="beginMove">
          <i class="fas fa-arrows-alt ctx-icon" /> Move
        </button>
        <button type="button" @click="setClipboard('copy')">
          <i class="far fa-copy ctx-icon" /> Copy
        </button>
        <button v-if="ctxTargets.length === 1" type="button" @click="openRename(ctxTargets[0])">
          <i class="fas fa-file-alt ctx-icon" /> Rename
        </button>
        <button v-if="ctxTargets.length === 1" type="button" @click="openChmod(ctxTargets[0])">
          <i class="fas fa-key ctx-icon" /> Change Permissions
        </button>
        <button type="button" class="danger" @click="removeTargets(ctxTargets)">
          <i class="fas fa-times ctx-icon" /> Delete
        </button>
        <button type="button" @click="compressTargets(ctxTargets)">
          <i class="fas fa-thumbtack ctx-icon" /> Compress
        </button>
        <button v-if="clipboard.mode" type="button" @click="pasteClipboard">
          <i class="fas fa-paste ctx-icon" /> Paste
        </button>
      </template>
    </div>

    <!-- UPLOAD MODAL -->
    <div v-if="showUploadModal" class="cp-modal-backdrop" @click.self="showUploadModal = false">
      <div class="cp-modal-card upload-modal-card">
        <div class="modal-head">
          <div class="upload-head-title">
            <i class="fas fa-cloud-upload-alt upload-main-icon" />
            <div>
              <h3>Upload Files & Archives</h3>
              <p class="modal-sub">Target folder: <code>{{ currentPath === '.' ? '/ (root)' : currentPath }}</code></p>
            </div>
          </div>
          <button type="button" class="btn-close" @click="showUploadModal = false">✕</button>
        </div>

        <div
          class="upload-drop-zone"
          :class="{ active: uploadDragOver }"
          @dragover.prevent="uploadDragOver = true"
          @dragleave="uploadDragOver = false"
          @drop.prevent="onDropFiles"
          @click="modalFileInputRef?.click()"
        >
          <i class="fas fa-file-zipper drop-icon" />
          <h4>Drag & drop files or ZIP archives here</h4>
          <p class="drop-hint">Maximum upload limit: <strong>512 MB</strong> per file. Supports .zip, tarballs, PHP, HTML, media & code.</p>
          <button type="button" class="btn-primary" @click.stop="modalFileInputRef?.click()">
            <i class="fas fa-folder-open" /> Choose Files to Upload
          </button>
          <input
            ref="modalFileInputRef"
            type="file"
            multiple
            accept="*/*"
            style="display: none"
            @change="onModalFileInputChange"
          />
        </div>

        <!-- ACTIVE / RECENT UPLOADS STATUS -->
        <div v-if="transfers.items.length" class="upload-transfers-box">
          <div class="transfers-box-head">
            <span>Transfers Queue ({{ transfers.items.length }})</span>
            <button v-if="!transfers.hasPending" type="button" class="btn-clear-q" @click="transfers.clearCompleted">
              Clear list
            </button>
          </div>
          <div class="transfers-list">
            <div v-for="item in transfers.items" :key="item.id" class="transfer-row">
              <div class="transfer-info">
                <i :class="item.name.toLowerCase().endsWith('.zip') ? 'fas fa-file-archive tone-orange' : 'fas fa-file tone-blue'" />
                <span class="transfer-name" :title="item.name">{{ item.name }}</span>
                <span class="transfer-status-pill" :class="item.status">{{ item.status }}</span>
              </div>
              <div class="transfer-progress-wrap">
                <div class="transfer-bar">
                  <div class="transfer-fill" :style="{ width: `${item.progress}%` }"></div>
                </div>
                <span class="transfer-pct">{{ item.progress }}%</span>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-foot">
          <p class="upload-note">Files stream in high-speed chunks safely. Keep this panel open during transfer.</p>
          <button type="button" class="btn-ghost" @click="showUploadModal = false">Close</button>
        </div>
      </div>
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
          <h3>Move {{ moveTargets.length || selectionCount || ctxTargets.length }} item(s)</h3>
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

    <!-- PASSWORD PROTECT MODAL -->
    <div v-if="passwordProtectModal.open" class="cp-modal-backdrop" @click.self="passwordProtectModal.open = false">
      <div class="cp-modal-card">
        <div class="modal-head">
          <div class="flex items-center gap-2">
            <i class="fas fa-lock text-sky-600 text-lg" />
            <h3>Directory Privacy / Password Protect</h3>
          </div>
          <button type="button" class="btn-close" @click="passwordProtectModal.open = false">✕</button>
        </div>
        <p class="modal-desc">
          Set password protection for <strong>/{{ passwordProtectModal.entry?.path }}</strong>
        </p>
        <div class="space-y-3 my-3 text-sm">
          <label class="flex items-center gap-2 cursor-pointer font-medium text-slate-700 dark:text-slate-200">
            <input v-model="passwordProtectModal.enabled" type="checkbox" class="rounded text-sky-600 focus:ring-sky-500" />
            Password protect this directory
          </label>
          <div v-if="passwordProtectModal.enabled" class="space-y-3 pt-2">
            <div>
              <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">Protected Area Display Name</label>
              <input
                v-model="passwordProtectModal.authName"
                placeholder="e.g. Restricted Area"
                class="w-full rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-sky-500"
              />
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div>
                <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">Username</label>
                <input
                  v-model="passwordProtectModal.username"
                  placeholder="admin"
                  class="w-full rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-sky-500"
                />
              </div>
              <div>
                <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">Password</label>
                <input
                  v-model="passwordProtectModal.password"
                  type="password"
                  placeholder="••••••••"
                  class="w-full rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-sky-500"
                />
              </div>
            </div>
          </div>
          <p v-if="passwordProtectModal.msg" class="text-xs text-red-600">{{ passwordProtectModal.msg }}</p>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="passwordProtectModal.open = false">Cancel</button>
          <button type="button" class="btn-primary" :disabled="passwordProtectModal.busy" @click="submitPasswordProtect">
            {{ passwordProtectModal.busy ? 'Saving…' : 'Save Protection' }}
          </button>
        </div>
      </div>
    </div>

    <!-- LEECH PROTECT MODAL -->
    <div v-if="leechProtectModal.open" class="cp-modal-backdrop" @click.self="leechProtectModal.open = false">
      <div class="cp-modal-card">
        <div class="modal-head">
          <div class="flex items-center gap-2">
            <i class="fas fa-shield-alt text-emerald-600 text-lg" />
            <h3>Leech & Hotlink Protection</h3>
          </div>
          <button type="button" class="btn-close" @click="leechProtectModal.open = false">✕</button>
        </div>
        <p class="modal-desc">
          Configure hotlink prevention for files in <strong>/{{ leechProtectModal.entry?.path }}</strong>
        </p>
        <div class="space-y-3 my-3 text-sm">
          <label class="flex items-center gap-2 cursor-pointer font-medium text-slate-700 dark:text-slate-200">
            <input v-model="leechProtectModal.enabled" type="checkbox" class="rounded text-sky-600 focus:ring-sky-500" />
            Enable Leech Protection
          </label>
          <div v-if="leechProtectModal.enabled" class="space-y-3 pt-2">
            <div>
              <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">Redirect Leech Requests To URL (Optional)</label>
              <input
                v-model="leechProtectModal.redirectUrl"
                placeholder="https://yourdomain.com/blocked.png"
                class="w-full rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-sky-500"
              />
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">Allowed Referrer Domains (comma-separated)</label>
              <textarea
                v-model="leechProtectModal.allowedDomains"
                placeholder="example.com, mywebsite.com"
                rows="2"
                class="w-full rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-sky-500"
              />
            </div>
          </div>
          <p v-if="leechProtectModal.msg" class="text-xs text-red-600">{{ leechProtectModal.msg }}</p>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="leechProtectModal.open = false">Cancel</button>
          <button type="button" class="btn-primary" :disabled="leechProtectModal.busy" @click="submitLeechProtect">
            {{ leechProtectModal.busy ? 'Saving…' : 'Save Leech Protection' }}
          </button>
        </div>
      </div>
    </div>

    <!-- MANAGE INDICES MODAL -->
    <div v-if="manageIndicesModal.open" class="cp-modal-backdrop" @click.self="manageIndicesModal.open = false">
      <div class="cp-modal-card">
        <div class="modal-head">
          <div class="flex items-center gap-2">
            <i class="fas fa-wrench text-amber-600 text-lg" />
            <h3>Manage Directory Indexing</h3>
          </div>
          <button type="button" class="btn-close" @click="manageIndicesModal.open = false">✕</button>
        </div>
        <p class="modal-desc">
          Choose indexing behavior for <strong>/{{ manageIndicesModal.entry?.path }}</strong>
        </p>
        <div class="space-y-2.5 my-3 text-sm">
          <label class="flex items-center gap-2 cursor-pointer text-slate-700 dark:text-slate-200">
            <input v-model="manageIndicesModal.indexMode" type="radio" value="default" />
            <span><strong>Default System Setting</strong> (Use default web server configuration)</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-slate-700 dark:text-slate-200">
            <input v-model="manageIndicesModal.indexMode" type="radio" value="no_index" />
            <span><strong>No Indexing</strong> (Prevent listing files when index.html is missing)</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-slate-700 dark:text-slate-200">
            <input v-model="manageIndicesModal.indexMode" type="radio" value="standard" />
            <span><strong>Standard Indexing</strong> (Show simple file names list)</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-slate-700 dark:text-slate-200">
            <input v-model="manageIndicesModal.indexMode" type="radio" value="fancy" />
            <span><strong>Fancy Indexing</strong> (Show file names, file sizes, and descriptions)</span>
          </label>
          <p v-if="manageIndicesModal.msg" class="text-xs text-red-600">{{ manageIndicesModal.msg }}</p>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="manageIndicesModal.open = false">Cancel</button>
          <button type="button" class="btn-primary" :disabled="manageIndicesModal.busy" @click="submitManageIndices">
            {{ manageIndicesModal.busy ? 'Saving…' : 'Save Index Settings' }}
          </button>
        </div>
      </div>
    </div>

    <!-- HTML EDITOR MODAL -->
    <div v-if="htmlEditorModal.open" class="cp-modal-backdrop" @click.self="htmlEditorModal.open = false">
      <div class="cp-modal-card html-editor-card">
        <div class="modal-head">
          <div class="flex items-center gap-2">
            <i class="fas fa-file-code text-amber-500 text-lg" />
            <h3>HTML Editor: {{ htmlEditorModal.entry?.name }}</h3>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="px-2.5 py-1 text-xs rounded border font-semibold flex items-center gap-1.5"
              :class="htmlEditorModal.preview ? 'bg-sky-600 text-white border-sky-600' : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300'"
              @click="htmlEditorModal.preview = !htmlEditorModal.preview"
            >
              <i class="fas" :class="htmlEditorModal.preview ? 'fa-code' : 'fa-eye'" />
              <span>{{ htmlEditorModal.preview ? 'Code View' : 'Live Preview' }}</span>
            </button>
            <button type="button" class="btn-close" @click="htmlEditorModal.open = false">✕</button>
          </div>
        </div>
        <div v-if="htmlEditorModal.loading" class="cp-loading">Loading HTML content…</div>
        <div v-else class="html-editor-body">
          <iframe
            v-if="htmlEditorModal.preview"
            :srcdoc="htmlEditorModal.content"
            class="html-preview-frame"
            sandbox="allow-scripts"
          />
          <textarea
            v-else
            v-model="htmlEditorModal.content"
            class="html-editor-textarea mono"
            placeholder="<html>...</html>"
          />
        </div>
        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="htmlEditorModal.open = false">Cancel</button>
          <button type="button" class="btn-primary" :disabled="htmlEditorModal.saving" @click="saveHtmlEditor">
            {{ htmlEditorModal.saving ? 'Saving…' : 'Save Changes' }}
          </button>
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

.btn-toggle-tree:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.tree-content {
  padding: 0.35rem 0;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.28rem 0.5rem;
  font-size: 0.78rem;
  font-weight: 500;
  color: #334155;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  user-select: none;
}

.tree-node:hover {
  background: #e2e8f0;
}

.tree-node.active {
  background: #0284c7;
  color: #fff;
  font-weight: 600;
}

.tree-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.15rem;
  height: 1.15rem;
  padding: 0;
  margin: 0;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 0.72rem;
  cursor: pointer;
  flex-shrink: 0;
  border-radius: 0.2rem;
}

.tree-toggle-btn:hover {
  background: rgba(0, 0, 0, 0.08);
  color: #0f172a;
}

.tree-toggle-spacer {
  display: inline-block;
  width: 1.15rem;
  flex-shrink: 0;
}

.tree-icon {
  font-size: 0.85rem;
  color: #0284c7;
  flex-shrink: 0;
}

.tree-icon.folder-icon {
  color: #d97706;
}

.tree-icon.globe-icon {
  color: #059669;
}

.tree-icon.trash-icon {
  color: #dc2626;
}

.tree-icon.home-icon {
  color: #0284c7;
}

.tree-node.active .tree-icon,
.tree-node.active .tree-toggle-btn,
.tree-node.active .highlight-web {
  color: #fff;
}

.highlight-web {
  font-weight: 700;
  color: #0369a1;
}

.root-node {
  font-weight: 700;
  border-bottom: 1px solid #e2e8f0;
  background: #f1f5f9;
  margin-bottom: 0.2rem;
}

.root-node:hover {
  background: #e2e8f0;
}

.root-node.active {
  background: #0284c7;
  color: #fff;
}

.cp-tool-spacer {
  flex: 1;
}

.cp-tool-btn.secondary {
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #334155;
  margin-left: auto;
}

.cp-tool-btn.secondary:hover {
  background: #e2e8f0;
  color: #0f172a;
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

.cp-table tbody tr {
  cursor: pointer;
  user-select: none;
}

.cp-table tr:hover td {
  background: #f1f5f9;
}

.cp-table tr.selected td {
  background: #dbeafe;
  color: #0369a1;
  font-weight: 500;
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

.folder-icon { color: #d97706; }
.cp-icon-globe { color: #0284c7; }
.cp-icon-ftp { color: #059669; }
.cp-icon-mail { color: #2563eb; }
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
  background: #ffffff;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  padding: 4px 0;
  min-width: 14rem;
  font-family: inherit;
}

.cp-ctx-menu button {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.45rem 1rem;
  background: transparent;
  border: none;
  font-size: 0.8125rem;
  font-weight: 500;
  color: #1e293b;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}

.cp-ctx-menu button .ctx-icon {
  font-size: 0.9rem;
  width: 1.1rem;
  text-align: center;
  color: #0f172a;
}

.cp-ctx-menu button:hover {
  background: #0284c7;
  color: #ffffff;
}

.cp-ctx-menu button:hover .ctx-icon {
  color: #ffffff;
}

.cp-ctx-menu button.danger {
  color: #b91c1c;
}

.cp-ctx-menu button.danger .ctx-icon {
  color: #b91c1c;
}

.cp-ctx-menu button.danger:hover {
  background: #dc2626;
  color: #ffffff;
}

.cp-ctx-menu button.danger:hover .ctx-icon {
  color: #ffffff;
}

.cp-ctx-menu hr {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 0.25rem 0;
}

/* HTML EDITOR MODAL */
.html-editor-card {
  max-width: 56rem !important;
  width: 95vw;
}

.html-editor-body {
  height: 60vh;
  border: 1px solid #cbd5e1;
  border-radius: 0.375rem;
  overflow: hidden;
  margin: 0.75rem 0;
}

.html-editor-textarea {
  width: 100%;
  height: 100%;
  padding: 0.75rem;
  font-size: 0.85rem;
  border: none;
  outline: none;
  resize: none;
  background: #0f172a;
  color: #f8fafc;
}

.html-preview-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: #ffffff;
}

/* UPLOAD MODAL */
.upload-modal-card {
  max-width: 36rem !important;
  width: 100%;
}

.upload-head-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.upload-main-icon {
  font-size: 1.5rem;
  color: #0284c7;
}

.modal-sub {
  font-size: 0.76rem;
  color: #64748b;
  margin: 0.15rem 0 0;
}

.modal-sub code {
  background: #f1f5f9;
  padding: 0.1rem 0.35rem;
  border-radius: 0.25rem;
  color: #0f172a;
}

.upload-drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  padding: 2rem 1.5rem;
  border: 2px dashed #cbd5e1;
  border-radius: 0.75rem;
  background: #f8fafc;
  text-align: center;
  transition: all 0.2s ease;
  cursor: pointer;
  margin: 0.75rem 0;
}

.upload-drop-zone.active, .upload-drop-zone:hover {
  border-color: #0284c7;
  background: #f0f9ff;
}

.drop-icon {
  font-size: 2.2rem;
  color: #0284c7;
}

.upload-drop-zone h4 {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.drop-hint {
  font-size: 0.78rem;
  color: #64748b;
  margin: 0;
  max-width: 26rem;
}

.upload-transfers-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.6rem;
  padding: 0.75rem 0.9rem;
  margin-top: 0.75rem;
  max-height: 12rem;
  overflow-y: auto;
}

.transfers-box-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.78rem;
  font-weight: 700;
  color: #334155;
  margin-bottom: 0.5rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid #f1f5f9;
}

.btn-clear-q {
  background: none;
  border: none;
  color: #0284c7;
  font-size: 0.74rem;
  cursor: pointer;
  font-weight: 600;
}

.transfers-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.transfer-row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.transfer-info {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.78rem;
}

.transfer-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #0f172a;
  font-weight: 600;
}

.transfer-status-pill {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 0.1rem 0.35rem;
  border-radius: 0.25rem;
  background: #e2e8f0;
  color: #475569;
}

.transfer-status-pill.complete, .transfer-status-pill.done {
  background: #dcfce7;
  color: #166534;
}

.transfer-status-pill.uploading, .transfer-status-pill.processing {
  background: #e0f2fe;
  color: #0369a1;
}

.transfer-progress-wrap {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.transfer-bar {
  flex: 1;
  height: 0.35rem;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}

.transfer-fill {
  height: 100%;
  background: #0284c7;
  transition: width 0.3s ease;
}

.transfer-pct {
  font-size: 0.72rem;
  font-weight: 700;
  color: #475569;
}

.upload-note {
  font-size: 0.75rem;
  color: #64748b;
  margin: 0;
  flex: 1;
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

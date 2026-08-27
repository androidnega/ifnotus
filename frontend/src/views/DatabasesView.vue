<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import ConfirmPasswordModal from '@/components/databases/ConfirmPasswordModal.vue'
import { authApi, databasesApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type {
  DatabaseBackup,
  DatabaseCreateBody,
  DatabaseCreated,
  DatabaseEngine,
  DatabaseOverview,
  EngineStatus,
  LiveDatabase,
  ManagedDatabase,
} from '@/types/databases'

const UNLOCK_KEY = 'ifnotus.databases.unlocked_at'
const UNLOCK_TTL_MS = 30 * 60 * 1000

const loading = ref(true)
const unlocked = ref(false)
const unlockBusy = ref(false)
const unlockError = ref<string | null>(null)
const unlockPassword = ref('')
const engineTab = ref<DatabaseEngine | 'all'>('all')
const backups = ref<DatabaseBackup[]>([])
const showRestore = ref(false)
const restoreBusy = ref(false)
const restoreFile = ref<File | null>(null)
const restoreEngine = ref<DatabaseEngine>('postgresql')
const restoreName = ref('')
const restorePath = ref('')
const restorePassword = ref('')
const actionKey = ref<string | null>(null)
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const overview = ref<DatabaseOverview | null>(null)
const showForm = ref(false)
const createdSecret = ref<DatabaseCreated | null>(null)
const revealed = ref<{ id: string; password: string; uri?: string | null } | null>(null)
const dropTarget = ref<
  | { kind: 'managed'; db: ManagedDatabase }
  | { kind: 'live'; row: LiveDatabase }
  | null
>(null)
const dropBusy = ref(false)
const dropError = ref<string | null>(null)

const form = ref<DatabaseCreateBody>({
  engine: 'mysql',
  name: '',
  username: '',
  password: '',
  path: '',
  create_user: true,
  notes: '',
})

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.DATABASES_WRITE))
const router = useRouter()

function openManaged(db: ManagedDatabase) {
  const eng = String(db.engine || '').toLowerCase()
  if (eng === 'mysql' || eng === 'mariadb') {
    void databasesApi
      .openPhpMyAdmin(db.id)
      .then(({ data }) => window.open(data.url, `ifnotus-pma-${db.id}`))
      .catch(() => {
        const href = router.resolve({ name: 'database-studio', query: { kind: 'managed', id: db.id } }).href
        window.open(href, `ifnotus-db-${db.id}`)
      })
    return
  }
  const href = router.resolve({ name: 'database-studio', query: { kind: 'managed', id: db.id } }).href
  window.open(href, `ifnotus-db-${db.id}`)
}

function openLive(row: LiveDatabase) {
  const href = router.resolve({
    name: 'database-studio',
    query: {
      kind: 'live',
      engine: row.engine,
      name: row.name,
      ...(row.path ? { path: row.path } : {}),
    },
  }).href
  window.open(href, `ifnotus-db-${row.engine}-${row.name}`)
}

function isManaged(row: LiveDatabase) {
  return managed.value.some((db) => {
    if (db.engine !== row.engine) return false
    if (row.engine === 'sqlite') return !!row.path && db.path === row.path
    return db.name === row.name
  })
}

function liveKey(row: LiveDatabase) {
  return `${row.engine}:${row.path || row.name}`
}

const engines = computed(() => overview.value?.engines ?? [])
const managed = computed(() => overview.value?.managed ?? [])
const live = computed(() => overview.value?.live ?? [])
const totalObjects = computed(() =>
  live.value.reduce((sum, row) => sum + (row.table_count ?? 0), 0),
)
const runningEngines = computed(() => engines.value.filter((item) => item.running).length)
const filteredManaged = computed(() =>
  engineTab.value === 'all' ? managed.value : managed.value.filter((db) => db.engine === engineTab.value),
)
const filteredLive = computed(() =>
  engineTab.value === 'all' ? live.value : live.value.filter((row) => row.engine === engineTab.value),
)
let refreshTimer: number | null = null

const liveByEngine = computed(() => {
  const map: Record<string, LiveDatabase[]> = {}
  for (const row of filteredLive.value) {
    ;(map[row.engine] ||= []).push(row)
  }
  return map
})

function isUnlocked() {
  const raw = sessionStorage.getItem(UNLOCK_KEY)
  if (!raw) return false
  const at = Number(raw)
  return Number.isFinite(at) && Date.now() - at < UNLOCK_TTL_MS
}

async function unlockDatabases() {
  unlockBusy.value = true
  unlockError.value = null
  try {
    await authApi.confirmPassword(unlockPassword.value)
    sessionStorage.setItem(UNLOCK_KEY, String(Date.now()))
    unlocked.value = true
    unlockPassword.value = ''
    await load()
  } catch (e) {
    unlockError.value = getApiErrorMessage(e, 'Incorrect dashboard password')
  } finally {
    unlockBusy.value = false
  }
}

async function downloadBackup(backupId: string, filename?: string) {
  const token = localStorage.getItem('access_token')
  const res = await fetch(databasesApi.downloadBackupUrl(backupId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error('Backup download failed')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || `backup-${backupId}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function load(silent = false) {
  if (!unlocked.value) return
  if (!silent) loading.value = true
  try {
    const [{ data }, backupRes] = await Promise.all([
      databasesApi.list(),
      databasesApi.listBackups().catch(() => ({ data: { backups: [] } })),
    ])
    overview.value = data
    backups.value = backupRes.data.backups || []
    if (engineTab.value === 'all' && data.engines[0]) {
      // keep all
    }
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Failed to load databases') }
  } finally {
    if (!silent) loading.value = false
  }
}

function engineBadge(engine: EngineStatus) {
  if (engine.running) return 'success' as const
  if (engine.available) return 'warning' as const
  return 'danger' as const
}

async function ensureEngine(engine: DatabaseEngine) {
  actionKey.value = `ensure-${engine}`
  message.value = null
  try {
    const { data } = await databasesApi.ensure(engine)
    message.value = { type: data.success ? 'ok' : 'err', text: data.message }
    await load()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Ensure failed') }
  } finally {
    actionKey.value = null
  }
}

async function createDb() {
  actionKey.value = 'create'
  message.value = null
  createdSecret.value = null
  try {
    const body: DatabaseCreateBody = {
      engine: form.value.engine,
      name: form.value.name.trim(),
      create_user: form.value.engine === 'sqlite' ? false : form.value.create_user,
      notes: form.value.notes || undefined,
    }
    if (form.value.engine === 'sqlite' && form.value.path?.trim()) {
      body.path = form.value.path.trim()
    }
    if (form.value.engine !== 'sqlite') {
      if (form.value.username?.trim()) body.username = form.value.username.trim()
      if (form.value.password?.trim()) body.password = form.value.password.trim()
    }
    const { data } = await databasesApi.create(body)
    createdSecret.value = data
    message.value = { type: 'ok', text: data.message }
    showForm.value = false
    form.value = {
      engine: form.value.engine,
      name: '',
      username: '',
      password: '',
      path: '',
      create_user: true,
      notes: '',
    }
    await load()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Create failed') }
  } finally {
    actionKey.value = null
  }
}

async function revealPassword(db: ManagedDatabase) {
  actionKey.value = `pw-${db.id}`
  try {
    const { data } = await databasesApi.revealPassword(db.id)
    revealed.value = { id: db.id, password: data.password, uri: data.connection_uri }
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Reveal failed') }
  } finally {
    actionKey.value = null
  }
}

async function dropDb(db: ManagedDatabase) {
  dropError.value = null
  dropTarget.value = { kind: 'managed', db }
}

async function adoptLive(row: LiveDatabase) {
  actionKey.value = `adopt-${liveKey(row)}`
  message.value = null
  try {
    const { data } = await databasesApi.adopt({
      engine: row.engine,
      name: row.name,
      path: row.path || undefined,
      notes: 'Adopted from live databases list',
    })
    createdSecret.value = data
    message.value = { type: 'ok', text: data.message }
    await load(true)
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Adopt failed') }
  } finally {
    actionKey.value = null
  }
}

async function dropLive(row: LiveDatabase) {
  dropError.value = null
  dropTarget.value = { kind: 'live', row }
}

async function confirmDrop(password: string) {
  if (!dropTarget.value) return
  dropBusy.value = true
  dropError.value = null
  message.value = null
  try {
    if (dropTarget.value.kind === 'managed') {
      const db = dropTarget.value.db
      actionKey.value = `del-${db.id}`
      const { data } = await databasesApi.drop(db.id, { confirmPassword: password })
      const backupId = typeof data.details?.backup_id === 'string' ? data.details.backup_id : null
      const backupName = typeof data.details?.backup_filename === 'string' ? data.details.backup_filename : undefined
      if (backupId) await downloadBackup(backupId, backupName)
      message.value = { type: 'ok', text: data.message }
      if (revealed.value?.id === db.id) revealed.value = null
    } else {
      const row = dropTarget.value.row
      actionKey.value = `live-del-${liveKey(row)}`
      const { data } = await databasesApi.dropLive({
        engine: row.engine,
        name: row.name,
        path: row.path || undefined,
        confirm_password: password,
        drop_user: false,
        remove_files: true,
      })
      const backupId = typeof data.details?.backup_id === 'string' ? data.details.backup_id : null
      const backupName = typeof data.details?.backup_filename === 'string' ? data.details.backup_filename : undefined
      if (backupId) await downloadBackup(backupId, backupName)
      message.value = { type: data.success ? 'ok' : 'err', text: data.message }
    }
    dropTarget.value = null
    await load(true)
  } catch (e) {
    dropError.value = getApiErrorMessage(e, 'Drop failed')
  } finally {
    dropBusy.value = false
    actionKey.value = null
  }
}

async function restoreDatabase() {
  if (!restorePassword.value.trim() || !restoreName.value.trim()) return
  restoreBusy.value = true
  message.value = null
  try {
    const formData = new FormData()
    formData.append('confirm_password', restorePassword.value)
    formData.append('engine', restoreEngine.value)
    formData.append('name', restoreName.value.trim())
    if (restorePath.value.trim()) formData.append('path', restorePath.value.trim())
    formData.append('create_if_missing', 'true')
    if (restoreFile.value) formData.append('file', restoreFile.value)
    const { data } = await databasesApi.restore(formData)
    message.value = { type: data.success ? 'ok' : 'err', text: data.message }
    showRestore.value = false
    restorePassword.value = ''
    restoreFile.value = null
    await load(true)
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Restore failed') }
  } finally {
    restoreBusy.value = false
  }
}

function formatBytes(n?: number | null) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

const dropTitle = computed(() => {
  if (!dropTarget.value) return 'Drop database'
  if (dropTarget.value.kind === 'managed') {
    return `Drop ${dropTarget.value.db.engine} database`
  }
  return `Drop live ${dropTarget.value.row.engine} database`
})

const dropDescription = computed(() => {
  if (!dropTarget.value) return ''
  const name = dropTarget.value.kind === 'managed' ? dropTarget.value.db.name : dropTarget.value.row.name
  return `You are about to permanently drop "${name}". A backup will be created and downloaded first. Confirm below and enter your dashboard admin password.`
})

onMounted(() => {
  unlocked.value = isUnlocked()
  if (unlocked.value) {
    load()
    refreshTimer = window.setInterval(() => {
      if (!document.hidden && !actionKey.value) load(true)
    }, 10_000)
  } else {
    loading.value = false
  }
})
onBeforeUnmount(() => {
  if (refreshTimer != null) window.clearInterval(refreshTimer)
})
</script>

<template>
  <DashboardLayout>
    <div v-if="!unlocked" class="mx-auto max-w-md space-y-4 rounded-2xl border border-surface-border bg-surface-raised p-6">
      <h1 class="text-xl font-semibold">Unlock Databases</h1>
      <p class="text-sm text-surface-muted">
        This area can change live data. Enter your dashboard admin password to continue.
      </p>
      <label class="block text-sm">
        <span class="text-surface-muted">Dashboard password</span>
        <input
          v-model="unlockPassword"
          type="password"
          autocomplete="current-password"
          class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2"
          @keydown.enter.prevent="unlockDatabases"
        />
      </label>
      <p v-if="unlockError" class="text-sm text-red-600">{{ unlockError }}</p>
      <button
        type="button"
        class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        :disabled="unlockBusy || !unlockPassword.trim()"
        @click="unlockDatabases"
      >
        {{ unlockBusy ? 'Checking…' : 'Unlock' }}
      </button>
    </div>

    <div v-else class="db-page">
      <UiPageHeader eyebrow="Data infrastructure" title="Databases" lede="Browse, query, back up, and manage every database running on this server.">
        <template #actions>
          <div class="db-hero-actions">
            <button type="button" class="db-button is-quiet" :disabled="loading" @click="load()">Refresh</button>
            <button v-if="canWrite" type="button" class="db-button is-quiet" @click="showRestore = !showRestore">
              {{ showRestore ? 'Hide restore' : 'Restore' }}
            </button>
            <button v-if="canWrite" type="button" class="db-button is-primary" @click="showForm = !showForm">
              {{ showForm ? 'Close form' : '+ Create database' }}
            </button>
          </div>
        </template>
        <div class="db-health-row" style="margin-top: 0.75rem">
          <span><strong>{{ runningEngines }}/{{ engines.length }}</strong> engines online</span>
          <span><strong>{{ live.length }}</strong> detected</span>
          <span><strong>{{ totalObjects }}</strong> data objects</span>
        </div>
      </UiPageHeader>

      <p
        v-if="message"
        class="rounded-lg px-3 py-2 text-sm"
        :class="message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-800 dark:text-emerald-200' : 'bg-red-500/10 text-red-700 dark:text-red-300'"
      >
        {{ message.text }}
      </p>

      <nav class="db-tabs" aria-label="Filter databases by engine">
        <button
          type="button"
          :class="{ active: engineTab === 'all' }"
          @click="engineTab = 'all'"
        >
          All engines
          <span>{{ live.length }}</span>
        </button>
        <button
          v-for="engine in engines"
          :key="engine.engine"
          type="button"
          :class="{ active: engineTab === engine.engine }"
          @click="engineTab = engine.engine"
        >
          {{ engine.engine }}
          <span>{{ live.filter((row) => row.engine === engine.engine).length }}</span>
        </button>
      </nav>

      <div class="db-stats">
        <div class="db-stat">
          <div class="db-stat-icon is-teal">DB</div>
          <div>
            <p>Detected databases</p>
            <strong>{{ live.length }}</strong>
            <span>Across all running engines</span>
          </div>
        </div>
        <div class="db-stat">
          <div class="db-stat-icon is-blue">IF</div>
          <div>
            <p>Managed by IFNOTUS</p>
            <strong>{{ managed.length }}</strong>
            <span>Credentials and lifecycle tracked</span>
          </div>
        </div>
        <div class="db-stat">
          <div class="db-stat-icon is-violet">#</div>
          <div>
            <p>Tables & collections</p>
            <strong>{{ totalObjects }}</strong>
            <span>Updated quietly in the background</span>
          </div>
        </div>
      </div>

      <Card v-if="createdSecret" title="Credentials (shown once)">
        <dl class="space-y-2 text-sm">
          <div class="flex gap-2"><dt class="w-28 text-surface-muted">Engine</dt><dd>{{ createdSecret.database.engine }}</dd></div>
          <div class="flex gap-2"><dt class="w-28 text-surface-muted">Name</dt><dd class="font-mono">{{ createdSecret.database.name }}</dd></div>
          <div v-if="createdSecret.database.username" class="flex gap-2">
            <dt class="w-28 text-surface-muted">User</dt>
            <dd class="font-mono">{{ createdSecret.database.username }}</dd>
          </div>
          <div v-if="createdSecret.password" class="flex gap-2">
            <dt class="w-28 text-surface-muted">Password</dt>
            <dd class="break-all font-mono text-amber-800 dark:text-amber-200">{{ createdSecret.password }}</dd>
          </div>
          <div v-if="createdSecret.connection_uri" class="flex gap-2">
            <dt class="w-28 text-surface-muted">URI</dt>
            <dd class="break-all font-mono text-xs">{{ createdSecret.connection_uri }}</dd>
          </div>
          <div v-if="createdSecret.database.path" class="flex gap-2">
            <dt class="w-28 text-surface-muted">Path</dt>
            <dd class="break-all font-mono text-xs">{{ createdSecret.database.path }}</dd>
          </div>
        </dl>
        <p class="mt-3 text-xs text-surface-muted">Copy these now — password is stored encrypted and can be revealed later from Managed.</p>
      </Card>

      <Card v-if="showForm && canWrite" title="Create database">
        <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="createDb">
          <label class="block text-sm sm:col-span-2">
            <span class="text-surface-muted">Engine</span>
            <select
              v-model="form.engine"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2"
            >
              <option value="mysql">MySQL</option>
              <option value="postgresql">PostgreSQL</option>
              <option value="sqlite">SQLite</option>
              <option value="mongodb">MongoDB</option>
            </select>
          </label>
          <label class="block text-sm">
            <span class="text-surface-muted">Database name</span>
            <input
              v-model="form.name"
              required
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
              placeholder="my_app_db"
            />
          </label>
          <label v-if="form.engine === 'sqlite'" class="block text-sm">
            <span class="text-surface-muted">File path (optional)</span>
            <input
              v-model="form.path"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
              placeholder="/srv/apps/myapp/data.sqlite3"
            />
          </label>
          <template v-else>
            <label class="block text-sm">
              <span class="text-surface-muted">Username</span>
              <input
                v-model="form.username"
                class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
                :placeholder="form.name || 'defaults to db name'"
              />
            </label>
            <label class="block text-sm sm:col-span-2">
              <span class="text-surface-muted">Password (leave blank to auto-generate)</span>
              <input
                v-model="form.password"
                type="text"
                autocomplete="new-password"
                class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
                placeholder="••••••••"
              />
            </label>
            <label class="flex items-center gap-2 text-sm sm:col-span-2">
              <input v-model="form.create_user" type="checkbox" class="rounded border-surface-border" />
              Create user and grant full access on this database
            </label>
          </template>
          <label class="block text-sm sm:col-span-2">
            <span class="text-surface-muted">Notes</span>
            <input
              v-model="form.notes"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm"
              placeholder="Optional note"
            />
          </label>
          <div class="sm:col-span-2">
            <button
              type="submit"
              class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              :disabled="actionKey === 'create' || !form.name.trim()"
            >
              {{ actionKey === 'create' ? 'Creating…' : 'Create' }}
            </button>
          </div>
        </form>
      </Card>

      <section>
        <div class="db-section-heading">
          <div>
            <span>Runtime</span>
            <h2>Database engines</h2>
          </div>
          <p>Services available on this host</p>
        </div>
        <div class="db-engine-grid">
        <div
          v-for="engine in engines"
          :key="engine.engine"
          class="db-engine"
          :class="{ selected: engineTab === engine.engine }"
          @click="engineTab = engine.engine"
        >
          <div class="db-engine-head">
            <div class="db-engine-mark">{{ engine.engine.slice(0, 2).toUpperCase() }}</div>
            <div>
              <h3>{{ engine.engine }}</h3>
              <p>{{ engine.port ? `Listening on port ${engine.port}` : 'Local engine' }}</p>
            </div>
            <Badge :variant="engineBadge(engine)" size="sm" dot>
              {{ engine.running ? 'running' : engine.available ? 'available' : 'missing' }}
            </Badge>
          </div>
          <p v-if="engine.version" class="db-engine-version" :title="engine.version">
            {{ engine.version }}
          </p>
          <p v-if="engine.message" class="db-engine-warning">{{ engine.message }}</p>
          <button
            v-if="canWrite && engine.installable && !engine.running"
            type="button"
            class="db-button is-quiet mt-3"
            :disabled="actionKey === `ensure-${engine.engine}`"
            @click.stop="ensureEngine(engine.engine)"
          >
            {{ actionKey === `ensure-${engine.engine}` ? 'Working…' : 'Ensure / start' }}
          </button>
        </div>
        </div>
      </section>

      <Card title="Managed by IFNOTUS" subtitle="Databases with lifecycle and credential management">
        <div v-if="loading" class="text-sm text-surface-muted">Loading…</div>
        <div v-else-if="!filteredManaged.length" class="text-sm text-surface-muted">
          {{ managed.length ? 'No managed databases in this tab.' : 'No managed databases yet. Create one above or ask SNR Dev.' }}
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[640px] text-left text-sm">
            <thead class="text-xs uppercase text-surface-muted">
              <tr>
                <th class="py-2 pr-3">Engine</th>
                <th class="py-2 pr-3">Name</th>
                <th class="py-2 pr-3">User</th>
                <th class="py-2 pr-3">Tables</th>
                <th class="py-2 pr-3">URI / path</th>
                <th class="py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="db in filteredManaged" :key="db.id" class="border-t border-surface-border/70">
                <td class="py-2.5 pr-3"><Badge size="sm">{{ db.engine }}</Badge></td>
                <td class="py-2.5 pr-3 font-mono">{{ db.name }}</td>
                <td class="py-2.5 pr-3 font-mono text-xs">{{ db.username || '—' }}</td>
                <td class="py-2.5 pr-3">
                  <span class="rounded-full bg-brand-500/10 px-2 py-1 text-xs font-medium text-brand-700 dark:text-brand-300">
                    {{ db.table_count ?? '—' }}
                  </span>
                </td>
                <td class="max-w-[240px] truncate py-2.5 pr-3 font-mono text-xs text-surface-muted" :title="db.connection_uri || db.path || ''">
                  {{ db.connection_uri || db.path || '—' }}
                </td>
                <td class="py-2.5">
                  <div class="flex flex-wrap gap-2">
                    <button
                      type="button"
                      class="text-xs text-brand-700 dark:text-brand-300"
                      @click="openManaged(db)"
                    >
                      {{
                        String(db.engine || '').toLowerCase() === 'mysql' ||
                        String(db.engine || '').toLowerCase() === 'mariadb'
                          ? 'Open phpMyAdmin'
                          : 'Open studio'
                      }}
                    </button>
                    <button
                      v-if="canWrite && db.password_set"
                      type="button"
                      class="text-xs text-brand-700 dark:text-brand-300"
                      @click="revealPassword(db)"
                    >
                      Reveal password
                    </button>
                    <button
                      v-if="canWrite"
                      type="button"
                      class="text-xs text-red-600"
                      @click="dropDb(db)"
                    >
                      Drop
                    </button>
                  </div>
                  <p
                    v-if="revealed?.id === db.id"
                    class="mt-1 break-all font-mono text-[11px] text-amber-800 dark:text-amber-200"
                  >
                    {{ revealed.password }}
                    <span v-if="revealed.uri" class="mt-1 block text-surface-muted">{{ revealed.uri }}</span>
                  </p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Live databases on host" subtitle="Discovered directly from running database engines">
        <div v-if="!live.length" class="text-sm text-surface-muted">No live databases detected.</div>
        <div v-else class="space-y-6">
          <section v-for="(rows, engine) in liveByEngine" :key="engine" class="db-live-section">
            <div class="mb-3 flex items-center gap-2">
              <h3 class="text-sm font-semibold capitalize tracking-tight">{{ engine }}</h3>
              <Badge size="sm" variant="success" dot>{{ rows.length }} live</Badge>
            </div>
            <div class="db-live-grid">
              <article
                v-for="row in rows"
                :key="`${row.engine}-${row.name}-${row.path || ''}`"
                class="db-live-card"
              >
                <header class="db-live-card__head">
                  <div class="min-w-0 flex-1">
                    <button
                      type="button"
                      class="db-live-card__name"
                      :title="row.path || row.name"
                      @click="openLive(row)"
                    >
                      {{ row.name }}
                    </button>
                    <p v-if="row.path" class="db-live-card__path" :title="row.path">{{ row.path }}</p>
                    <p v-else-if="row.owner" class="db-live-card__meta">owner · {{ row.owner }}</p>
                  </div>
                  <Badge v-if="isManaged(row)" size="sm" variant="info">managed</Badge>
                </header>

                <dl class="db-live-card__stats">
                  <div>
                    <dt>{{ row.engine === 'mongodb' ? 'Collections' : 'Tables' }}</dt>
                    <dd>{{ row.table_count ?? '—' }}</dd>
                  </div>
                  <div>
                    <dt>Size</dt>
                    <dd>{{ formatBytes(row.size_bytes) || '—' }}</dd>
                  </div>
                  <div>
                    <dt>Engine</dt>
                    <dd class="capitalize">{{ row.engine }}</dd>
                  </div>
                </dl>

                <footer class="db-live-card__actions">
                  <button type="button" class="db-live-btn is-primary" @click="openLive(row)">
                    Open studio
                  </button>
                  <button
                    v-if="canWrite && !isManaged(row)"
                    type="button"
                    class="db-live-btn"
                    :disabled="actionKey === `adopt-${liveKey(row)}`"
                    @click="adoptLive(row)"
                  >
                    {{ actionKey === `adopt-${liveKey(row)}` ? 'Adopting…' : 'Manage' }}
                  </button>
                  <button
                    v-if="canWrite"
                    type="button"
                    class="db-live-btn is-danger"
                    :disabled="actionKey === `live-del-${liveKey(row)}`"
                    @click="dropLive(row)"
                  >
                    {{ actionKey === `live-del-${liveKey(row)}` ? 'Dropping…' : 'Drop' }}
                  </button>
                </footer>
              </article>
            </div>
          </section>
        </div>
      </Card>

      <Card v-if="showRestore && canWrite" title="Restore database">
        <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="restoreDatabase">
          <label class="block text-sm">
            <span class="text-surface-muted">Engine</span>
            <select v-model="restoreEngine" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2">
              <option value="mysql">MySQL</option>
              <option value="postgresql">PostgreSQL</option>
              <option value="sqlite">SQLite</option>
              <option value="mongodb">MongoDB</option>
            </select>
          </label>
          <label class="block text-sm">
            <span class="text-surface-muted">Target database name</span>
            <input v-model="restoreName" required class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm" />
          </label>
          <label v-if="restoreEngine === 'sqlite'" class="block text-sm sm:col-span-2">
            <span class="text-surface-muted">SQLite destination path</span>
            <input v-model="restorePath" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm" />
          </label>
          <label class="block text-sm sm:col-span-2">
            <span class="text-surface-muted">Dump file</span>
            <input type="file" class="mt-1 w-full text-sm" @change="restoreFile = ($event.target as HTMLInputElement).files?.[0] || null" />
          </label>
          <label class="block text-sm sm:col-span-2">
            <span class="text-surface-muted">Dashboard password</span>
            <input v-model="restorePassword" type="password" required class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2" />
          </label>
          <div class="sm:col-span-2">
            <button type="submit" class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" :disabled="restoreBusy || !restoreFile">
              {{ restoreBusy ? 'Restoring…' : 'Restore' }}
            </button>
          </div>
        </form>
      </Card>

      <Card v-if="backups.length" title="Recent backups">
        <ul class="space-y-2 text-sm">
          <li v-for="b in backups.slice(0, 12)" :key="b.id" class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border/70 px-3 py-2">
            <div class="min-w-0">
              <p class="truncate font-mono text-xs">{{ b.filename }}</p>
              <p class="text-[11px] text-surface-muted">{{ b.engine }} · {{ b.database }} · {{ b.kind }} · {{ formatBytes(b.size_bytes) }}</p>
            </div>
            <button type="button" class="text-xs text-brand-700 dark:text-brand-300" @click="downloadBackup(b.id, b.filename)">
              Download
            </button>
          </li>
        </ul>
      </Card>
    </div>

    <ConfirmPasswordModal
      :open="!!dropTarget"
      :title="dropTitle"
      :description="dropDescription"
      :busy="dropBusy"
      :error="dropError"
      confirm-label="Backup & drop"
      @cancel="dropTarget = null; dropError = null"
      @confirm="confirmDrop"
    />
  </DashboardLayout>
</template>

<style scoped>
.db-page {
  display: grid;
  gap: 1.5rem;
}
.db-hero {
  position: relative;
  display: flex;
  overflow: hidden;
  align-items: flex-end;
  justify-content: space-between;
  gap: 2rem;
  border: 1px solid rgb(15 118 110 / 0.18);
  border-radius: 1.35rem;
  background:
    radial-gradient(34rem 16rem at 92% 5%, rgb(45 212 191 / 0.16), transparent 70%),
    linear-gradient(135deg, rgb(15 118 110 / 0.09), rgb(255 255 255 / 0.7));
  padding: clamp(1.25rem, 3vw, 2rem);
}
.dark .db-hero {
  background:
    radial-gradient(34rem 16rem at 92% 5%, rgb(45 212 191 / 0.13), transparent 70%),
    linear-gradient(135deg, rgb(15 118 110 / 0.13), rgb(15 23 42 / 0.8));
}
.db-hero-copy {
  max-width: 43rem;
}
.db-eyebrow,
.db-section-heading span {
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #0f766e;
}
.dark .db-eyebrow,
.dark .db-section-heading span {
  color: #5eead4;
}
.db-hero h1 {
  margin-top: 0.35rem;
  font-size: clamp(1.8rem, 3.5vw, 2.7rem);
  font-weight: 720;
  letter-spacing: -0.045em;
  line-height: 1;
  color: #0f172a;
}
.dark .db-hero h1 {
  color: #f8fafc;
}
.db-hero-copy > p {
  margin-top: 0.75rem;
  max-width: 38rem;
  color: var(--color-text-muted);
  font-size: 0.9rem;
  line-height: 1.6;
}
.db-health-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 1.2rem;
  margin-top: 1.15rem;
  color: var(--color-text-muted);
  font-size: 0.73rem;
}
.db-health-row strong {
  color: #0f766e;
  font-size: 0.85rem;
}
.dark .db-health-row strong {
  color: #5eead4;
}
.db-hero-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.55rem;
}
.db-button {
  border: 1px solid transparent;
  border-radius: 0.7rem;
  padding: 0.55rem 0.85rem;
  font-size: 0.78rem;
  font-weight: 650;
  transition: background 150ms ease, border-color 150ms ease, transform 150ms ease;
}
.db-button:hover:not(:disabled) {
  transform: translateY(-1px);
}
.db-button.is-primary {
  background: #0f766e;
  color: #fff;
  box-shadow: 0 8px 20px rgb(15 118 110 / 0.2);
}
.db-button.is-primary:hover:not(:disabled) {
  background: #115e59;
}
.db-button.is-quiet {
  border-color: var(--color-border);
  background: color-mix(in srgb, var(--color-surface-raised) 88%, transparent);
  color: inherit;
}
.db-button.is-quiet:hover:not(:disabled) {
  background: rgb(15 118 110 / 0.08);
  border-color: rgb(15 118 110 / 0.25);
}
.db-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.db-tabs {
  display: flex;
  gap: 0.35rem;
  overflow-x: auto;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 0.6rem;
}
.db-tabs button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0.45rem;
  border: 0;
  border-radius: 0.65rem;
  background: transparent;
  padding: 0.5rem 0.7rem;
  color: var(--color-text-muted);
  font-size: 0.76rem;
  font-weight: 650;
  text-transform: capitalize;
}
.db-tabs button:hover {
  background: rgb(148 163 184 / 0.1);
  color: inherit;
}
.db-tabs button.active {
  background: rgb(15 118 110 / 0.11);
  color: #0f766e;
}
.dark .db-tabs button.active {
  color: #5eead4;
}
.db-tabs button span {
  min-width: 1.2rem;
  border-radius: 999px;
  background: rgb(148 163 184 / 0.15);
  padding: 0.08rem 0.35rem;
  text-align: center;
  font-size: 0.62rem;
}
.db-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.8rem;
}
.db-stat {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  background: var(--color-surface-raised);
  padding: 1rem;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.03);
}
.db-stat-icon,
.db-engine-mark {
  display: grid;
  flex: 0 0 auto;
  width: 2.6rem;
  height: 2.6rem;
  place-items: center;
  border-radius: 0.75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.72rem;
  font-weight: 800;
}
.db-stat-icon.is-teal {
  background: rgb(20 184 166 / 0.13);
  color: #0f766e;
}
.db-stat-icon.is-blue {
  background: rgb(59 130 246 / 0.12);
  color: #2563eb;
}
.db-stat-icon.is-violet {
  background: rgb(139 92 246 / 0.12);
  color: #7c3aed;
}
.db-stat p {
  color: var(--color-text-muted);
  font-size: 0.68rem;
  font-weight: 650;
  text-transform: uppercase;
  letter-spacing: 0.045em;
}
.db-stat strong {
  display: block;
  margin-top: 0.1rem;
  font-size: 1.45rem;
  line-height: 1.1;
}
.db-stat span {
  display: block;
  margin-top: 0.2rem;
  color: var(--color-text-muted);
  font-size: 0.66rem;
}
.db-section-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}
.db-section-heading h2 {
  margin-top: 0.15rem;
  font-size: 1rem;
  font-weight: 700;
}
.db-section-heading > p {
  color: var(--color-text-muted);
  font-size: 0.72rem;
}
.db-engine-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.8rem;
}
.db-engine {
  cursor: pointer;
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  background: var(--color-surface-raised);
  padding: 0.9rem;
  transition: border-color 150ms ease, transform 150ms ease, box-shadow 150ms ease;
}
.db-engine:hover,
.db-engine.selected {
  transform: translateY(-1px);
  border-color: rgb(15 118 110 / 0.35);
  box-shadow: 0 10px 24px rgb(15 23 42 / 0.06);
}
.db-engine-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.65rem;
}
.db-engine-head > div:nth-child(2) {
  min-width: 0;
  flex: 1;
}
.db-engine-mark {
  width: 2.2rem;
  height: 2.2rem;
  background: rgb(15 118 110 / 0.1);
  color: #0f766e;
}
.dark .db-engine-mark {
  color: #5eead4;
}
.db-engine h3 {
  font-size: 0.82rem;
  font-weight: 700;
  text-transform: capitalize;
}
.db-engine-head p,
.db-engine-version,
.db-engine-warning {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
  font-size: 0.64rem;
}
.db-engine-version {
  margin-top: 0.7rem;
}
.db-engine-warning {
  margin-top: 0.45rem;
  color: #b45309;
  white-space: normal;
}
.db-live-section {
  min-width: 0;
}
.db-live-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16.5rem, 1fr));
  gap: 0.85rem;
}
.db-live-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.85rem;
  border: 1px solid var(--color-border);
  border-radius: 0.95rem;
  background:
    linear-gradient(165deg, color-mix(in srgb, var(--color-surface-raised) 92%, rgb(15 118 110) 8%), var(--color-surface-raised));
  padding: 0.95rem 1rem;
  box-shadow: 0 1px 0 rgb(15 23 42 / 0.03);
}
.db-live-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.65rem;
}
.db-live-card__name {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #0f766e;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  text-align: left;
}
.db-live-card__name:hover {
  text-decoration: underline;
}
.dark .db-live-card__name {
  color: #5eead4;
}
.db-live-card__path,
.db-live-card__meta {
  margin-top: 0.25rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
  font-size: 0.68rem;
}
.db-live-card__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.45rem;
  margin: 0;
}
.db-live-card__stats > div {
  min-width: 0;
  border-radius: 0.55rem;
  background: color-mix(in srgb, var(--color-surface-muted) 55%, transparent);
  padding: 0.45rem 0.5rem;
}
.db-live-card__stats dt {
  color: var(--color-text-muted);
  font-size: 0.58rem;
  font-weight: 650;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.db-live-card__stats dd {
  margin: 0.15rem 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.78rem;
  font-weight: 650;
}
.db-live-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: auto;
}
.db-live-btn {
  border: 1px solid var(--color-border);
  border-radius: 0.55rem;
  background: color-mix(in srgb, var(--color-surface-raised) 90%, transparent);
  padding: 0.35rem 0.6rem;
  color: inherit;
  font-size: 0.68rem;
  font-weight: 650;
}
.db-live-btn.is-primary {
  border-color: rgb(15 118 110 / 0.35);
  background: rgb(15 118 110 / 0.1);
  color: #0f766e;
}
.dark .db-live-btn.is-primary {
  color: #5eead4;
}
.db-live-btn.is-danger {
  border-color: rgb(239 68 68 / 0.25);
  color: #dc2626;
}
.db-live-btn:disabled {
  opacity: 0.55;
}
.db-live-group {
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  background: color-mix(in srgb, var(--color-surface-raised) 94%, rgb(15 118 110) 6%);
  padding: 0.8rem;
}
@media (max-width: 1100px) {
  .db-engine-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 760px) {
  .db-hero {
    align-items: stretch;
    flex-direction: column;
  }
  .db-hero-actions {
    justify-content: flex-start;
  }
  .db-stats,
  .db-engine-grid {
    grid-template-columns: 1fr;
  }
  .db-section-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>

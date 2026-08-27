<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Badge from '@/components/ui/Badge.vue'
import CodeEditor from '@/components/files/CodeEditor.vue'
import AiAgentPanel from '@/components/ai/AiAgentPanel.vue'
import { databasesApi, authApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import { useThemeStore } from '@/stores/theme'
import type { DatabaseEngine, DbQueryResult, DbSchema, DbTable } from '@/types/databases'

type StudioColorMode = 'light' | 'dark'

const UNLOCK_KEY = 'ifnotus.databases.unlocked_at'
const UNLOCK_TTL_MS = 30 * 60 * 1000

const route = useRoute()
const router = useRouter()
const theme = useThemeStore()
const { can } = usePermissions()
const canWrite = computed(() => can(Permission.DATABASES_WRITE))
const canRunQuery = computed(() => can(Permission.DATABASES_READ) || canWrite.value)

function isStudioWrite(text: string): boolean {
  const s = (text || '').trim()
  if (!s) return false
  if (isMongo.value) {
    return /\.(insert(?:One|Many)?|update(?:One|Many)?|delete(?:One|Many)?|remove|drop|create(?:Index|Collection)?|bulkWrite|findAndModify|renameCollection|replaceOne)\b/i.test(s)
      || /^\s*(?:db\.dropDatabase|dropDatabase)\b/i.test(s)
  }
  if (/^\s*(?:WITH\b[\s\S]*?\bAS\s*\([\s\S]*?\)\s*)*(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|RENAME|CALL|EXEC(?:UTE)?|LOAD|COPY|MERGE)\b/i.test(s)) {
    return true
  }
  if (/^\s*(WITH\b[\s\S]*?\bSELECT\b|SELECT\b|SHOW\b|DESCRIBE\b|DESC\b|EXPLAIN\b|PRAGMA\b)\b/i.test(s)) {
    return false
  }
  return true
}

function isStudioDestructive(text: string): boolean {
  const s = (text || '').trim()
  if (!s) return false
  if (isMongo.value) {
    return /\.(?:drop(?:Index|Collection)?|create(?:Index|Collection)?|renameCollection)\b/i.test(s)
      || /^\s*(?:db\.dropDatabase|dropDatabase)\b/i.test(s)
  }
  return /^\s*(?:WITH\b[\s\S]*?\bAS\s*\([\s\S]*?\)\s*)*(ALTER|DROP|CREATE|TRUNCATE|GRANT|REVOKE|RENAME)\b/i.test(s)
}

const unlocked = ref(false)
const unlockBusy = ref(false)
const unlockError = ref<string | null>(null)
const unlockPassword = ref('')

const kind = computed(() => (String(route.query.kind || 'managed') === 'live' ? 'live' : 'managed'))
const dbId = computed(() => String(route.query.id || ''))
const engine = computed(() => String(route.query.engine || '') as DatabaseEngine)
const dbName = computed(() => String(route.query.name || ''))
const dbPath = computed(() => String(route.query.path || '') || undefined)

const loading = ref(true)
const error = ref<string | null>(null)
const schema = ref<DbSchema | null>(null)
const selectedTable = ref<string | null>(null)
const selectedCollection = ref<string | null>(null)
const result = ref<DbQueryResult | null>(null)
const sql = ref('SELECT * FROM ')
const queryRunning = ref(false)
const rowsLoading = ref(false)
const message = ref<{ ok: boolean; text: string } | null>(null)
const showAi = ref(false)
const editing = ref<Record<string, unknown> | null>(null)
const editValues = ref<Record<string, string>>({})
const editMode = ref<'edit' | 'insert'>('edit')
const lastSyncedAt = ref<Date | null>(null)
const schemaRefreshing = ref(false)
const resultMode = ref<'table' | 'query'>('table')
const THEME_KEY = 'ifnotus.studio.theme'
const SCHEMA_WIDTH_KEY = 'ifnotus.studio.schema_width'
const storedTheme = localStorage.getItem(THEME_KEY) as StudioColorMode | null
const colorMode = ref<StudioColorMode>(storedTheme || (theme.isDark ? 'dark' : 'light'))
const schemaWidth = ref(clampSchemaWidth(Number(localStorage.getItem(SCHEMA_WIDTH_KEY) || 240)))
let schemaTimer: number | null = null
let rowsTimer: number | null = null
let resizingSchema = false

function clampSchemaWidth(n: number) {
  if (!Number.isFinite(n)) return 240
  return Math.min(480, Math.max(160, Math.round(n)))
}

function onSchemaResizeStart(event: PointerEvent) {
  resizingSchema = true
  const startX = event.clientX
  const startWidth = schemaWidth.value
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)

  function onMove(e: PointerEvent) {
    if (!resizingSchema) return
    schemaWidth.value = clampSchemaWidth(startWidth + (e.clientX - startX))
  }
  function onUp(e: PointerEvent) {
    resizingSchema = false
    localStorage.setItem(SCHEMA_WIDTH_KEY, String(schemaWidth.value))
    target.releasePointerCapture(e.pointerId)
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

const title = computed(() => {
  if (kind.value === 'managed') return schema.value?.database || dbId.value || 'Database'
  return `${engine.value} · ${dbName.value || schema.value?.database || 'live'}`
})

const tables = computed(() => schema.value?.tables || [])
const collections = computed(() => schema.value?.collections || [])
const isMongo = computed(() => (schema.value?.engine || engine.value) === 'mongodb')
const activeTable = computed(() => tables.value.find((t) => t.name === selectedTable.value) || null)
const pkCols = computed(() => (activeTable.value?.columns || []).filter((c) => c.primary_key).map((c) => c.name))
const objectCount = computed(() => (isMongo.value ? collections.value.length : tables.value.length))
const queryLanguage = computed(() => (isMongo.value ? 'javascript' : 'sql'))
const queryPath = computed(() => (isMongo.value ? 'query.js' : 'query.sql'))

watch(colorMode, (mode) => {
  localStorage.setItem(THEME_KEY, mode)
  document.documentElement.classList.toggle('dark', mode === 'dark')
  document.documentElement.style.colorScheme = mode
})

function isUnlocked() {
  const raw = sessionStorage.getItem(UNLOCK_KEY)
  if (!raw) return false
  const at = Number(raw)
  return Number.isFinite(at) && Date.now() - at < UNLOCK_TTL_MS
}

async function unlockStudio() {
  unlockBusy.value = true
  unlockError.value = null
  try {
    await authApi.confirmPassword(unlockPassword.value)
    sessionStorage.setItem(UNLOCK_KEY, String(Date.now()))
    unlocked.value = true
    unlockPassword.value = ''
    await loadSchema()
  } catch (e) {
    unlockError.value = getApiErrorMessage(e, 'Incorrect dashboard password')
  } finally {
    unlockBusy.value = false
  }
}

async function loadSchema(silent = false) {
  if (!unlocked.value) return
  if (schemaRefreshing.value) return
  schemaRefreshing.value = true
  if (!silent) {
    loading.value = true
    error.value = null
  }
  try {
    if (kind.value === 'managed') {
      if (!dbId.value) throw new Error('Missing database id')
      const { data } = await databasesApi.schema(dbId.value)
      schema.value = data
    } else {
      const { data } = await databasesApi.liveSchema(engine.value, dbName.value, dbPath.value)
      schema.value = data
    }
    lastSyncedAt.value = new Date()
    if (selectedTable.value && !tables.value.some((table) => table.name === selectedTable.value)) {
      selectedTable.value = null
      result.value = null
    }
    if (selectedCollection.value && !collections.value.includes(selectedCollection.value)) {
      selectedCollection.value = null
      result.value = null
    }
    if (!isMongo.value && tables.value.length && !selectedTable.value) {
      selectTable(tables.value[0])
    } else if (isMongo.value && collections.value.length && !selectedCollection.value) {
      selectCollection(collections.value[0])
    }
  } catch (e) {
    if (!silent) error.value = getApiErrorMessage(e, 'Failed to load schema')
  } finally {
    if (!silent) loading.value = false
    schemaRefreshing.value = false
  }
}

async function selectTable(table: DbTable) {
  selectedTable.value = table.name
  selectedCollection.value = null
  sql.value = table.schema_name
    ? `SELECT * FROM "${table.schema_name}"."${table.name}" LIMIT 100`
    : schema.value?.engine === 'mysql'
      ? `SELECT * FROM \`${table.name}\` LIMIT 100`
      : `SELECT * FROM ${table.name} LIMIT 100`
  await loadRows()
}

async function selectCollection(name: string) {
  selectedCollection.value = name
  selectedTable.value = null
  sql.value = `db.getCollection('${name}').find().limit(100).toArray()`
  await loadRows()
}

async function loadRows(force = false) {
  if ((!force && (rowsLoading.value || queryRunning.value)) || editing.value) return
  rowsLoading.value = true
  resultMode.value = 'table'
  try {
    if (kind.value === 'managed') {
      const { data } = await databasesApi.rows(dbId.value, {
        table: selectedTable.value || undefined,
        collection: selectedCollection.value || undefined,
        schema_name: activeTable.value?.schema_name || undefined,
        limit: 100,
      })
      result.value = data
    } else {
      const { data } = await databasesApi.liveRows(engine.value, dbName.value, {
        table: selectedTable.value || undefined,
        collection: selectedCollection.value || undefined,
        schema_name: activeTable.value?.schema_name || undefined,
        path: dbPath.value,
        limit: 100,
      })
      result.value = data
    }
    lastSyncedAt.value = new Date()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Failed to load rows') }
  } finally {
    rowsLoading.value = false
  }
}

async function runQuery() {
  if (queryRunning.value) return
  const text = sql.value || ''
  const write = isStudioWrite(text)
  if (write && !canWrite.value) {
    message.value = { ok: false, text: 'databases:write required for write or DDL queries' }
    return
  }
  let confirmPassword: string | undefined
  if (isStudioDestructive(text)) {
    if (!canWrite.value) {
      message.value = { ok: false, text: 'databases:write required for destructive SQL' }
      return
    }
    const pw = window.prompt('Confirm your dashboard password to run this destructive SQL:')
    if (!pw) {
      message.value = { ok: false, text: 'Destructive SQL cancelled' }
      return
    }
    confirmPassword = pw
  }
  queryRunning.value = true
  message.value = null
  try {
    const body = isMongo.value
      ? { script: sql.value, limit: 200, confirm_password: confirmPassword }
      : { sql: sql.value, limit: 200, confirm_password: confirmPassword }
    if (kind.value === 'managed') {
      const { data } = await databasesApi.query(dbId.value, body)
      result.value = data
    } else {
      const { data } = await databasesApi.liveQuery(engine.value, dbName.value, body, dbPath.value)
      result.value = data
    }
    resultMode.value = 'query'
    message.value = {
      ok: true,
      text: result.value.message
        || (result.value.affected_rows != null
          ? `Affected ${result.value.affected_rows} row(s)`
          : `${result.value.row_count} row(s)`),
    }
    const changesData = isMongo.value
      || !!result.value.message
      || result.value.affected_rows != null
      || /^\s*(create|alter|drop|truncate|insert|update|delete|replace|grant|revoke)\b/i.test(sql.value)
    if (changesData) {
      await loadSchema(true)
      if (selectedTable.value || selectedCollection.value) await loadRows(true)
    }
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Query failed') }
  } finally {
    queryRunning.value = false
  }
}

async function onAiApplied(action: { type: string }) {
  if (!['run_sql', 'run_mongo', 'create_database', 'drop_database'].includes(action.type)) return
  await loadSchema(true)
  if (selectedTable.value || selectedCollection.value) await loadRows()
  message.value = { ok: true, text: 'AI changes synced live.' }
}

function startEdit(row: Record<string, unknown>) {
  if (!canWrite.value) return
  editMode.value = 'edit'
  editing.value = { ...row }
  const vals: Record<string, string> = {}
  for (const [k, v] of Object.entries(row)) {
    if (isMongo.value && k === '_id') {
      vals[k] = typeof v === 'object' ? JSON.stringify(v) : String(v)
    } else {
      vals[k] = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)
    }
  }
  editValues.value = vals
}

function startInsert() {
  if (!canWrite.value) return
  editMode.value = 'insert'
  editing.value = {}
  const vals: Record<string, string> = {}
  if (isMongo.value) {
    vals.document = '{\n  \n}'
  } else {
    for (const col of activeTable.value?.columns || []) {
      vals[col.name] = col.default != null ? String(col.default) : ''
    }
  }
  editValues.value = vals
}

function parseCell(raw: string): unknown {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  if (trimmed === 'true') return true
  if (trimmed === 'false') return false
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed)
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
    try {
      return JSON.parse(trimmed)
    } catch {
      return raw
    }
  }
  return raw
}

async function saveEdit() {
  if (!editing.value) return
  queryRunning.value = true
  try {
    if (editMode.value === 'insert') {
      let values: Record<string, unknown> = {}
      if (isMongo.value) {
        values = JSON.parse(editValues.value.document || '{}') as Record<string, unknown>
        const body = { collection: selectedCollection.value || undefined, values }
        if (kind.value === 'managed') await databasesApi.insertRow(dbId.value, body)
        else await databasesApi.liveInsertRow(engine.value, dbName.value, body, dbPath.value)
      } else {
        for (const [k, v] of Object.entries(editValues.value)) {
          values[k] = parseCell(v)
        }
        const body = {
          table: selectedTable.value || undefined,
          schema_name: activeTable.value?.schema_name || undefined,
          values,
        }
        if (kind.value === 'managed') await databasesApi.insertRow(dbId.value, body)
        else await databasesApi.liveInsertRow(engine.value, dbName.value, body, dbPath.value)
      }
      editing.value = null
      message.value = { ok: true, text: 'Row inserted.' }
      await loadRows(true)
      return
    }

    if (isMongo.value && selectedCollection.value) {
      const filter =
        editing.value._id != null
          ? { _id: typeof editing.value._id === 'string' ? editing.value._id : editing.value._id }
          : { ...editing.value }
      const values: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(editValues.value)) {
        if (k === '_id') continue
        values[k] = parseCell(v)
      }
      const body = { collection: selectedCollection.value, filter, values }
      if (kind.value === 'managed') await databasesApi.updateRow(dbId.value, body)
      else await databasesApi.liveUpdateRow(engine.value, dbName.value, body, dbPath.value)
    } else if (selectedTable.value) {
      const pk: Record<string, unknown> = {}
      const keys = pkCols.value.length ? pkCols.value : Object.keys(editing.value).slice(0, 1)
      for (const k of keys) pk[k] = editing.value[k]
      const values: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(editValues.value)) {
        if (keys.includes(k)) continue
        values[k] = parseCell(v)
      }
      const body = {
        table: selectedTable.value,
        schema_name: activeTable.value?.schema_name || undefined,
        primary_key: pk,
        values,
      }
      if (kind.value === 'managed') await databasesApi.updateRow(dbId.value, body)
      else await databasesApi.liveUpdateRow(engine.value, dbName.value, body, dbPath.value)
    }
    editing.value = null
    message.value = { ok: true, text: 'Row updated.' }
    await loadRows(true)
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, editMode.value === 'insert' ? 'Insert failed' : 'Update failed') }
  } finally {
    queryRunning.value = false
  }
}

async function deleteRow(row: Record<string, unknown>) {
  if (!canWrite.value) return
  if (!confirm('Delete this row?')) return
  queryRunning.value = true
  try {
    if (isMongo.value && selectedCollection.value) {
      const filter = row._id != null ? { _id: row._id } : row
      const body = { collection: selectedCollection.value, filter }
      if (kind.value === 'managed') await databasesApi.deleteRow(dbId.value, body)
      else await databasesApi.liveDeleteRow(engine.value, dbName.value, body, dbPath.value)
    } else if (selectedTable.value) {
      const pk: Record<string, unknown> = {}
      const keys = pkCols.value.length ? pkCols.value : Object.keys(row).slice(0, 1)
      for (const k of keys) pk[k] = row[k]
      const body = {
        table: selectedTable.value,
        schema_name: activeTable.value?.schema_name || undefined,
        primary_key: pk,
      }
      if (kind.value === 'managed') await databasesApi.deleteRow(dbId.value, body)
      else await databasesApi.liveDeleteRow(engine.value, dbName.value, body, dbPath.value)
    }
    message.value = { ok: true, text: 'Row deleted.' }
    await loadRows(true)
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Delete failed') }
  } finally {
    queryRunning.value = false
  }
}

function closeWindow() {
  // Prefer closing the popup; noopener-less open is required for this to work.
  try {
    window.close()
  } catch {
    /* ignore */
  }
  // If the browser blocked close (or this isn't a script-opened window), go back to Databases.
  window.setTimeout(() => {
    if (!window.closed) {
      router.push({ name: 'databases' }).catch(() => {
        history.back()
      })
    }
  }, 120)
}

function toggleTheme() {
  colorMode.value = colorMode.value === 'dark' ? 'light' : 'dark'
}

function cell(v: unknown) {
  if (v == null) return 'NULL'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function onKeydown(ev: KeyboardEvent) {
  const mod = ev.metaKey || ev.ctrlKey
  if (!mod) return
  if (ev.key.toLowerCase() === 'enter') {
    ev.preventDefault()
    runQuery()
  }
}

watch([kind, dbId, engine, dbName, dbPath], () => loadSchema(), { immediate: false })
onMounted(() => {
  document.documentElement.classList.toggle('dark', colorMode.value === 'dark')
  document.documentElement.style.colorScheme = colorMode.value
  window.addEventListener('keydown', onKeydown, true)
  unlocked.value = isUnlocked()
  if (unlocked.value) {
    loadSchema()
    schemaTimer = window.setInterval(() => {
      if (!document.hidden && !queryRunning.value && !rowsLoading.value) loadSchema(true)
    }, 5_000)
    rowsTimer = window.setInterval(() => {
      if (
        !document.hidden
        && !queryRunning.value
        && !rowsLoading.value
        && !editing.value
        && resultMode.value === 'table'
        && (selectedTable.value || selectedCollection.value)
      ) {
        loadRows()
      }
    }, 3_000)
  } else {
    loading.value = false
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown, true)
  if (schemaTimer != null) window.clearInterval(schemaTimer)
  if (rowsTimer != null) window.clearInterval(rowsTimer)
})
</script>

<template>
  <div v-if="!unlocked" class="studio-shell is-dark grid h-screen place-items-center p-6">
    <div class="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 text-slate-100">
      <h1 class="text-lg font-semibold">Unlock Database Studio</h1>
      <p class="mt-2 text-sm text-slate-400">Enter your dashboard admin password to open this database.</p>
      <input
        v-model="unlockPassword"
        type="password"
        autocomplete="current-password"
        class="mt-4 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
        @keydown.enter.prevent="unlockStudio"
      />
      <p v-if="unlockError" class="mt-2 text-sm text-red-400">{{ unlockError }}</p>
      <div class="mt-4 flex gap-2">
        <button type="button" class="rounded-lg border border-slate-700 px-3 py-2 text-sm" @click="closeWindow">Close</button>
        <button
          type="button"
          class="rounded-lg bg-teal-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          :disabled="unlockBusy || !unlockPassword.trim()"
          @click="unlockStudio"
        >
          {{ unlockBusy ? 'Checking…' : 'Unlock' }}
        </button>
      </div>
    </div>
  </div>

  <div v-else class="studio-shell" :class="colorMode === 'dark' ? 'is-dark' : 'is-light'">
    <header class="studio-top">
      <div class="studio-identity">
        <button type="button" class="icon-btn" title="Close" @click="closeWindow">←</button>
        <span class="ext-chip">{{ isMongo ? 'MONGO' : 'SQL' }}</span>
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold">
            {{ title }}
            <span v-if="queryRunning" class="hint-inline">running</span>
          </p>
          <p class="truncate font-mono text-[11px] opacity-60">
            {{ schema?.path || schema?.database || dbName || dbId }}
          </p>
        </div>
      </div>

      <div class="studio-tools">
        <Badge v-if="schema" size="sm">{{ schema.engine }}</Badge>
        <Badge size="sm" variant="info">{{ kind }}</Badge>
        <Badge v-if="schema" size="sm" variant="success" dot>
          {{ objectCount }} {{ isMongo ? 'collections' : 'tables' }}
        </Badge>
        <span v-if="lastSyncedAt" class="sync-label">{{ lastSyncedAt.toLocaleTimeString() }}</span>
        <button type="button" class="tool-btn" @click="loadSchema()">Refresh</button>
        <button type="button" class="tool-btn" @click="toggleTheme">
          {{ colorMode === 'dark' ? 'Light' : 'Dark' }}
        </button>
        <button type="button" class="tool-btn" @click="showAi = !showAi">
          {{ showAi ? 'Hide AI' : 'AI' }}
        </button>
        <button type="button" class="tool-btn" @click="closeWindow">Close</button>
      </div>
    </header>

    <p v-if="message" class="banner" :class="message.ok ? 'is-ok' : 'is-err'">
      {{ message.text }}
      <span v-if="result?.duration_ms != null" class="opacity-70"> · {{ result.duration_ms.toFixed(0) }}ms</span>
    </p>

    <div v-if="loading" class="pad muted">Loading schema…</div>
    <div v-else-if="error" class="pad err">{{ error }}</div>

    <div
      v-else
      class="studio-body"
      :style="{ gridTemplateColumns: `${schemaWidth}px 6px minmax(0, 1fr)` }"
    >
      <aside class="schema-pane">
        <p class="pane-label">{{ isMongo ? 'Collections' : 'Tables' }}</p>
        <button
          v-for="t in tables"
          :key="(t.schema_name || '') + t.name"
          type="button"
          class="schema-item"
          :class="{ active: selectedTable === t.name }"
          @click="selectTable(t)"
        >
          <span class="truncate font-mono">{{ t.schema_name ? `${t.schema_name}.` : '' }}{{ t.name }}</span>
          <span v-if="t.approx_rows != null && t.approx_rows > 0" class="count">{{ t.approx_rows }}</span>
        </button>
        <button
          v-for="c in collections"
          :key="c"
          type="button"
          class="schema-item font-mono"
          :class="{ active: selectedCollection === c }"
          @click="selectCollection(c)"
        >
          {{ c }}
        </button>
      </aside>

      <div
        class="schema-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize tables panel"
        title="Drag to resize"
        @pointerdown.prevent="onSchemaResizeStart"
      />

      <main class="work-pane">
        <section class="query-pane">
          <div class="query-toolbar">
            <span class="pane-label">Query editor</span>
            <span class="hint">⌘/Ctrl + Enter to run</span>
            <button
              type="button"
              class="run-btn"
              :disabled="queryRunning || !canRunQuery"
              @click="runQuery"
            >
              {{ queryRunning ? 'Running…' : 'Run' }}
            </button>
          </div>
          <div class="editor-frame">
            <CodeEditor
              v-model="sql"
              :path="queryPath"
              :language="queryLanguage"
              :readonly="!canRunQuery"
              :color-mode="colorMode"
              :font-size="13"
              :word-wrap="true"
              :minimap="false"
              @save="runQuery"
            />
          </div>
        </section>

        <section class="result-pane">
          <div class="result-toolbar">
            <span class="pane-label">Results</span>
            <span v-if="result" class="hint">{{ result.row_count }} row(s)</span>
            <button
              v-if="canWrite && (selectedTable || selectedCollection)"
              type="button"
              class="tool-btn"
              @click="startInsert"
            >
              Insert {{ isMongo ? 'document' : 'row' }}
            </button>
          </div>
          <div class="result-scroll">
            <p v-if="!result" class="empty">Select a table or run a query.</p>
            <p v-else-if="result.message && !result.columns.length" class="msg-block">{{ result.message }}</p>
            <table v-else-if="result.columns.length" class="data-table">
              <thead>
                <tr>
                  <th class="row-num">#</th>
                  <th v-for="col in result.columns" :key="col">{{ col }}</th>
                  <th v-if="canWrite">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in result.rows" :key="idx">
                  <td class="row-num">{{ idx + 1 }}</td>
                  <td v-for="col in result.columns" :key="col">
                    <span :class="row[col] == null ? 'nullish' : ''">{{ cell(row[col]) }}</span>
                  </td>
                  <td v-if="canWrite" class="actions">
                    <button type="button" class="link" @click="startEdit(row)">Edit</button>
                    <button type="button" class="link danger" @click="deleteRow(row)">Delete</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="editing" class="edit-drawer">
            <p class="pane-label">{{ editMode === 'insert' ? (isMongo ? 'Insert document' : 'Insert row') : 'Edit row' }}</p>
            <div class="edit-grid">
              <label v-for="(_val, key) in editValues" :key="key">
                <span>{{ key }}</span>
                <textarea
                  v-if="key === 'document' || String(key).length > 40 || (_val && _val.length > 80)"
                  v-model="editValues[key]"
                  rows="6"
                />
                <input
                  v-else
                  v-model="editValues[key]"
                  :disabled="editMode === 'edit' && !isMongo && pkCols.includes(String(key))"
                />
              </label>
            </div>
            <div class="edit-actions">
              <button type="button" class="run-btn" :disabled="queryRunning" @click="saveEdit">
                {{ editMode === 'insert' ? 'Insert' : 'Save' }}
              </button>
              <button type="button" class="tool-btn" @click="editing = null">Cancel</button>
            </div>
          </div>
        </section>
      </main>

      <Transition name="ai-drawer">
      <aside v-if="showAi" class="ai-pane">
        <div class="ai-pane-bar">
          <div>
            <p>Database assistant</p>
            <span>{{ selectedTable || selectedCollection || schema?.database }}</span>
          </div>
          <button type="button" aria-label="Close AI assistant" @click="showAi = false">×</button>
        </div>
        <AiAgentPanel
          surface="studio"
          :path="schema?.path || schema?.database || dbName || dbId"
          compact
          class="h-full"
          @applied="onAiApplied"
        />
      </aside>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.studio-shell {
  display: flex;
  height: 100vh;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(900px 320px at 8% -10%, rgb(15 118 110 / 0.1), transparent 55%),
    var(--bg);
  color: var(--fg);
  --bg: #f4f6f8;
  --fg: #0f172a;
  --panel: #ffffff;
  --line: rgb(15 23 42 / 0.1);
  --muted: #64748b;
  --accent: #0f766e;
  --ok: #047857;
  --err: #b91c1c;
}
.studio-shell.is-dark {
  --bg: #0b1220;
  --fg: #e2e8f0;
  --panel: #111827;
  --line: rgb(148 163 184 / 0.18);
  --muted: #94a3b8;
  --accent: #2dd4bf;
  --ok: #34d399;
  --err: #fca5a5;
}
.studio-top {
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
.studio-identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.65rem;
}
.ext-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 3.1rem;
  border-radius: 0.55rem;
  background: rgb(15 118 110 / 0.14);
  color: var(--accent);
  padding: 0.35rem 0.45rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.live-dot {
  margin-left: 0.35rem;
  color: var(--ok);
  font-size: 0.7rem;
}
.hint-inline {
  margin-left: 0.4rem;
  font-size: 0.7rem;
  font-weight: 500;
  color: var(--muted);
}
.studio-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}
.sync-label {
  font-size: 0.7rem;
  color: var(--muted);
}
.icon-btn,
.tool-btn,
.run-btn {
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
.tool-btn:hover,
.icon-btn:hover {
  background: rgb(15 118 110 / 0.12);
}
.run-btn {
  border-color: transparent;
  background: #0f766e;
  color: white;
  font-weight: 600;
}
.run-btn:disabled {
  opacity: 0.55;
}
.banner {
  border-bottom: 1px solid var(--line);
  padding: 0.45rem 0.9rem;
  font-size: 0.8rem;
}
.banner.is-ok {
  background: rgb(16 185 129 / 0.1);
  color: var(--ok);
}
.banner.is-err {
  background: rgb(239 68 68 / 0.1);
  color: var(--err);
}
.pad {
  padding: 1.5rem;
}
.pad.muted { color: var(--muted); }
.pad.err { color: var(--err); }
.studio-body {
  position: relative;
  display: grid;
  min-height: 0;
  flex: 1;
  grid-template-columns: 15rem 6px minmax(0, 1fr);
}
.schema-pane {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  border-right: none;
  background: color-mix(in srgb, var(--panel) 88%, transparent);
}
.schema-resizer {
  position: relative;
  z-index: 5;
  cursor: col-resize;
  touch-action: none;
  background: var(--line);
}
.schema-resizer::after {
  content: '';
  position: absolute;
  inset: 0 -4px;
}
.schema-resizer:hover,
.schema-resizer:active {
  background: color-mix(in srgb, #0f766e 55%, var(--line));
}
.ai-pane {
  position: absolute;
  z-index: 20;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  width: min(27rem, calc(100vw - 2rem));
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--line);
  background: var(--panel);
  box-shadow: -18px 0 50px rgb(15 23 42 / 0.16);
}
.ai-pane-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border-bottom: 1px solid var(--line);
  padding: 0.65rem 0.75rem;
}
.ai-pane-bar p {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--fg);
}
.ai-pane-bar span {
  display: block;
  max-width: 20rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.65rem;
  color: var(--muted);
}
.ai-pane-bar button {
  display: grid;
  width: 1.8rem;
  height: 1.8rem;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: transparent;
  color: var(--muted);
  font-size: 1.1rem;
}
.ai-pane :deep(.ai-panel) {
  min-height: 0;
  flex: 1;
  border: 0;
  border-radius: 0;
}
.ai-pane :deep(.ai-messages) {
  min-height: 0;
  max-height: none;
}
.ai-drawer-enter-active,
.ai-drawer-leave-active {
  transition: transform 180ms ease, opacity 180ms ease;
}
.ai-drawer-enter-from,
.ai-drawer-leave-to {
  transform: translateX(1rem);
  opacity: 0;
}
.schema-pane {
  padding: 0.65rem;
}
.pane-label {
  margin: 0;
  padding: 0.25rem 0.35rem 0.55rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}
.schema-item {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  border-radius: 0.55rem;
  border: 0;
  background: transparent;
  padding: 0.45rem 0.5rem;
  text-align: left;
  font-size: 0.78rem;
  color: inherit;
}
.schema-item:hover {
  background: rgb(15 118 110 / 0.08);
}
.schema-item.active {
  background: rgb(15 118 110 / 0.16);
  color: var(--accent);
}
.count {
  font-size: 0.65rem;
  color: var(--muted);
}
.work-pane {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: minmax(11rem, 34%) minmax(0, 1fr);
}
.query-pane,
.result-pane {
  display: flex;
  min-height: 0;
  flex-direction: column;
  background: var(--panel);
}
.query-pane {
  border-bottom: 1px solid var(--line);
}
.query-toolbar,
.result-toolbar {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  border-bottom: 1px solid var(--line);
  padding: 0.45rem 0.7rem;
}
.hint {
  font-size: 0.7rem;
  color: var(--muted);
}
.query-toolbar .run-btn {
  margin-left: auto;
}
.editor-frame {
  min-height: 0;
  flex: 1;
  overflow: hidden;
}
.editor-frame :deep(.code-editor),
.editor-frame :deep(.code-editor-host) {
  height: 100%;
  min-height: 9rem;
  border: 0;
  border-radius: 0;
}
.result-scroll {
  min-height: 0;
  flex: 1;
  overflow: auto;
}
.empty,
.msg-block {
  padding: 1rem;
  font-size: 0.85rem;
  color: var(--muted);
}
.msg-block {
  white-space: pre-wrap;
  font-family: 'JetBrains Mono', 'SF Mono', Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
  color: inherit;
}
.data-table {
  width: 100%;
  min-width: max-content;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.78rem;
  font-family: 'JetBrains Mono', 'SF Mono', Menlo, Monaco, Consolas, monospace;
}
.data-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 92%, #0f766e 8%);
  padding: 0.55rem 0.7rem;
  font-weight: 650;
  white-space: nowrap;
}
.data-table td {
  border-bottom: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
  padding: 0.45rem 0.7rem;
  white-space: pre;
  vertical-align: top;
}
.data-table th.row-num,
.data-table td.row-num {
  position: sticky;
  left: 0;
  z-index: 2;
  width: 3rem;
  min-width: 3rem;
  text-align: right;
  color: var(--muted);
  background: var(--panel);
  border-right: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
  user-select: none;
}
.data-table th.row-num {
  z-index: 3;
  background: color-mix(in srgb, var(--panel) 92%, #0f766e 8%);
}
.data-table tr:hover td {
  background: rgb(15 118 110 / 0.06);
}
.data-table tr:hover td.row-num {
  background: color-mix(in srgb, var(--panel) 88%, #0f766e 12%);
}
.nullish {
  font-style: italic;
  color: var(--muted);
}
.actions {
  white-space: nowrap;
}
.link {
  margin-right: 0.55rem;
  border: 0;
  background: transparent;
  color: var(--accent);
  font-size: 0.75rem;
}
.link.danger {
  color: #ef4444;
}
.edit-drawer {
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 94%, #0f766e 6%);
  padding: 0.75rem;
}
.edit-grid {
  display: grid;
  max-height: 10rem;
  gap: 0.55rem;
  overflow: auto;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
}
.edit-grid label {
  display: grid;
  gap: 0.25rem;
  font-size: 0.72rem;
  color: var(--muted);
}
.edit-grid input,
.edit-grid textarea {
  border-radius: 0.5rem;
  border: 1px solid var(--line);
  background: transparent;
  color: inherit;
  padding: 0.4rem 0.55rem;
  font-family: 'JetBrains Mono', Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
}
.edit-grid textarea {
  min-height: 6rem;
  resize: vertical;
}
.edit-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.7rem;
}
@media (max-width: 980px) {
  .studio-body {
    grid-template-columns: 1fr !important;
    grid-template-rows: 10rem 0 minmax(0, 1fr);
  }
  .schema-resizer {
    display: none;
  }
  .ai-pane {
    width: min(25rem, 94vw);
  }
}
</style>

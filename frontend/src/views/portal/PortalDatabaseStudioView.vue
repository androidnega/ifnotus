<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Badge from '@/components/ui/Badge.vue'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { DbQueryResult, DbSchema, DbTable } from '@/types/databases'
import type { EnvironmentDatabaseV2Response } from '@/api'

type Tab = 'structure' | 'browse' | 'sql' | 'import'
type ColorMode = 'light' | 'dark'

const route = useRoute()
const router = useRouter()

const envId = computed(() => String(route.query.env || ''))
const THEME_KEY = 'ifnotus.portal.studio.theme'
const colorMode = ref<ColorMode>((localStorage.getItem(THEME_KEY) as ColorMode) || 'light')

const loading = ref(true)
const busy = ref(false)
const pmaBusy = ref(false)
const error = ref<string | null>(null)
const message = ref<{ ok: boolean; text: string } | null>(null)
const meta = ref<{ engine?: string | null; name?: string | null; domain?: string | null }>({})
const canWrite = ref(true)
const schema = ref<DbSchema | null>(null)
const tab = ref<Tab>('browse')
const selectedTable = ref<string | null>(null)
const offset = ref(0)
const pageSize = 50
const rows = ref<DbQueryResult | null>(null)
const sql = ref('SELECT * FROM ')
const queryResult = ref<DbQueryResult | null>(null)
const editing = ref<Record<string, unknown> | null>(null)
const editMode = ref<'edit' | 'insert'>('edit')
const editValues = ref<Record<string, string>>({})

const databases = ref<EnvironmentDatabaseV2Response[]>([])
const selectedDbId = ref<string | null>(null)
const hasNoDatabase = ref(false)
const createDbBusy = ref(false)

const importFile = ref<File | null>(null)
const importSqlText = ref('')
const importBusy = ref(false)
const importMsg = ref<{ ok: boolean; text: string } | null>(null)

const showGuide = ref(false)
const selectedGuideTab = ref<'mysql' | 'postgres' | 'laravel' | 'wordpress'>('mysql')

const tables = computed(() => schema.value?.tables || [])
const activeTable = computed(() => tables.value.find((t) => t.name === selectedTable.value) || null)
const pkCols = computed(() => (activeTable.value?.columns || []).filter((c) => c.primary_key).map((c) => c.name))
const title = computed(() => meta.value.name || schema.value?.database || 'SQL studio')
const engineLabel = computed(() => {
  const e = (schema.value?.engine || meta.value.engine || '').toLowerCase()
  if (e === 'mysql' || e === 'mariadb') return 'MySQL'
  if (e === 'postgresql' || e === 'postgres') return 'PostgreSQL'
  return e || 'Database'
})

const isMysql = computed(() => {
  const e = (schema.value?.engine || meta.value.engine || '').toLowerCase()
  return e === 'mysql' || e === 'mariadb'
})

watch(colorMode, (mode) => {
  localStorage.setItem(THEME_KEY, mode)
  document.documentElement.classList.toggle('dark', mode === 'dark')
  document.documentElement.style.colorScheme = mode
})

function cell(v: unknown) {
  if (v == null) return 'NULL'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function quoteIdent(name: string) {
  const eng = (schema.value?.engine || '').toLowerCase()
  if (eng === 'mysql' || eng === 'mariadb') return `\`${name.replace(/`/g, '``')}\``
  return `"${name.replace(/"/g, '""')}"`
}

async function boot() {
  if (!envId.value) {
    error.value = 'Missing site environment.'
    loading.value = false
    return
  }
  loading.value = true
  error.value = null
  hasNoDatabase.value = false
  try {
    const [{ data: db }, dbsRes, dash] = await Promise.all([
      customersApi.getEnvDatabase(envId.value, false).catch(() => ({ data: { engine: null, name: null } as any })),
      customersApi.listEnvDatabasesV2(envId.value).catch(() => ({ data: [] as EnvironmentDatabaseV2Response[] })),
      customersApi.dashboard().catch(() => null),
    ])

    databases.value = dbsRes.data || []

    // If target is specifically phpMyAdmin redirect
    if (route.query.pma === '1' || route.query.target === 'pma') {
      try {
        const { data } = await customersApi.openEnvPhpMyAdmin(envId.value)
        window.location.replace(data.url)
        return
      } catch (e: unknown) {
        // Fall back to SQL studio
      }
    }

    const firstDb = databases.value[0]
    const activeDbName = db?.name || firstDb?.name
    const activeDbEngine = db?.engine || firstDb?.engine

    if (!activeDbName && !activeDbEngine && databases.value.length === 0) {
      hasNoDatabase.value = true
      loading.value = false
      return
    }

    if (firstDb && !selectedDbId.value) {
      selectedDbId.value = firstDb.id
    }

    meta.value = {
      engine: activeDbEngine,
      name: activeDbName,
      domain: dash?.data?.environments?.find((e: any) => e.id === envId.value)?.domain || null,
    }
    const env = dash?.data?.environments?.find((e: any) => e.id === envId.value)
    const level = env?.capabilities?.levels?.db_manage
    canWrite.value = !level || level === 'yes'
    await loadSchema()
  } catch (e) {
    error.value = getApiErrorMessage(e, 'Could not open SQL studio.')
  } finally {
    loading.value = false
  }
}

async function loadSchema() {
  try {
    const { data } = await customersApi.getEnvDatabaseSchema(envId.value)
    schema.value = data
    document.title = `${data.database || 'Database'} · SQL studio`
    if (!selectedTable.value && data.tables?.length) {
      await selectTable(data.tables[0])
    } else if (selectedTable.value) {
      await loadRows()
    }
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Could not load schema.') }
  }
}

async function onDbChange() {
  if (!selectedDbId.value) return
  const target = databases.value.find((d) => d.id === selectedDbId.value)
  if (target) {
    meta.value.name = target.name
    meta.value.engine = target.engine
    selectedTable.value = null
    await loadSchema()
  }
}

async function openPhpMyAdmin() {
  if (!envId.value) return
  pmaBusy.value = true
  try {
    const { data } = await customersApi.openEnvPhpMyAdmin(envId.value)
    window.open(data.url, '_blank')
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Could not launch phpMyAdmin.') }
  } finally {
    pmaBusy.value = false
  }
}

async function createQuickDatabase() {
  createDbBusy.value = true
  message.value = null
  try {
    await customersApi.createEnvDatabase(envId.value, {
      engine: 'mysql',
      logical_name: 'app_db',
    })
    message.value = { ok: true, text: 'MySQL database created successfully!' }
    await boot()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Failed to create database.') }
  } finally {
    createDbBusy.value = false
  }
}

async function selectTable(table: DbTable | string) {
  const name = typeof table === 'string' ? table : table.name
  selectedTable.value = name
  offset.value = 0
  const t = typeof table === 'string' ? tables.value.find((x) => x.name === name) : table
  sql.value = `SELECT * FROM ${quoteIdent(name)} LIMIT 100`
  if (tab.value === 'sql') {
    /* keep sql tab */
  } else if (tab.value !== 'structure') {
    tab.value = 'browse'
  }
  void t
  await loadRows()
}

async function loadRows() {
  if (!selectedTable.value) return
  busy.value = true
  message.value = null
  try {
    const { data } = await customersApi.getEnvDatabaseRows(envId.value, {
      table: selectedTable.value,
      schema_name: activeTable.value?.schema_name || undefined,
      limit: pageSize,
      offset: offset.value,
    })
    rows.value = data
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Could not load rows.') }
  } finally {
    busy.value = false
  }
}

async function runSql() {
  const text = sql.value.trim()
  if (!text) return
  busy.value = true
  message.value = null
  try {
    const { data } = await customersApi.queryEnvDatabase(envId.value, text, 200)
    queryResult.value = data
    tab.value = 'sql'
    message.value = {
      ok: true,
      text:
        data.message ||
        (data.affected_rows != null ? `Affected ${data.affected_rows} row(s)` : `${data.row_count} row(s)`),
    }
    const mutates = /^\s*(create|alter|drop|truncate|insert|update|delete|replace)\b/i.test(text)
    if (mutates) {
      await loadSchema()
    }
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'SQL execution failed.') }
  } finally {
    busy.value = false
  }
}

function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input?.files?.[0]
  if (!f) return
  importFile.value = f
  const reader = new FileReader()
  reader.onload = () => {
    importSqlText.value = String(reader.result || '')
  }
  reader.readAsText(f)
}

async function runImport() {
  const content = importSqlText.value.trim()
  if (!content) return
  importBusy.value = true
  importMsg.value = null
  try {
    const targetId = selectedDbId.value || null
    const { data } = await customersApi.importEnvDatabaseSql(envId.value, targetId, content)
    importMsg.value = { ok: true, text: data.message || 'SQL file imported successfully!' }
    await loadSchema()
  } catch (e) {
    importMsg.value = { ok: false, text: getApiErrorMessage(e, 'Import failed.') }
  } finally {
    importBusy.value = false
  }
}

function parseCell(raw: string): unknown {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  if (trimmed === 'true') return true
  if (trimmed === 'false') return false
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed)
  return raw
}

function startEdit(row: Record<string, unknown>) {
  if (!canWrite.value) return
  editMode.value = 'edit'
  editing.value = { ...row }
  const vals: Record<string, string> = {}
  for (const [k, v] of Object.entries(row)) {
    vals[k] = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)
  }
  editValues.value = vals
}

function startInsert() {
  if (!canWrite.value || !activeTable.value) return
  editMode.value = 'insert'
  editing.value = {}
  const vals: Record<string, string> = {}
  for (const col of activeTable.value.columns || []) {
    vals[col.name] = col.default != null ? String(col.default) : ''
  }
  editValues.value = vals
}

function cancelEdit() {
  editing.value = null
  editValues.value = {}
}

async function saveEdit() {
  if (!selectedTable.value || !editing.value) return
  busy.value = true
  try {
    const values: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(editValues.value)) {
      values[k] = parseCell(v)
    }
    if (editMode.value === 'insert') {
      await customersApi.insertEnvDatabaseRow(envId.value, {
        table: selectedTable.value,
        schema_name: activeTable.value?.schema_name || undefined,
        values,
      })
      message.value = { ok: true, text: 'Row inserted.' }
    } else {
      const pk: Record<string, unknown> = {}
      const keys = pkCols.value.length ? pkCols.value : Object.keys(editing.value).slice(0, 1)
      for (const k of keys) pk[k] = editing.value[k]
      await customersApi.updateEnvDatabaseRow(envId.value, {
        table: selectedTable.value,
        schema_name: activeTable.value?.schema_name || undefined,
        primary_key: pk,
        values,
      })
      message.value = { ok: true, text: 'Row updated.' }
    }
    cancelEdit()
    await loadRows()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Save failed.') }
  } finally {
    busy.value = false
  }
}

async function deleteRow(row: Record<string, unknown>) {
  if (!canWrite.value || !selectedTable.value) return
  if (!confirm('Delete this row?')) return
  busy.value = true
  try {
    const pk: Record<string, unknown> = {}
    const keys = pkCols.value.length ? pkCols.value : Object.keys(row).slice(0, 1)
    for (const k of keys) pk[k] = row[k]
    await customersApi.deleteEnvDatabaseRow(envId.value, {
      table: selectedTable.value,
      schema_name: activeTable.value?.schema_name || undefined,
      primary_key: pk,
    })
    message.value = { ok: true, text: 'Row deleted.' }
    await loadRows()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Delete failed.') }
  } finally {
    busy.value = false
  }
}

function prevPage() {
  offset.value = Math.max(0, offset.value - pageSize)
  void loadRows()
}
function nextPage() {
  offset.value += pageSize
  void loadRows()
}

function closeWindow() {
  if (window.opener) {
    window.close()
  } else {
    void router.push({ path: '/account', query: { panel: 'database' } })
  }
}

function onKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    if (tab.value === 'sql') void runSql()
  }
}

onMounted(() => {
  document.documentElement.classList.toggle('dark', colorMode.value === 'dark')
  window.addEventListener('keydown', onKey)
  void boot()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div class="studio" :class="{ 'is-dark': colorMode === 'dark' }">
    <header class="top">
      <div class="identity">
        <button type="button" class="icon" title="Close" @click="closeWindow">←</button>
        <div class="min-w-0">
          <p class="title">SQL studio</p>
          <p class="sub">
            <Badge variant="neutral">{{ engineLabel }}</Badge>
            <span class="mono">{{ title }}</span>
            <span v-if="meta.domain" class="muted">· {{ meta.domain }}</span>
          </p>
        </div>
      </div>
      <div class="actions">
        <!-- Database Selector if multiple -->
        <select
          v-if="databases.length > 1"
          v-model="selectedDbId"
          class="db-select"
          @change="onDbChange"
        >
          <option v-for="d in databases" :key="d.id" :value="d.id">
            {{ d.name || d.logical_name }} ({{ d.engine }})
          </option>
        </select>

        <button
          v-if="isMysql"
          type="button"
          class="tool pma-btn"
          :disabled="pmaBusy"
          title="Open phpMyAdmin in a new tab"
          @click="openPhpMyAdmin"
        >
          {{ pmaBusy ? 'Opening…' : '↗ phpMyAdmin' }}
        </button>

        <button
          type="button"
          class="tool"
          title="Architecture & stack connection guide"
          @click="showGuide = true"
        >
          (i) Guide
        </button>

        <button type="button" class="tool" @click="colorMode = colorMode === 'dark' ? 'light' : 'dark'">
          {{ colorMode === 'dark' ? 'Light' : 'Dark' }}
        </button>
        <button type="button" class="tool" :disabled="busy" @click="loadSchema">Refresh</button>
      </div>
    </header>

    <p v-if="message" class="banner" :class="message.ok ? 'ok' : 'err'">{{ message.text }}</p>

    <div v-if="loading" class="pad muted">Opening database…</div>
    
    <div v-else-if="hasNoDatabase" class="pad no-db-wrap">
      <div class="no-db-card">
        <div class="no-db-icon">🗄️</div>
        <h3>No database on this site yet</h3>
        <p class="muted">Create your MySQL database with 1-click or from Site → Databases to start querying and importing tables.</p>
        <div class="no-db-actions">
          <button type="button" class="primary" :disabled="createDbBusy" @click="createQuickDatabase">
            {{ createDbBusy ? 'Creating…' : '+ Create MySQL Database' }}
          </button>
          <button type="button" class="tool" @click="closeWindow">Back to Account</button>
        </div>
      </div>
    </div>

    <div v-else-if="error" class="pad err">{{ error }}</div>

    <div v-else class="body">
      <aside class="side">
        <p class="side-label">Tables</p>
        <ul v-if="tables.length" class="tables">
          <li
            v-for="t in tables"
            :key="t.name"
            :class="{ on: selectedTable === t.name }"
            @click="selectTable(t)"
          >
            <span class="tag">TBL</span>
            <span class="name">{{ t.name }}</span>
            <span v-if="t.approx_rows != null" class="rows">{{ t.approx_rows }}</span>
          </li>
        </ul>
        <p v-else class="muted tiny">No tables yet.</p>
      </aside>

      <main class="main">
        <nav class="tabs">
          <button type="button" :class="{ on: tab === 'structure' }" @click="tab = 'structure'">Structure</button>
          <button type="button" :class="{ on: tab === 'browse' }" @click="tab = 'browse'">Browse</button>
          <button type="button" :class="{ on: tab === 'sql' }" @click="tab = 'sql'">SQL</button>
          <button type="button" :class="{ on: tab === 'import' }" @click="tab = 'import'">Import (.sql)</button>
        </nav>

        <section v-if="tab === 'structure'" class="panel">
          <template v-if="activeTable">
            <h2>{{ activeTable.name }}</h2>
            <p class="muted tiny">Columns · indexes shown as primary key where available</p>
            <div class="scroll">
              <table class="grid">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Column</th>
                    <th>Type</th>
                    <th>Null</th>
                    <th>Key</th>
                    <th>Default</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(col, i) in activeTable.columns || []" :key="col.name">
                    <td>{{ i + 1 }}</td>
                    <td class="mono">{{ col.name }}</td>
                    <td>{{ col.data_type || '—' }}</td>
                    <td>{{ col.nullable ? 'YES' : 'NO' }}</td>
                    <td>{{ col.primary_key ? 'PRI' : '' }}</td>
                    <td class="mono">{{ col.default ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <p v-else class="muted">Select a table.</p>
        </section>

        <section v-else-if="tab === 'browse'" class="panel">
          <div class="bar">
            <h2>{{ selectedTable || 'Browse' }}</h2>
            <div class="bar-actions">
              <button type="button" class="tool" :disabled="!offset || busy" @click="prevPage">Previous</button>
              <button type="button" class="tool" :disabled="busy" @click="nextPage">Next</button>
              <button
                v-if="canWrite"
                type="button"
                class="tool primary"
                :disabled="!selectedTable || busy"
                @click="startInsert"
              >
                + Insert row
              </button>
            </div>
          </div>
          <p class="hint">Showing up to {{ pageSize }} rows (offset {{ offset }}).</p>
          <div v-if="rows?.columns?.length" class="scroll">
            <table class="grid">
              <thead>
                <tr>
                  <th class="row-num">#</th>
                  <th v-if="canWrite" class="acts" />
                  <th v-for="col in rows.columns" :key="col">{{ col }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in rows.rows || []" :key="idx">
                  <td class="row-num">{{ idx + 1 }}</td>
                  <td v-if="canWrite" class="acts">
                    <button type="button" class="link" @click="startEdit(row)">Edit</button>
                    <button type="button" class="link danger" @click="deleteRow(row)">Del</button>
                  </td>
                  <td v-for="col in rows.columns" :key="col">{{ cell(row[col]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else-if="selectedTable" class="muted">{{ busy ? 'Loading…' : 'No rows in this table.' }}</p>
          <p v-else class="muted">Select a table to browse.</p>
        </section>

        <section v-else-if="tab === 'import'" class="panel sql-panel">
          <h2>Import SQL Dump</h2>
          <p class="muted tiny">
            Select a .sql file from your computer or paste SQL queries below to import into {{ schema?.database || 'this database' }}.
          </p>

          <div class="import-picker mt">
            <input type="file" accept=".sql,.txt" @change="onFilePicked" />
            <span v-if="importFile" class="tiny mono">{{ importFile.name }} ({{ (importFile.size / 1024).toFixed(1) }} KB)</span>
          </div>

          <textarea
            v-model="importSqlText"
            class="sql mt"
            rows="10"
            spellcheck="false"
            placeholder="-- Or paste your SQL dump here...&#10;CREATE TABLE IF NOT EXISTS ..."
          />

          <div class="bar-actions mt">
            <button
              type="button"
              class="primary"
              :disabled="importBusy || !importSqlText.trim()"
              @click="runImport"
            >
              {{ importBusy ? 'Importing…' : 'Run Import' }}
            </button>
            <button
              v-if="importSqlText"
              type="button"
              class="tool"
              @click="importSqlText = ''; importFile = null"
            >
              Clear
            </button>
          </div>

          <p v-if="importMsg" class="mt tiny" :class="importMsg.ok ? 'ok-msg' : 'err-msg'">
            {{ importMsg.text }}
          </p>
        </section>

        <section v-else class="panel sql-panel">
          <h2>Run SQL</h2>
          <p class="muted tiny">Ctrl/Cmd + Enter to run · same role as the SQL tab in phpMyAdmin</p>
          <textarea v-model="sql" class="sql" rows="8" spellcheck="false" />
          <button type="button" class="primary" :disabled="busy || !sql.trim()" @click="runSql">
            {{ busy ? 'Running…' : 'Go' }}
          </button>
          <div v-if="queryResult?.columns?.length" class="scroll mt">
            <table class="grid">
              <thead>
                <tr>
                  <th class="row-num">#</th>
                  <th v-for="col in queryResult.columns" :key="col">{{ col }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in queryResult.rows || []" :key="idx">
                  <td class="row-num">{{ idx + 1 }}</td>
                  <td v-for="col in queryResult.columns" :key="col">{{ cell(row[col]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else-if="queryResult" class="muted mt">
            {{ queryResult.message || `Affected ${queryResult.affected_rows ?? 0} row(s)` }}
          </p>
        </section>
      </main>
    </div>

    <div v-if="editing" class="modal" @click.self="cancelEdit">
      <div class="sheet">
        <h3>{{ editMode === 'insert' ? 'Insert row' : 'Edit row' }}</h3>
        <div class="fields">
          <label v-for="col in activeTable?.columns || []" :key="col.name">
            <span class="mono">{{ col.name }}</span>
            <input v-model="editValues[col.name]" type="text" />
          </label>
        </div>
        <div class="modal-acts">
          <button type="button" class="tool" @click="cancelEdit">Cancel</button>
          <button type="button" class="primary" :disabled="busy" @click="saveEdit">
            {{ busy ? 'Saving…' : 'Save' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Stack Guide Modal (i) in Studio -->
    <div v-if="showGuide" class="modal" @click.self="showGuide = false">
      <div class="sheet guide-sheet">
        <div class="guide-sheet-head">
          <h3>Database & Stack Connection Guide</h3>
          <button type="button" class="tool" @click="showGuide = false">✕</button>
        </div>

        <div class="guide-nav-bar">
          <button type="button" class="guide-tab" :class="{ on: selectedGuideTab === 'mysql' }" @click="selectedGuideTab = 'mysql'">PHP + MySQL</button>
          <button type="button" class="guide-tab" :class="{ on: selectedGuideTab === 'postgres' }" @click="selectedGuideTab = 'postgres'">PHP + PostgreSQL</button>
          <button type="button" class="guide-tab" :class="{ on: selectedGuideTab === 'laravel' }" @click="selectedGuideTab = 'laravel'">Laravel</button>
          <button type="button" class="guide-tab" :class="{ on: selectedGuideTab === 'wordpress' }" @click="selectedGuideTab = 'wordpress'">WordPress</button>
        </div>

        <div class="guide-sheet-content">
          <div v-if="selectedGuideTab === 'mysql'" class="guide-body">
            <h4>PHP PDO with MySQL</h4>
            <pre class="code-block"><code>&lt;?php
$pdo = new PDO("mysql:host=localhost;port=3306;dbname={{ meta.name || 'app_db' }};charset=utf8mb4", "username", "password", [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
]);</code></pre>
            <p class="muted tiny">Import .sql dump files using the <strong>Import (.sql)</strong> tab or via phpMyAdmin.</p>
          </div>

          <div v-else-if="selectedGuideTab === 'postgres'" class="guide-body">
            <h4>PHP PDO with PostgreSQL (pdo_pgsql)</h4>
            <pre class="code-block"><code>&lt;?php
$pdo = new PDO("pgsql:host=localhost;port=5432;dbname={{ meta.name || 'app_db' }}", "username", "password", [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
]);</code></pre>
            <p class="muted tiny">Native pdo_pgsql is pre-installed on IFNOTUS PHP 8.3 & 8.2 runtimes.</p>
          </div>

          <div v-else-if="selectedGuideTab === 'laravel'" class="guide-body">
            <h4>Laravel .env Configuration</h4>
            <pre class="code-block"><code>DB_CONNECTION={{ (meta.engine || '').includes('postgre') ? 'pgsql' : 'mysql' }}
DB_HOST=127.0.0.1
DB_PORT={{ (meta.engine || '').includes('postgre') ? '5432' : '3306' }}
DB_DATABASE={{ meta.name || 'app_db' }}
DB_USERNAME=your_db_user
DB_PASSWORD=your_password</code></pre>
          </div>

          <div v-else class="guide-body">
            <h4>WordPress wp-config.php</h4>
            <pre class="code-block"><code>define( 'DB_NAME', '{{ meta.name || 'app_db' }}' );
define( 'DB_USER', 'your_user' );
define( 'DB_PASSWORD', 'your_password' );
define( 'DB_HOST', 'localhost:3306' );</code></pre>
          </div>
        </div>

        <div class="modal-acts">
          <button type="button" class="primary" @click="showGuide = false">Close Guide</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.studio {
  display: flex;
  flex-direction: column;
  height: 100dvh;
  background: #f8fafc;
  color: #0f172a;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 0.85rem;
}
.studio.is-dark {
  background: #0b1220;
  color: #e2e8f0;
}
.top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 0.6rem 0.9rem;
  border-bottom: 1px solid #d7dee8;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
}
.is-dark .top {
  background: rgba(15, 23, 42, 0.85);
  border-color: #1e293b;
}
.identity { display: flex; align-items: center; gap: 0.6rem; min-width: 0; }
.title { font-weight: 700; font-size: 0.95rem; margin: 0; line-height: 1.2; }
.sub { margin: 0; font-size: 0.72rem; display: flex; align-items: center; gap: 0.35rem; }
.icon {
  background: transparent;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  padding: 0.25rem 0.5rem;
  cursor: pointer;
  color: inherit;
}
.is-dark .icon { border-color: #334155; }
.actions { display: flex; gap: 0.4rem; align-items: center; }
.tool {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  padding: 0.35rem 0.65rem;
  font-size: 0.78rem;
  cursor: pointer;
  color: inherit;
  transition: all 0.15s;
}
.tool:hover { background: #e2e8f0; }
.is-dark .tool { background: #1e293b; border-color: #334155; }
.is-dark .tool:hover { background: #334155; }
.pma-btn {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
  font-weight: 600;
}
.pma-btn:hover { background: #dbeafe; }
.is-dark .pma-btn {
  background: #1e3a8a;
  border-color: #2563eb;
  color: #93c5fd;
}
.is-dark .pma-btn:hover { background: #1e40af; }
.db-select {
  padding: 0.3rem 0.5rem;
  font-size: 0.78rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  background: #fff;
  color: inherit;
}
.is-dark .db-select {
  background: #1e293b;
  border-color: #334155;
}
.primary {
  background: #0f766e;
  border: 1px solid #0f766e;
  color: #fff;
  border-radius: 0.35rem;
  padding: 0.35rem 0.75rem;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}
.primary:hover { background: #115e59; }
.banner {
  padding: 0.45rem 0.9rem;
  margin: 0;
  font-size: 0.78rem;
}
.banner.ok { background: #ecfdf5; color: #047857; }
.banner.err, .err { background: #fef2f2; color: #b91c1c; }
.is-dark .banner.ok { background: #064e3b; color: #a7f3d0; }
.is-dark .banner.err, .is-dark .err { background: #7f1d1d; color: #fecaca; }
.pad { padding: 1.25rem; }

.no-db-wrap {
  display: flex;
  justify-content: center;
  align-items: center;
  flex: 1;
}
.no-db-card {
  max-width: 440px;
  text-align: center;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 2.2rem 1.8rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.is-dark .no-db-card {
  background: #1e293b;
  border-color: #334155;
}
.no-db-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
.no-db-card h3 { margin: 0 0 0.5rem; font-size: 1.15rem; }
.no-db-actions { display: flex; justify-content: center; gap: 0.75rem; margin-top: 1.25rem; }

.body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(180px, 240px) 1fr;
}
.side {
  border-right: 1px solid #d7dee8;
  overflow: auto;
  padding: 0.65rem;
  background: rgba(255, 255, 255, 0.55);
}
.is-dark .side {
  border-color: #1e293b;
  background: rgba(15, 23, 42, 0.55);
}
.side-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  margin: 0 0 0.4rem;
}
.tables { list-style: none; margin: 0; padding: 0; }
.tables li {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.35rem;
  align-items: center;
  padding: 0.4rem 0.45rem;
  border-radius: 0.35rem;
  cursor: pointer;
  font-size: 0.78rem;
}
.tables li:hover, .tables li.on { background: #ecfdf5; }
.is-dark .tables li:hover, .is-dark .tables li.on { background: #134e4a; }
.tag {
  font-size: 0.58rem;
  font-weight: 700;
  color: #0f766e;
  background: #ccfbf1;
  padding: 0.1rem 0.25rem;
  border-radius: 0.2rem;
}
.is-dark .tag { background: #115e59; color: #99f6e4; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rows { color: #94a3b8; font-size: 0.68rem; }
.main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.tabs {
  display: flex;
  gap: 0.25rem;
  padding: 0.5rem 0.75rem 0;
  border-bottom: 1px solid #d7dee8;
  flex-shrink: 0;
}
.is-dark .tabs { border-color: #1e293b; }
.tabs button {
  border: 0;
  background: transparent;
  padding: 0.45rem 0.7rem;
  font-size: 0.8rem;
  color: #64748b;
  border-bottom: 2px solid transparent;
  cursor: pointer;
}
.tabs button.on {
  color: #0f766e;
  border-bottom-color: #0f766e;
  font-weight: 600;
}
.panel {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0.75rem;
}
.panel h2 { margin: 0; font-size: 0.95rem; }
.bar {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 0.5rem;
}
.bar-actions { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.hint { font-size: 0.75rem; color: #64748b; margin: 0 0 0.5rem; }
.scroll { overflow: auto; max-height: calc(100dvh - 12rem); border: 1px solid #d7dee8; border-radius: 0.4rem; }
.is-dark .scroll { border-color: #334155; }
.grid {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
  font-size: 0.75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.grid th, .grid td {
  border-bottom: 1px solid #e2e8f0;
  padding: 0.35rem 0.5rem;
  text-align: left;
  white-space: pre;
  vertical-align: top;
}
.is-dark .grid th, .is-dark .grid td { border-color: #1e293b; }
.grid th { background: #f8fafc; position: sticky; top: 0; z-index: 1; white-space: nowrap; }
.is-dark .grid th { background: #111827; }
.grid th.row-num,
.grid td.row-num {
  position: sticky;
  left: 0;
  z-index: 2;
  width: 2.75rem;
  min-width: 2.75rem;
  text-align: center;
  color: #94a3b8;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
}
.is-dark .grid th.row-num,
.is-dark .grid td.row-num {
  background: #111827;
  border-color: #1e293b;
}
.grid th.acts, .grid td.acts {
  position: sticky;
  left: 2.75rem;
  z-index: 2;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
}
.is-dark .grid th.acts, .is-dark .grid td.acts {
  background: #111827;
  border-color: #1e293b;
}
.link {
  background: transparent;
  border: 0;
  color: #0f766e;
  padding: 0 0.25rem;
  cursor: pointer;
  font-size: 0.75rem;
}
.link.danger { color: #b91c1c; }
.sql-panel textarea.sql {
  width: 100%;
  box-sizing: border-box;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8rem;
  padding: 0.5rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  background: #fff;
  color: inherit;
  resize: vertical;
  margin: 0.4rem 0 0.6rem;
}
.is-dark .sql-panel textarea.sql {
  background: #0f172a;
  border-color: #334155;
}
.import-picker {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem;
  background: rgba(0, 0, 0, 0.02);
  border: 1px dashed #cbd5e1;
  border-radius: 0.35rem;
}
.is-dark .import-picker {
  background: rgba(255, 255, 255, 0.02);
  border-color: #334155;
}
.ok-msg { color: #047857; font-weight: 600; }
.err-msg { color: #b91c1c; font-weight: 600; }
.mt { margin-top: 0.6rem; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.muted { color: #64748b; }
.tiny { font-size: 0.75rem; }
.modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
  padding: 1rem;
}
.sheet {
  background: #fff;
  border-radius: 0.5rem;
  width: 100%;
  max-width: 520px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
}
.is-dark .sheet { background: #1e293b; color: #e2e8f0; }
.sheet h3 { margin: 0.75rem 1rem 0.5rem; font-size: 0.95rem; }
.fields {
  overflow: auto;
  padding: 0.5rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.fields label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.78rem; }
.fields input {
  padding: 0.4rem 0.55rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.3rem;
  background: #fff;
  color: inherit;
  font-size: 0.8rem;
}
.is-dark .fields input { background: #0f172a; border-color: #334155; }
.modal-acts {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  padding: 0.6rem 1rem;
  border-top: 1px solid #e2e8f0;
}
.is-dark .modal-acts { border-color: #334155; }

.guide-sheet {
  max-width: 620px;
}
.guide-sheet-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}
.is-dark .guide-sheet-head { border-color: #334155; }
.guide-sheet-head h3 { margin: 0; font-size: 0.95rem; }
.guide-nav-bar {
  display: flex;
  gap: 0.35rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f1f5f9;
}
.is-dark .guide-nav-bar { background: #0f172a; border-color: #334155; }
.guide-tab {
  padding: 0.3rem 0.6rem;
  border-radius: 0.3rem;
  border: 1px solid transparent;
  background: transparent;
  font-size: 0.78rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
}
.guide-tab.on {
  background: #0284c7;
  color: #fff;
}
.guide-sheet-content {
  padding: 1rem;
  overflow-y: auto;
}
.code-block {
  background: #0f172a;
  color: #f8fafc;
  padding: 0.75rem;
  border-radius: 0.4rem;
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  margin: 0.5rem 0;
  overflow-x: auto;
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Badge from '@/components/ui/Badge.vue'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { DbQueryResult, DbSchema, DbTable } from '@/types/databases'

type Tab = 'structure' | 'browse' | 'sql'
type ColorMode = 'light' | 'dark'

const route = useRoute()
const router = useRouter()

const envId = computed(() => String(route.query.env || ''))
const THEME_KEY = 'ifnotus.portal.studio.theme'
const colorMode = ref<ColorMode>((localStorage.getItem(THEME_KEY) as ColorMode) || 'light')

const loading = ref(true)
const busy = ref(false)
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
  try {
    const [{ data: db }, dash] = await Promise.all([
      customersApi.getEnvDatabase(envId.value, false),
      customersApi.dashboard().catch(() => null),
    ])
    const eng = String(db.engine || '').toLowerCase()
    if (eng === 'mysql' || eng === 'mariadb') {
      try {
        const { data } = await customersApi.openEnvPhpMyAdmin(envId.value)
        window.location.replace(data.url)
        return
      } catch (e: unknown) {
        // Keep SQL studio as fallback if phpMyAdmin sign-on fails.
        error.value = getApiErrorMessage(e, 'Could not open phpMyAdmin — using SQL studio.')
      }
    }
    if (!db.name && !db.engine) {
      error.value = 'No database on this site yet. Install WordPress or Laravel from Site → Stack when you need one.'
      loading.value = false
      return
    }
    meta.value = {
      engine: db.engine,
      name: db.name,
      domain: dash?.data?.environments?.find((e) => e.id === envId.value)?.domain || null,
    }
    const env = dash?.data?.environments?.find((e) => e.id === envId.value)
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
  const { data } = await customersApi.getEnvDatabaseSchema(envId.value)
  schema.value = data
  document.title = `${data.database || 'Database'} · SQL studio`
  if (!selectedTable.value && data.tables?.length) {
    await selectTable(data.tables[0])
  } else if (selectedTable.value) {
    await loadRows()
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
    message.value = { ok: false, text: getApiErrorMessage(e, 'Query failed.') }
  } finally {
    busy.value = false
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
  try {
    window.close()
  } catch {
    /* ignore */
  }
  window.setTimeout(() => {
    if (!window.closed) {
      router.push({ name: 'hosting-panel', params: { environmentId: envId.value }, query: { tab: 'databases' } })
    }
  }, 120)
}

function onKeydown(ev: KeyboardEvent) {
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'enter' && tab.value === 'sql') {
    ev.preventDefault()
    void runSql()
  }
}

onMounted(() => {
  document.documentElement.classList.toggle('dark', colorMode.value === 'dark')
  document.documentElement.style.colorScheme = colorMode.value
  window.addEventListener('keydown', onKeydown, true)
  void boot()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div class="studio" :class="colorMode === 'dark' ? 'is-dark' : 'is-light'">
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
        <button type="button" class="tool" @click="colorMode = colorMode === 'dark' ? 'light' : 'dark'">
          {{ colorMode === 'dark' ? 'Light' : 'Dark' }}
        </button>
        <button type="button" class="tool" :disabled="busy" @click="loadSchema">Refresh</button>
      </div>
    </header>

    <p v-if="message" class="banner" :class="message.ok ? 'ok' : 'err'">{{ message.text }}</p>

    <div v-if="loading" class="pad muted">Opening database…</div>
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
                class="primary"
                :disabled="!selectedTable || busy"
                @click="startInsert"
              >
                Insert row
              </button>
            </div>
          </div>
          <p v-if="!canWrite" class="hint">This package can view data. Writes need a higher pack.</p>
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
          <label v-for="(_val, key) in editValues" :key="key" class="field">
            <span>{{ key }}</span>
            <textarea v-model="editValues[key]" rows="2" />
          </label>
        </div>
        <div class="sheet-actions">
          <button type="button" class="tool" @click="cancelEdit">Cancel</button>
          <button type="button" class="primary" :disabled="busy" @click="saveEdit">Save</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.studio {
  min-height: 100vh;
  max-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: #f4f7fb;
  color: #0f172a;
  overflow: hidden;
}
.studio.is-dark {
  background: #0b1220;
  color: #e2e8f0;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid #d7dee8;
  background: rgba(255, 255, 255, 0.96);
  flex-shrink: 0;
}
.is-dark .top {
  background: rgba(11, 18, 32, 0.96);
  border-color: #1e293b;
}
.identity {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
}
.title {
  font-weight: 700;
  font-size: 0.95rem;
}
.sub {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  font-size: 0.75rem;
  color: #64748b;
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.muted { color: #64748b; }
.tiny { font-size: 0.72rem; }
.actions { display: flex; gap: 0.4rem; }
.icon, .tool, .primary, .link {
  border-radius: 0.4rem;
  border: 1px solid #d7dee8;
  background: #fff;
  color: #334155;
  padding: 0.35rem 0.55rem;
  font-size: 0.78rem;
  cursor: pointer;
}
.is-dark .icon, .is-dark .tool, .is-dark .primary {
  background: #111827;
  border-color: #334155;
  color: #e2e8f0;
}
.primary {
  background: #0f766e;
  border-color: #0f766e;
  color: #fff;
}
.link {
  border: 0;
  background: transparent;
  padding: 0 0.25rem;
  color: #0f766e;
}
.link.danger { color: #b91c1c; }
.banner {
  margin: 0;
  padding: 0.45rem 0.85rem;
  font-size: 0.8rem;
  flex-shrink: 0;
}
.banner.ok { background: #ecfdf5; color: #065f46; }
.banner.err, .err { background: #fef2f2; color: #991b1b; }
.is-dark .banner.ok { background: #064e3b; color: #a7f3d0; }
.is-dark .banner.err, .is-dark .err { background: #7f1d1d; color: #fecaca; }
.pad { padding: 1.25rem; }
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
  text-align: right;
  color: #64748b;
  background: #fff;
  border-right: 1px solid #e2e8f0;
  user-select: none;
}
.grid th.row-num {
  z-index: 3;
  background: #f8fafc;
}
.is-dark .grid th.row-num,
.is-dark .grid td.row-num {
  background: #111827;
  border-right-color: #1e293b;
}
.acts { width: 4.5rem; white-space: nowrap; }
.sql-panel .sql {
  width: 100%;
  margin: 0.5rem 0;
  border-radius: 0.4rem;
  border: 1px solid #d7dee8;
  padding: 0.65rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
  background: #fff;
  color: inherit;
  resize: vertical;
}
.is-dark .sql {
  background: #0f172a;
  border-color: #334155;
}
.mt { margin-top: 0.65rem; }
.modal {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: grid;
  place-items: center;
  padding: 1rem;
  z-index: 40;
}
.sheet {
  width: min(560px, 100%);
  max-height: 85dvh;
  overflow: auto;
  background: #fff;
  border-radius: 0.6rem;
  padding: 1rem;
}
.is-dark .sheet { background: #111827; }
.sheet h3 { margin: 0 0 0.75rem; }
.fields { display: grid; gap: 0.55rem; }
.field { display: grid; gap: 0.25rem; font-size: 0.75rem; }
.field textarea {
  border: 1px solid #d7dee8;
  border-radius: 0.35rem;
  padding: 0.4rem;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 0.78rem;
  background: #fff;
  color: inherit;
}
.is-dark .field textarea {
  background: #0f172a;
  border-color: #334155;
}
.sheet-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-top: 0.85rem;
}
@media (max-width: 800px) {
  .body { grid-template-columns: 1fr; }
  .side { max-height: 30vh; border-right: 0; border-bottom: 1px solid #d7dee8; }
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import '@/assets/portal.css'

type Entry = {
  name: string
  path: string
  is_dir: boolean
  size_bytes?: number | null
}

const route = useRoute()
const router = useRouter()

const envId = computed(() => String(route.query.env || ''))
const loading = ref(true)
const entries = ref<Entry[]>([])
const currentPath = ref(String(route.query.path || '.') || '.')
const parentPath = ref<string | null>(null)
const msg = ref('')
const err = ref('')
const usageLabel = ref('')
const newFolder = ref('')
const newFileName = ref('')
const showMkdir = ref(false)
const showNewFile = ref(false)
const domain = ref('')
const canWrite = true

const breadcrumbs = computed(() => {
  const parts = currentPath.value === '.' ? [] : currentPath.value.split('/').filter(Boolean)
  const crumbs: Array<{ label: string; path: string }> = [{ label: 'Site root', path: '.' }]
  let acc = ''
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part
    crumbs.push({ label: part, path: acc })
  }
  return crumbs
})

const sorted = computed(() => {
  const list = [...entries.value]
  list.sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  return list
})

function formatSize(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

async function loadUsage() {
  if (!envId.value) return
  try {
    const { data } = await customersApi.getEnvUsage(envId.value)
    usageLabel.value = `${Number(data.storage_used_gb || 0).toFixed(2)} / ${Number(data.storage_limit_gb || 0).toFixed(2)} GB · ${data.file_count || 0} files`
  } catch {
    usageLabel.value = ''
  }
}

async function load() {
  if (!envId.value) {
    err.value = 'Missing environment. Open Files from your account.'
    loading.value = false
    return
  }
  loading.value = true
  err.value = ''
  try {
    const { data } = await customersApi.listEnvFiles(envId.value, currentPath.value)
    entries.value = (data.entries || []) as Entry[]
    parentPath.value = data.parent
    currentPath.value = data.path || currentPath.value
    document.title = `Files · ${currentPath.value} · IFNOTUS`
    void router.replace({
      name: 'portal-files',
      query: { env: envId.value, path: currentPath.value },
    })
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not load files.')
  } finally {
    loading.value = false
  }
}

async function hydrateEnv() {
  try {
    const { data } = await customersApi.environments()
    const hit = data.find((e) => e.id === envId.value)
    domain.value = hit?.domain || ''
  } catch {
    domain.value = ''
  }
}

function openDir(path: string) {
  currentPath.value = path || '.'
  void load()
}

function openEntry(entry: Entry) {
  if (entry.is_dir) {
    openDir(entry.path)
    return
  }
  const href = `/account/files/edit?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(entry.path)}`
  window.open(href, `ifnotus-editor-${entry.path}`)
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
    await load()
    await loadUsage()
    const href = `/account/files/edit?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(path)}`
    window.open(href, `ifnotus-editor-${path}`)
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Could not create file.')
  }
}

async function removeEntry(entry: Entry) {
  const label = entry.is_dir ? 'folder' : 'file'
  if (!confirm(`Delete this ${label}? ${entry.name}`)) return
  try {
    await customersApi.deleteEnvFile(envId.value, entry.path)
    msg.value = `Deleted ${entry.name}`
    await load()
    await loadUsage()
  } catch (e) {
    err.value = getApiErrorMessage(e, 'Delete failed.')
  }
}

function pickUpload() {
  if (!envId.value) return
  const href = `/account/files/upload?env=${encodeURIComponent(envId.value)}&path=${encodeURIComponent(currentPath.value || '.')}`
  window.open(href, `ifnotus-upload-${envId.value}`)
}

watch(
  () => route.query.env,
  () => {
    void hydrateEnv()
    void load()
    void loadUsage()
  },
)

onMounted(async () => {
  await hydrateEnv()
  await load()
  await loadUsage()
})
</script>

<template>
  <div class="fm-shell">
    <header class="fm-top">
      <div class="brand">
        <a href="/account" class="mark">IF</a>
        <div>
          <strong>File manager</strong>
          <p>{{ domain || 'Your site' }}</p>
        </div>
      </div>
      <div class="actions">
        <span v-if="usageLabel" class="usage">{{ usageLabel }}</span>
        <button type="button" class="ghost" @click="load">Refresh</button>
        <button type="button" class="ghost" @click="showMkdir = !showMkdir; showNewFile = false">
          New folder
        </button>
        <button type="button" class="ghost" @click="showNewFile = !showNewFile; showMkdir = false">
          New file
        </button>
        <span class="hint-ai">Dev Companion lives in the file editor. Open a file to chat.</span>
        <button type="button" class="primary" :disabled="!canWrite || !envId" @click="pickUpload">
          Upload
        </button>
      </div>
    </header>

    <nav class="crumbs" aria-label="Path">
      <button
        v-for="(c, i) in breadcrumbs"
        :key="c.path"
        type="button"
        @click="openDir(c.path)"
      >
        <span v-if="i">/</span>{{ c.label }}
      </button>
    </nav>

    <div v-if="showMkdir" class="mkdir">
      <input v-model="newFolder" placeholder="Folder name" @keyup.enter="createFolder" />
      <button type="button" class="primary" @click="createFolder">Create</button>
    </div>
    <div v-if="showNewFile" class="mkdir">
      <input
        v-model="newFileName"
        placeholder="File name (e.g. page.html)"
        @keyup.enter="createFile"
      />
      <button type="button" class="primary" @click="createFile">Create & edit</button>
    </div>

    <p v-if="msg" class="ok">{{ msg }}</p>
    <p v-if="err" class="bad">{{ err }}</p>
    <p v-if="loading" class="muted">Loading…</p>

    <table v-else class="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Size</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="parentPath != null">
          <td colspan="3">
            <button type="button" class="row-btn" @click="openDir(parentPath || '.')">↑ Parent folder</button>
          </td>
        </tr>
        <tr v-for="entry in sorted" :key="entry.path">
          <td>
            <button type="button" class="row-btn" @click="openEntry(entry)">
              <span class="tag">{{ entry.is_dir ? 'DIR' : 'FILE' }}</span>
              {{ entry.name }}
            </button>
          </td>
          <td class="mono">{{ entry.is_dir ? '—' : formatSize(entry.size_bytes) }}</td>
          <td class="right">
            <button
              v-if="!entry.is_dir"
              type="button"
              class="ghost"
              @click="openEntry(entry)"
            >
              Edit
            </button>
            <button type="button" class="ghost danger" @click="removeEntry(entry)">Delete</button>
          </td>
        </tr>
        <tr v-if="!sorted.length">
          <td colspan="3" class="muted">This folder is empty. Upload files or create a folder.</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.fm-shell {
  min-height: 100vh;
  background: #eef2f6;
  color: #0f172a;
  font-family: Figtree, Segoe UI, sans-serif;
  padding: 1rem 1.25rem 2.5rem;
}
.fm-top {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.85rem;
}
.brand {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}
.mark {
  display: inline-flex;
  width: 2.2rem;
  height: 2.2rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.5rem;
  background: #1e3a5f;
  color: #fff;
  font-weight: 800;
  font-size: 0.7rem;
  text-decoration: none;
}
.brand strong { display: block; font-size: 0.95rem; }
.brand p { margin: 0; font-size: 0.75rem; color: #64748b; }
.actions { display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: center; }
.hint-ai {
  font-size: 0.72rem;
  color: #64748b;
  max-width: 18rem;
  line-height: 1.3;
}
.usage {
  font-size: 0.75rem;
  color: #475569;
  background: #fff;
  border: 1px solid #d7dee8;
  border-radius: 999px;
  padding: 0.3rem 0.7rem;
}
.primary, .ghost {
  border-radius: 0.45rem;
  font-size: 0.82rem;
  font-weight: 650;
  padding: 0.45rem 0.75rem;
  cursor: pointer;
}
.primary {
  border: none;
  background: #1e3a5f;
  color: #fff;
}
.ghost {
  border: 1px solid #d7dee8;
  background: #fff;
  color: #334155;
}
.ghost.danger { color: #b91c1c; }
.hidden { display: none; }
.crumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.15rem;
  margin-bottom: 0.75rem;
}
.crumbs button {
  border: none;
  background: none;
  color: #1e3a5f;
  font-weight: 650;
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0.15rem 0.25rem;
}
.crumbs span { color: #94a3b8; margin-right: 0.15rem; }
.mkdir {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.mkdir input {
  flex: 1;
  border: 1px solid #d7dee8;
  border-radius: 0.45rem;
  padding: 0.5rem 0.7rem;
}
.table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid #d7dee8;
  border-radius: 0.75rem;
  overflow: hidden;
}
.table th, .table td {
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid #eef2f6;
  text-align: left;
  font-size: 0.88rem;
}
.table th { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: #64748b; }
.row-btn {
  border: none;
  background: none;
  cursor: pointer;
  font: inherit;
  color: inherit;
  display: inline-flex;
  gap: 0.5rem;
  align-items: center;
  padding: 0;
}
.tag {
  font-size: 0.65rem;
  font-weight: 700;
  color: #1e3a5f;
  background: #e8eef5;
  border-radius: 0.3rem;
  padding: 0.1rem 0.35rem;
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; color: #64748b; }
.right { text-align: right; white-space: nowrap; }
.ok { color: #047857; font-size: 0.85rem; }
.bad { color: #b91c1c; font-size: 0.85rem; }
.muted { color: #64748b; font-size: 0.85rem; }
</style>

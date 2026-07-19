<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import { filesApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { useFileTransferStore } from '@/stores/fileTransfers'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { FileDetail, FileRoot } from '@/types/hosting'
import type { FileEntry } from '@/types/operations'

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

const editorOpen = ref(false)
const editorPath = ref('')
const editorContent = ref('')
const editorMeta = ref<FileDetail | null>(null)

const newFolderName = ref('')
const chmodMode = ref('644')

const infoPanel = ref<FileDetail | null>(null)
const renameTarget = ref<FileEntry | null>(null)
const renameValue = ref('')
const moveTarget = ref<FileEntry | null>(null)
const moveDestination = ref('')

const scope = computed(() => {
  if (!selectedRoot.value) return {}
  // Hosting roots and discovered VPS paths use root_id; only registered app IDs use app_id.
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

function downloadEntry(entry: FileEntry) {
  if (entry.is_dir) return
  transfers.enqueueDownload(entry.path, entry.name, entry.size_bytes ?? 0, scope.value)
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
  try {
    const { data } = await filesApi.list(path, scope.value)
    entries.value = data.entries
    currentPath.value = data.path
    parentPath.value = data.parent
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Failed to list files') }
  } finally {
    loading.value = false
  }
}

async function switchRoot() {
  currentPath.value = '.'
  infoPanel.value = null
  await load('.')
}

function openDir(entry: FileEntry) {
  if (entry.is_dir) load(entry.path)
}

function goUp() {
  if (parentPath.value !== undefined) load(parentPath.value)
}

async function showInfo(entry: FileEntry) {
  actionKey.value = `info-${entry.path}`
  try {
    const { data } = await filesApi.stat(entry.path, scope.value)
    infoPanel.value = data
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Failed to load file info' }
  } finally {
    actionKey.value = null
  }
}

async function openFile(entry: FileEntry) {
  if (entry.is_dir) return
  actionKey.value = 'read'
  try {
    const { data } = await filesApi.read(entry.path, scope.value)
    editorPath.value = entry.path
    editorContent.value = data.content ?? ''
    editorMeta.value = data
    editorOpen.value = true
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Cannot open file' }
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
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Save failed' }
  } finally {
    actionKey.value = null
  }
}

async function mkdir() {
  if (!newFolderName.value) return
  const path = currentPath.value === '.' ? newFolderName.value : `${currentPath.value}/${newFolderName.value}`
  const { data } = await filesApi.mkdir(path, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  newFolderName.value = ''
  await load(currentPath.value)
}

async function remove(entry: FileEntry) {
  if (!confirm(`Delete ${entry.name}?`)) return
  const { data } = await filesApi.delete(entry.path, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  if (infoPanel.value?.path === entry.path) infoPanel.value = null
  await load(currentPath.value)
}

async function chmodEntry(entry: FileEntry) {
  const { data } = await filesApi.chmod(entry.path, chmodMode.value, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  await load(currentPath.value)
}

async function unzip(entry: FileEntry) {
  const { data } = await filesApi.unzip(entry.path, scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  await load(currentPath.value)
}

function startRename(entry: FileEntry) {
  renameTarget.value = entry
  renameValue.value = entry.name
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
}

async function confirmMove() {
  if (!moveTarget.value || !moveDestination.value.trim()) return
  const { data } = await filesApi.move(moveTarget.value.path, moveDestination.value.trim(), scope.value)
  message.value = { type: data.success ? 'ok' : 'err', text: data.message }
  moveTarget.value = null
  await load(currentPath.value)
}

function formatBytes(n?: number) {
  if (n == null) return '—'
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

onMounted(async () => {
  await loadRoots()
  const queryPath = String(route.query.path ?? '.')
  await load(queryPath || '.')
})
</script>

<template>
  <DashboardLayout @refresh="() => { loadRoots(); load() }">
    <div class="animate-fade-in space-y-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">File Manager</h1>
          <p class="text-sm text-surface-muted">Browse approved server paths</p>
        </div>
        <div v-if="canWrite" class="flex gap-2">
          <button type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" :disabled="parentPath === undefined" @click="goUp">Up</button>
          <RouterLink
            :to="uploadLink"
            class="rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Upload
          </RouterLink>
        </div>
        <button v-else type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" :disabled="parentPath === undefined" @click="goUp">Up</button>
      </div>

      <label v-if="roots.length" class="block max-w-lg text-sm">
        <span class="text-surface-muted">Browse root</span>
        <select
          v-model="selectedRoot"
          class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2"
          @change="switchRoot"
        >
          <option v-for="root in roots" :key="root.id" :value="root.id">{{ root.label }} — {{ root.path }}</option>
        </select>
      </label>

      <p class="font-mono text-xs text-surface-muted">
        {{ activeRoot?.path }}/{{ currentPath === '.' ? '' : currentPath }}
      </p>

      <p
        v-if="message"
        class="rounded-lg px-3 py-2 text-sm"
        :class="message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-700' : 'bg-red-500/10 text-red-700'"
      >
        {{ message.text }}
      </p>

      <Card v-if="canWrite" padding="sm">
        <div class="flex flex-wrap items-center gap-2">
          <input v-model="newFolderName" placeholder="New folder" class="rounded-lg border border-surface-border bg-transparent px-3 py-1.5 text-sm" />
          <button type="button" class="rounded-lg border border-surface-border px-3 py-1.5 text-sm" @click="mkdir">Create folder</button>
          <span class="text-xs text-surface-muted">chmod mode</span>
          <input v-model="chmodMode" class="w-16 rounded-lg border border-surface-border bg-transparent px-2 py-1.5 text-sm" maxlength="4" />
        </div>
      </Card>

      <div v-if="loading" class="text-sm text-surface-muted">Loading…</div>

      <div v-else class="max-h-[min(70vh,36rem)] overflow-auto rounded-xl border border-surface-border">
        <table class="w-full text-left text-sm">
          <thead class="sticky top-0 z-10 border-b border-surface-border bg-surface-raised text-xs text-surface-muted">
            <tr>
              <th class="px-4 py-2 font-medium">Name</th>
              <th class="px-4 py-2 font-medium">Size</th>
              <th class="px-4 py-2 font-medium">Perms</th>
              <th class="px-4 py-2 font-medium">Owner</th>
              <th class="px-4 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="entry in entries"
              :key="entry.path"
              class="border-b border-surface-border/60 hover:bg-slate-50/50 dark:hover:bg-slate-800/30"
            >
              <td class="px-4 py-2">
                <button
                  type="button"
                  class="text-left font-medium"
                  :class="entry.is_dir ? 'text-brand-600' : ''"
                  @click="entry.is_dir ? openDir(entry) : openFile(entry)"
                >
                  {{ entry.is_dir ? '📁' : '📄' }} {{ entry.name }}
                </button>
              </td>
              <td class="px-4 py-2 text-surface-muted">{{ entry.is_dir ? '—' : formatBytes(entry.size_bytes) }}</td>
              <td class="px-4 py-2 font-mono text-xs text-surface-muted">{{ entry.mode ?? '—' }}</td>
              <td class="px-4 py-2 text-xs text-surface-muted">{{ entry.owner ?? '—' }}</td>
              <td class="px-4 py-2">
                <div class="flex flex-wrap gap-2 text-xs">
                  <button type="button" class="underline" @click="showInfo(entry)">info</button>
                  <button v-if="!entry.is_dir" type="button" class="underline" @click="downloadEntry(entry)">download</button>
                  <template v-if="canWrite">
                    <button type="button" class="underline" @click="startRename(entry)">rename</button>
                    <button type="button" class="underline" @click="startMove(entry)">move</button>
                    <button type="button" class="underline" @click="chmodEntry(entry)">chmod</button>
                    <button v-if="entry.name.endsWith('.zip')" type="button" class="underline" @click="unzip(entry)">unzip</button>
                    <button type="button" class="text-red-600" @click="remove(entry)">delete</button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!entries.length" class="p-4 text-sm text-surface-muted">Empty directory.</p>
      </div>

      <Card v-if="infoPanel" padding="sm">
        <h2 class="text-sm font-semibold">File details</h2>
        <dl class="mt-2 grid gap-1 text-xs text-surface-muted md:grid-cols-2">
          <div><dt class="inline font-medium text-slate-700 dark:text-slate-200">Path:</dt> {{ infoPanel.path }}</div>
          <div><dt class="inline font-medium">Mode:</dt> {{ infoPanel.mode ?? '—' }}</div>
          <div><dt class="inline font-medium">Owner:</dt> {{ infoPanel.owner ?? '—' }}</div>
          <div><dt class="inline font-medium">Group:</dt> {{ infoPanel.group ?? '—' }}</div>
          <div><dt class="inline font-medium">Size:</dt> {{ formatBytes(infoPanel.size_bytes ?? undefined) }}</div>
          <div><dt class="inline font-medium">Modified:</dt> {{ infoPanel.modified ?? '—' }}</div>
        </dl>
      </Card>

      <Card v-if="renameTarget && canWrite" padding="sm">
        <p class="text-sm font-medium">Rename {{ renameTarget.name }}</p>
        <div class="mt-2 flex gap-2">
          <input v-model="renameValue" class="flex-1 rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
          <button type="button" class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white" @click="confirmRename">Save</button>
          <button type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" @click="renameTarget = null">Cancel</button>
        </div>
      </Card>

      <Card v-if="moveTarget && canWrite" padding="sm">
        <p class="text-sm font-medium">Move {{ moveTarget.name }}</p>
        <div class="mt-2 flex gap-2">
          <input v-model="moveDestination" class="flex-1 rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm font-mono" />
          <button type="button" class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white" @click="confirmMove">Move</button>
          <button type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" @click="moveTarget = null">Cancel</button>
        </div>
      </Card>

      <Card v-if="editorOpen" padding="md">
        <div class="mb-2 flex items-center justify-between">
          <span class="font-mono text-sm">{{ editorPath }}</span>
          <Badge v-if="editorMeta?.mode" size="sm">{{ editorMeta.mode }} · {{ editorMeta.owner }}:{{ editorMeta.group }}</Badge>
        </div>
        <textarea
          v-model="editorContent"
          class="h-64 w-full rounded-lg border border-surface-border bg-transparent p-3 font-mono text-xs"
          :readonly="!canWrite"
        />
        <div class="mt-3 flex gap-2">
          <button v-if="canWrite" type="button" class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white" :disabled="actionKey === 'save'" @click="saveFile">Save</button>
          <button type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" @click="editorOpen = false">Close</button>
        </div>
      </Card>

      <FileTransferQueue />
    </div>
  </DashboardLayout>
</template>

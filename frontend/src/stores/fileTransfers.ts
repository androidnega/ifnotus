import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { filesApi } from '@/api'

export type TransferKind = 'upload' | 'download'
export type TransferStatus = 'queued' | 'active' | 'done' | 'error' | 'cancelled'

export interface FileScope {
  appId?: string
  rootId?: string
}

export interface TransferItem {
  id: string
  kind: TransferKind
  name: string
  path: string
  sizeBytes: number
  progress: number
  status: TransferStatus
  message?: string
  scope: FileScope
}

let idCounter = 0
function nextId() {
  idCounter += 1
  return `xfer-${Date.now()}-${idCounter}`
}

export const useFileTransferStore = defineStore('fileTransfers', () => {
  const items = ref<TransferItem[]>([])
  const processing = ref(false)
  const uploadFileMap = new Map<string, File>()

  const active = computed(() => items.value.find((i) => i.status === 'active'))
  const queuedCount = computed(() => items.value.filter((i) => i.status === 'queued').length)
  const hasPending = computed(() => items.value.some((i) => i.status === 'queued' || i.status === 'active'))

  function enqueueUploadMany(files: File[], targetPath: string, scope: FileScope) {
    for (const file of files) {
      const id = nextId()
      uploadFileMap.set(id, file)
      items.value.push({
        id,
        kind: 'upload',
        name: file.name,
        path: targetPath,
        sizeBytes: file.size,
        progress: 0,
        status: 'queued',
        scope,
        message: 'Waiting in queue…',
      })
    }
    void processQueue()
  }

  function enqueueDownload(filePath: string, fileName: string, sizeBytes: number, scope: FileScope) {
    items.value.push({
      id: nextId(),
      kind: 'download',
      name: fileName,
      path: filePath,
      sizeBytes,
      progress: 0,
      status: 'queued',
      scope,
      message: 'Waiting in queue…',
    })
    void processQueue()
  }

  function clearCompleted() {
    items.value = items.value.filter((i) => i.status !== 'done' && i.status !== 'cancelled')
    for (const id of [...uploadFileMap.keys()]) {
      if (!items.value.some((i) => i.id === id)) uploadFileMap.delete(id)
    }
  }

  function removeItem(id: string) {
    const item = items.value.find((i) => i.id === id)
    if (item && item.status === 'queued') {
      item.status = 'cancelled'
      item.message = 'Cancelled'
      uploadFileMap.delete(id)
    }
  }

  async function processQueue() {
    if (processing.value) return
    processing.value = true
    try {
      while (true) {
        const item = items.value.find((i) => i.status === 'queued')
        if (!item) break

        item.status = 'active'
        item.message = item.kind === 'upload' ? 'Uploading…' : 'Downloading…'
        item.progress = 0

        try {
          if (item.kind === 'upload') {
            const file = uploadFileMap.get(item.id)
            if (!file) throw new Error('File data missing from queue')
            await filesApi.uploadChunked(file, item.path, item.scope, (pct) => {
              item.progress = pct
            })
            uploadFileMap.delete(item.id)
          } else {
            await filesApi.downloadQueued(item.path, item.name, item.scope, (pct) => {
              item.progress = pct
            })
          }
          item.progress = 100
          item.status = 'done'
          item.message = item.kind === 'upload' ? 'Upload complete' : 'Download complete'
        } catch (e) {
          item.status = 'error'
          item.message = e instanceof Error ? e.message : 'Transfer failed'
          uploadFileMap.delete(item.id)
        }
      }
    } finally {
      processing.value = false
    }
  }

  return {
    items,
    processing,
    active,
    queuedCount,
    hasPending,
    enqueueUploadMany,
    enqueueDownload,
    clearCompleted,
    removeItem,
  }
})

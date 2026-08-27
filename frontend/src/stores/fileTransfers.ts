import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { customersApi, filesApi } from '@/api'

export type TransferKind = 'upload' | 'download'
/** Prompt states: queued | uploading | processing | complete | failed | cancelled */
export type TransferStatus =
  | 'queued'
  | 'uploading'
  | 'processing'
  | 'complete'
  | 'failed'
  | 'cancelled'
  /** @deprecated use uploading */
  | 'active'
  /** @deprecated use complete */
  | 'done'
  /** @deprecated use failed */
  | 'error'

export interface FileScope {
  appId?: string
  rootId?: string
  /** Customer portal environment uploads */
  environmentId?: string
}

export interface TransferItem {
  id: string
  kind: TransferKind
  name: string
  path: string
  sizeBytes: number
  bytesUploaded: number
  progress: number
  speedBps: number
  status: TransferStatus
  message?: string
  scope: FileScope
}

export type UploadProgressInfo = {
  percent: number
  loaded: number
  total: number
  speedBps?: number
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
  const abortMap = new Map<string, AbortController>()

  const active = computed(() =>
    items.value.find((i) => i.status === 'uploading' || i.status === 'processing' || i.status === 'active'),
  )
  const queuedCount = computed(() => items.value.filter((i) => i.status === 'queued').length)
  const hasPending = computed(() =>
    items.value.some(
      (i) =>
        i.status === 'queued' ||
        i.status === 'uploading' ||
        i.status === 'processing' ||
        i.status === 'active',
    ),
  )

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
        bytesUploaded: 0,
        progress: 0,
        speedBps: 0,
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
      bytesUploaded: 0,
      progress: 0,
      speedBps: 0,
      status: 'queued',
      scope,
      message: 'Waiting in queue…',
    })
    void processQueue()
  }

  function clearCompleted() {
    items.value = items.value.filter(
      (i) => i.status !== 'complete' && i.status !== 'done' && i.status !== 'cancelled',
    )
    for (const id of [...uploadFileMap.keys()]) {
      if (!items.value.some((i) => i.id === id)) uploadFileMap.delete(id)
    }
  }

  function cancelItem(id: string) {
    const item = items.value.find((i) => i.id === id)
    if (!item) return
    if (item.status === 'queued') {
      item.status = 'cancelled'
      item.message = 'Cancelled'
      uploadFileMap.delete(id)
      return
    }
    if (item.status === 'uploading' || item.status === 'active' || item.status === 'processing') {
      abortMap.get(id)?.abort()
      abortMap.delete(id)
      item.status = 'cancelled'
      item.message = 'Cancelled'
      item.speedBps = 0
    }
  }

  /** @deprecated alias */
  function removeItem(id: string) {
    cancelItem(id)
  }

  function retryItem(id: string) {
    const item = items.value.find((i) => i.id === id)
    if (!item) return
    if (item.status !== 'failed' && item.status !== 'error' && item.status !== 'cancelled') return
    if (item.kind === 'upload' && !uploadFileMap.has(id)) {
      item.message = 'Original file is no longer in memory — pick the file again.'
      return
    }
    item.status = 'queued'
    item.progress = 0
    item.bytesUploaded = 0
    item.speedBps = 0
    item.message = 'Waiting in queue…'
    void processQueue()
  }

  async function processQueue() {
    if (processing.value) return
    processing.value = true
    try {
      while (true) {
        const item = items.value.find((i) => i.status === 'queued')
        if (!item) break

        const controller = new AbortController()
        abortMap.set(item.id, controller)
        item.status = 'uploading'
        item.message = item.kind === 'upload' ? 'Uploading…' : 'Downloading…'
        item.progress = 0
        item.bytesUploaded = 0
        item.speedBps = 0
        const started = performance.now()

        const onProgress = (info: number | UploadProgressInfo) => {
          if (item.status === 'cancelled') return
          const percent = typeof info === 'number' ? info : info.percent
          const loaded = typeof info === 'number'
            ? Math.round((percent / 100) * Math.max(item.sizeBytes, 1))
            : info.loaded
          const total = typeof info === 'number' ? item.sizeBytes : info.total
          item.progress = percent
          item.bytesUploaded = loaded
          const elapsed = (performance.now() - started) / 1000
          item.speedBps =
            typeof info === 'object' && info.speedBps != null
              ? info.speedBps
              : elapsed > 0
                ? loaded / elapsed
                : 0
          item.message =
            item.kind === 'upload'
              ? `Uploading… ${percent}%`
              : `Downloading… ${percent}%`
          void total
        }

        try {
          if (item.kind === 'upload') {
            const file = uploadFileMap.get(item.id)
            if (!file) throw new Error('File data missing from queue')
            if (item.scope.environmentId) {
              await customersApi.uploadEnvChunked(
                item.scope.environmentId,
                file,
                item.path,
                onProgress,
                controller.signal,
              )
            } else {
              await filesApi.uploadChunked(
                file,
                item.path,
                item.scope,
                onProgress,
                controller.signal,
              )
            }
            if (controller.signal.aborted) {
              item.status = 'cancelled'
              item.message = 'Cancelled'
            } else {
              item.status = 'processing'
              item.message = 'Finalizing…'
              item.progress = 100
              item.bytesUploaded = item.sizeBytes
              item.status = 'complete'
              item.message = 'Upload complete'
              uploadFileMap.delete(item.id)
            }
          } else {
            if (item.scope.environmentId) {
              await customersApi.downloadEnvQueued(
                item.scope.environmentId,
                item.path,
                item.name,
                onProgress,
                controller.signal,
              )
            } else {
              await filesApi.downloadQueued(
                item.path,
                item.name,
                item.scope,
                onProgress,
                controller.signal,
              )
            }
            if (controller.signal.aborted) {
              item.status = 'cancelled'
              item.message = 'Cancelled'
            } else {
              item.progress = 100
              item.bytesUploaded = item.sizeBytes
              item.status = 'complete'
              item.message = 'Download complete'
            }
          }
        } catch (e) {
          if (controller.signal.aborted || item.status === 'cancelled') {
            item.status = 'cancelled'
            item.message = 'Cancelled'
          } else {
            item.status = 'failed'
            item.message = e instanceof Error ? e.message : 'Transfer failed'
            // Keep File in map so retry works for uploads.
          }
        } finally {
          abortMap.delete(item.id)
          item.speedBps = 0
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
    cancelItem,
    removeItem,
    retryItem,
  }
})

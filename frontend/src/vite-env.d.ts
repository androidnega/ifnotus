/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface MonacoEnvironment {
  getWorker(workerId: string, label: string): Worker
}

interface Window {
  MonacoEnvironment?: MonacoEnvironment
}

declare var MonacoEnvironment: MonacoEnvironment | undefined


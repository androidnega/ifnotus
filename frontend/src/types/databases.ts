export type DatabaseEngine = 'sqlite' | 'mysql' | 'postgresql' | 'mongodb'

export interface EngineStatus {
  engine: DatabaseEngine
  available: boolean
  running: boolean
  version?: string | null
  host?: string | null
  port?: number | null
  message?: string | null
  installable?: boolean
}

export interface ManagedDatabase {
  id: string
  engine: DatabaseEngine
  name: string
  username?: string | null
  host?: string | null
  port?: number | null
  path?: string | null
  connection_uri?: string | null
  password_set: boolean
  password_masked?: string | null
  notes?: string | null
  created_at?: string | null
  managed: boolean
  size_bytes?: number | null
  table_count?: number | null
}

export interface LiveDatabase {
  engine: DatabaseEngine
  name: string
  owner?: string | null
  size_bytes?: number | null
  path?: string | null
  table_count?: number | null
}

export interface DatabaseOverview {
  engines: EngineStatus[]
  managed: ManagedDatabase[]
  live: LiveDatabase[]
}

export interface DatabaseCreateBody {
  engine: DatabaseEngine
  name: string
  username?: string
  password?: string
  path?: string
  create_user?: boolean
  notes?: string
  overwrite?: boolean
}

export interface DatabaseAdoptBody {
  engine: DatabaseEngine
  name: string
  username?: string
  password?: string
  path?: string
  host?: string
  port?: number
  notes?: string
}

export interface DatabaseLiveDropBody {
  engine: DatabaseEngine
  name: string
  confirm_password: string
  path?: string
  username?: string
  drop_user?: boolean
  remove_files?: boolean
}

export interface DatabaseBackup {
  id: string
  engine: DatabaseEngine
  database: string
  filename: string
  path: string
  size_bytes?: number | null
  created_at?: string | null
  kind?: string
}

export interface DatabaseCreated {
  success: boolean
  message: string
  database: ManagedDatabase
  password?: string | null
  connection_uri?: string | null
  details?: Record<string, unknown>
}

export interface DbColumn {
  name: string
  data_type?: string | null
  nullable?: boolean | null
  primary_key?: boolean
  default?: string | null
}

export interface DbTable {
  name: string
  schema_name?: string | null
  columns: DbColumn[]
  approx_rows?: number | null
}

export interface DbSchema {
  engine: DatabaseEngine
  database: string
  path?: string | null
  tables: DbTable[]
  collections: string[]
}

export interface DbQueryResult {
  success: boolean
  engine: DatabaseEngine
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  affected_rows?: number | null
  message?: string | null
  truncated?: boolean
  duration_ms?: number | null
}

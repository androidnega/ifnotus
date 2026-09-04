import { computed, onUnmounted, ref, toValue, watch, type MaybeRefOrGetter, type Ref } from 'vue'
import { customersApi } from '@/api'
import type { CustomerDashboard } from '@/types/platform'
import type { DbQueryResult, DbSchema } from '@/types/databases'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import type { EnvUsageSnapshot } from '@/lib/resourceUsage'

export type PortalSiteTab = 'files' | 'stack' | 'applications' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail' | 'git' | ''

export function usePortalSiteTools(
  dash: Ref<CustomerDashboard | null>,
  options?: {
    /** When set, environment switching is locked to this id (hosting panel). */
    lockEnvId?: MaybeRefOrGetter<string>
  },
) {
  const activeEnvId = ref('')
  const filePath = ref('.')
  const fileEntries = ref<Array<{ name: string; path: string; is_dir: boolean; size_bytes?: number | null }>>([])
  const fileContent = ref('')
  const editingFile = ref('')
  const fileMsg = ref('')
  const dbInfo = ref('')
  const dbCreds = ref<{
    engine?: string | null
    name?: string | null
    username?: string | null
    host?: string | null
    port?: number | null
    password_set?: boolean
    password?: string | null
    remote_access_mode?: string | null
    message?: string | null
    empty?: boolean
    error?: string
  } | null>(null)
  const dbSchema = ref<DbSchema | null>(null)
  const dbRows = ref<DbQueryResult | null>(null)
  const dbStudioBusy = ref(false)
  const dbStudioMsg = ref('')
  const dbSelectedTable = ref('')
  const dbRowOffset = ref(0)
  const dbSql = ref('SELECT * FROM ')
  const dbList = ref<
    Array<{
      id: string
      engine?: string | null
      logical_name?: string | null
      name?: string | null
      username?: string | null
      host?: string | null
      port?: number | null
      password_set?: boolean
      legacy?: boolean
      status?: string | null
      size_mb?: number | null
      remote_access_mode?: string | null
      message?: string | null
    }>
  >([])
  const selectedDbId = ref('')
  const dbBusy = ref(false)
  const dbActionMsg = ref('')
  const newDbEngine = ref('mysql')
  const newDbName = ref('')
  const newDbUser = ref('')
  const newDbPassword = ref('')
  const ftpInfo = ref('')
  const ftpCreds = ref<{
    enabled?: boolean
    username?: string | null
    host?: string
    wordpress_host?: string
    port?: number
    password_set?: boolean
    password?: string | null
    home?: string | null
    connection_type?: string
    sftp_coming_note?: string | null
    hint?: string
    message?: string | null
    error?: string
  } | null>(null)
  const sftpCreds = ref<{
    sftp_allowed?: boolean
    enabled?: boolean
    username?: string | null
    host?: string
    shared_ip?: string | null
    port?: number
    password_set?: boolean
    password?: string | null
    connection_type?: string
    shell_access?: boolean
    keys?: Array<{ id: string; name?: string | null; fingerprint?: string | null; created_at?: string | null }>
    command?: string | null
    hint?: string
    message?: string | null
    error?: string
  } | null>(null)
  const sftpInfo = ref('')
  const sftpKeyInput = ref('')
  const sftpKeyName = ref('')
  const sshCreds = ref<{
    ssh_allowed?: boolean
    enabled?: boolean
    username?: string | null
    host?: string
    shared_ip?: string | null
    port?: number
    command?: string | null
    min_price_ghs?: number
    hint?: string
    message?: string | null
    error?: string
  } | null>(null)
  const usageInfo = ref('')
  const logEntries = ref<Array<{ source: string; message: string }>>([])
  const logMsg = ref('')
  const logBusy = ref(false)
  const usageStatus = ref<'ok' | 'warning' | 'over' | ''>('')
  const usagePct = ref(0)
  const usageSnapshot = ref<EnvUsageSnapshot | null>(null)
  const monitoringSnapshot = ref<{
    level?: string
    disk?: { used_gb?: number; limit_gb?: number; pct?: number; file_count?: number; status?: string }
    health_status?: string
    site_status?: string
    ssl?: { status?: string; days_remaining?: number | null }
    backups?: { success_count?: number }
    applications?: { total?: number; active?: number }
    mail?: { enabled?: boolean; used_mb?: number | null; limit_mb?: number | null }
    cpu?: { percent?: number; limit_vcpu?: number }
    memory?: { rss_mb?: number; limit_mb?: number; pct?: number }
    processes?: { count?: number }
    databases?: { count?: number; total_size_mb?: number }
    note?: string | null
  } | null>(null)
  const monitoringMsg = ref('')
  const healthInfo = ref('')

  const gitStatus = ref<{
    environment_id?: string
    configured?: boolean
    path?: string
    home_display?: string
    repos_limit?: number | null
    branch?: string | null
    commit?: string | null
    remote?: string | null
    dirty?: boolean
    message?: string
    repositories?: Array<{
      id: string
      name: string
      path: string
      path_display: string
      configured: boolean
      branch?: string | null
      commit?: string | null
      commit_full?: string | null
      author?: string | null
      author_email?: string | null
      committed_at?: string | null
      message?: string | null
      remote?: string | null
      dirty?: boolean
      clone_url?: string | null
    }>
  } | null>(null)
  const gitBusy = ref(false)
  const gitMsg = ref('')
  const gitCloneUrl = ref('')
  const gitCloneBranch = ref('')
  const gitView = ref<'list' | 'create' | 'history'>('list')
  const gitCloneRemote = ref(true)
  const gitRepoName = ref('')
  const gitRepoPath = ref('')
  const gitCreateAnother = ref(false)
  const gitServeAsWebsite = ref(true)
  const gitExpandedId = ref<string | null>(null)
  const gitSearch = ref('')
  const gitHistory = ref<Array<{ commit: string; committed_at: string; author: string; message: string }>>([])
  const gitHistoryPath = ref('')
  watch(gitView, (view) => {
    if (view === 'create' && gitStatus.value?.home_display) {
      const home = gitStatus.value.home_display.replace(/\/$/, '')
      if (!gitRepoPath.value || gitRepoPath.value === `${home}/`) {
        gitRepoPath.value = `${home}/`
      }
    }
  })
  const dnsInfo = ref('')
  const dnsData = ref<{
    domain?: string | null
    addon?: string | null
    custom?: string | null
    nameservers?: string[]
    customDomains?: string[]
    availableDomains?: string[]
    used?: number
    limit?: number
    canAssign?: boolean
    ip: string
    records?: Array<{ record_type: string; host: string; value: string; ttl?: number }>
    message?: string
    namecheap?: boolean
    includedHostname?: boolean
    nsLive?: boolean | null
    resolves?: boolean | null
    dnsLive?: boolean
    dnsMode?: string | null
    aRecordsLive?: boolean
    cpanelLive?: boolean
    sslReady?: boolean
    statusSummary?: string
    checklist?: Array<{ id: string; label: string; done: boolean; detail?: string }>
    panelHostname?: string | null
    panelUrl?: string | null
    mailHostname?: string | null
    error?: string
  } | null>(null)
  const sslMsg = ref('')
  const backups = ref<
    Array<{
      id: string
      status: string
      file_size?: number | null
      created_at?: string | null
      filename: string
    }>
  >([])
  const backupMsg = ref('')
  const stackMsg = ref('')
  const stackBusy = ref(false)
  const stackProgress = ref<import('@/api').StackInstallProgress | null>(null)
  const stackJobId = ref('')
  const stackOutcome = ref<'idle' | 'running' | 'success' | 'error'>('idle')
  let stackPollTimer: ReturnType<typeof setInterval> | null = null
  let usagePollTimer: ReturnType<typeof setInterval> | null = null

  const selectedStack = ref('static')
  const stacks = ref<
    Array<{
      id: string
      name: string
      description: string
      icon?: string
      level?: string
      one_click?: boolean
      allowed?: boolean
    }>
  >([])
  const currentStack = ref<Record<string, unknown> | null>(null)
  const cronJobs = ref<
    Array<{
      id: string
      schedule: string
      command: string
      enabled: boolean
      last_run_at?: string | null
      last_status?: string | null
      last_output?: string | null
    }>
  >([])
  const cronSchedule = ref('*/15 * * * *')
  const cronCommand = ref('php artisan schedule:run')
  const cronMsg = ref('')
  const cronBusy = ref(false)
  const cronLimits = ref<{
    max_jobs: number
    min_interval_minutes: number
    jobs_used: number
    runs_as?: string | null
    note?: string
  } | null>(null)
  const appCatalog = ref<
    Array<{
      id: string
      runtime: string
      label: string
      stack_key: string
      allowed: boolean
      runtime_version?: string
      runtime_versions?: string[]
    }>
  >([])
  const applications = ref<
    Array<{
      id: string
      name: string
      runtime: string
      framework?: string | null
      framework_label?: string | null
      runtime_version?: string | null
      status: string
      port?: number | null
      slug?: string | null
      app_root?: string | null
      app_root_display?: string | null
      uses_site_root?: boolean
      serve_url?: string | null
      log_path?: string | null
      start_command?: string | null
      runtime_version?: string | null
      env_var_keys?: string[]
    }>
  >([])
  const appMsg = ref('')
  const appBusy = ref(false)
  const newAppName = ref('')
  const newAppFramework = ref('fastapi')
  const newAppGitUrl = ref('')
  const newAppRuntimeVersion = ref<string | null>(null)
  // Python/FastAPI entry wiring (maps to `module:object` used by gunicorn+uvicorn).
  const newAppPythonModule = ref('')
  const newAppPythonObject = ref('')
  const newAppRootPlacement = ref<'apps' | 'home' | 'public_html'>('apps')
  const newAppServeAtDomain = ref(false)
  const newAppLogPath = ref('')
  const showAppCreateForm = ref(false)
  const editingAppId = ref<string | null>(null)
  const editAppName = ref('')
  const editAppLogPath = ref('')
  const editAppPythonModule = ref('app.main')
  const editAppPythonObject = ref('app')
  const editAppServeAtDomain = ref(false)
  const editAppRuntimeVersion = ref<string | null>(null)
  const editAppEnvVars = ref<Array<{ key: string; value: string }>>([])
  const newAppEnvVars = ref<Array<{ key: string; value: string }>>([])
  const editEnvVarsDirty = ref(false)

  function addEnvVarRow(target: 'new' | 'edit') {
    const rows = target === 'new' ? newAppEnvVars : editAppEnvVars
    rows.value = [...rows.value, { key: '', value: '' }]
    if (target === 'edit') editEnvVarsDirty.value = true
  }

  function removeEnvVarRow(target: 'new' | 'edit', index: number) {
    const rows = target === 'new' ? newAppEnvVars : editAppEnvVars
    rows.value = rows.value.filter((_, i) => i !== index)
    if (target === 'edit') editEnvVarsDirty.value = true
  }

  function updateEnvVarRow(
    target: 'new' | 'edit',
    index: number,
    field: 'key' | 'value',
    value: string,
  ) {
    const rows = target === 'new' ? newAppEnvVars : editAppEnvVars
    rows.value = rows.value.map((row, i) => (i === index ? { ...row, [field]: value } : row))
    if (target === 'edit') editEnvVarsDirty.value = true
  }

  function envVarsToRecord(rows: Array<{ key: string; value: string }>): Record<string, string> {
    const out: Record<string, string> = {}
    for (const row of rows) {
      const key = String(row.key || '').trim()
      if (!key) continue
      out[key] = String(row.value ?? '')
    }
    return out
  }

  const lockedEnvId = computed(() => {
    if (!options?.lockEnvId) return ''
    return String(toValue(options.lockEnvId) || '')
  })

  const activeEnv = computed(
    () =>
      dash.value?.environments.find((e) => e.id === activeEnvId.value) ||
      (lockedEnvId.value
        ? dash.value?.environments.find((e) => e.id === lockedEnvId.value)
        : null) ||
      dash.value?.environments[0] ||
      null,
  )

  const dbCanWrite = computed(() => {
    const level = activeEnv.value?.capabilities?.levels?.db_manage
    if (!level) return true
    return level === 'yes'
  })

  function healthLabel(status?: string | null) {
    switch ((status || 'unknown').toLowerCase()) {
      case 'healthy':
        return 'Online'
      case 'degraded':
        return 'Degraded'
      case 'unhealthy':
        return 'Offline'
      case 'offline':
        return 'Offline'
      case 'checking':
        return 'Checking'
      default:
        return 'Unknown'
    }
  }

  function stopStackPoll() {
    if (stackPollTimer) {
      clearInterval(stackPollTimer)
      stackPollTimer = null
    }
  }

  function applyStackProgress(progress?: import('@/api').StackInstallProgress | null, fallbackMsg?: string) {
    if (progress) stackProgress.value = progress
    if (progress?.label) stackMsg.value = progress.label
    else if (progress?.message) stackMsg.value = progress.message
    else if (fallbackMsg) stackMsg.value = fallbackMsg
  }

  async function pollStackJob(envId: string, jobId: string) {
    try {
      const { data } = await customersApi.getEnvStackJob(envId, jobId)
      applyStackProgress(data.progress, data.message || undefined)
      const status = (data.progress?.status || data.status || '').toLowerCase()
      if (status === 'success') {
        stopStackPoll()
        stackBusy.value = false
        stackOutcome.value = 'success'
        stackMsg.value = data.message || data.progress?.message || 'Stack installed successfully.'
        currentStack.value = data.current || data.result || currentStack.value
        await loadFiles()
        await loadStacks()
        return
      }
      if (status === 'failed') {
        stopStackPoll()
        stackBusy.value = false
        stackOutcome.value = 'error'
        stackMsg.value = data.error || data.message || data.progress?.error || 'Install failed.'
        return
      }
      stackOutcome.value = 'running'
      stackBusy.value = true
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      stackMsg.value = err.response?.data?.error?.message ?? (stackMsg.value || 'Checking install status…')
    }
  }

  function startStackPoll(envId: string, jobId: string) {
    stopStackPoll()
    stackJobId.value = jobId
    void pollStackJob(envId, jobId)
    stackPollTimer = setInterval(() => {
      void pollStackJob(envId, jobId)
    }, 1500)
  }

  onUnmounted(() => {
    stopStackPoll()
    stopUsagePoll()
  })

  function stopUsagePoll() {
    if (usagePollTimer) {
      clearInterval(usagePollTimer)
      usagePollTimer = null
    }
  }

  function startUsagePoll() {
    stopUsagePoll()
    usagePollTimer = setInterval(() => {
      void loadUsage({ quiet: true })
    }, 30_000)
  }

  async function loadFiles() {
    if (!activeEnv.value) return
    fileMsg.value = ''
    try {
      const { data } = await customersApi.listEnvFiles(activeEnv.value.id, filePath.value)
      filePath.value = data.path || '.'
      fileEntries.value = data.entries
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      fileMsg.value = err.response?.data?.error?.message ?? 'Could not list files.'
    }
  }

  async function openEntry(entry: { name: string; path: string; is_dir: boolean }) {
    if (!activeEnv.value) return
    if (entry.is_dir) {
      filePath.value = entry.path
      editingFile.value = ''
      fileContent.value = ''
      await loadFiles()
      return
    }
    try {
      const { data } = await customersApi.readEnvFile(activeEnv.value.id, entry.path)
      editingFile.value = entry.path
      fileContent.value = data.content ?? ''
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      fileMsg.value = err.response?.data?.error?.message ?? 'Could not open file.'
    }
  }

  async function goUp() {
    if (filePath.value === '.' || !filePath.value) return
    const parts = filePath.value.split('/').filter(Boolean)
    parts.pop()
    filePath.value = parts.length ? parts.join('/') : '.'
    editingFile.value = ''
    await loadFiles()
  }

  async function saveFile() {
    if (!activeEnv.value || !editingFile.value) return
    fileMsg.value = 'Saving…'
    try {
      await customersApi.writeEnvFile(activeEnv.value.id, editingFile.value, fileContent.value)
      fileMsg.value = 'Saved.'
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      fileMsg.value = err.response?.data?.error?.message ?? 'Save failed.'
    }
  }

  async function loadDbList() {
    if (!activeEnv.value) return
    dbActionMsg.value = ''
    try {
      const { data } = await customersApi.listEnvDatabases(activeEnv.value.id)
      dbList.value = data
      if (!selectedDbId.value && data.length) {
        selectedDbId.value = data[0].id
      } else if (selectedDbId.value && !data.some((d) => d.id === selectedDbId.value)) {
        selectedDbId.value = data[0]?.id || ''
      }
      if (selectedDbId.value) {
        await loadDb(true)
      } else {
        dbCreds.value = { empty: true }
        dbInfo.value = 'No databases yet. Create one below or install WordPress/Laravel from Stack.'
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbActionMsg.value = err.response?.data?.error?.message ?? 'Could not load databases.'
    }
  }

  async function loadDb(reveal = true) {
    if (!activeEnv.value) return
    dbInfo.value = 'Loading…'
    try {
      if (selectedDbId.value) {
        if (!reveal) {
          const row = dbList.value.find((d) => d.id === selectedDbId.value)
          if (row) {
            dbCreds.value = {
              engine: row.engine,
              name: row.name,
              username: row.username,
              host: row.host || 'localhost',
              port: row.port || 3306,
              password_set: row.password_set,
              password: null,
              remote_access_mode: row.remote_access_mode || 'localhost',
              message: row.message || null,
            }
            dbInfo.value = ''
            return
          }
        }
        const { data } = await customersApi.revealEnvDatabase(activeEnv.value.id, selectedDbId.value)
        if (!data.name && !data.engine) {
          dbCreds.value = { empty: true }
          dbInfo.value = 'No database on this site yet.'
          dbSchema.value = null
          dbRows.value = null
          return
        }
        const listed = dbList.value.find((d) => d.id === selectedDbId.value)
        dbCreds.value = {
          engine: data.engine,
          name: data.name,
          username: data.username,
          host: data.host || 'localhost',
          port: data.port || 3306,
          password_set: Boolean(data.password),
          password: data.password || null,
          remote_access_mode: listed?.remote_access_mode || 'localhost',
          message: listed?.message || null,
        }
        dbInfo.value = ''
        await loadDbSchema()
        return
      }
      const { data } = await customersApi.getEnvDatabase(activeEnv.value.id, reveal)
      if (!data.name && !data.engine) {
        dbCreds.value = { empty: true }
        dbInfo.value = 'No database on this site yet. Install WordPress or Laravel from Stack when you need one.'
        dbSchema.value = null
        dbRows.value = null
        return
      }
      dbCreds.value = {
        engine: data.engine,
        name: data.name,
        username: data.username,
        host: data.host || 'localhost',
        port: data.port || 3306,
        password_set: data.password_set,
        password: data.password || null,
        remote_access_mode: 'localhost',
        message: null,
      }
      dbInfo.value = ''
      await loadDbSchema()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not load database.'
      dbInfo.value = msg
      dbCreds.value = { error: msg }
    }
  }

  async function createDatabase() {
    if (!activeEnv.value || !newDbName.value.trim()) return
    dbBusy.value = true
    dbActionMsg.value = 'Creating database & user…'
    try {
      await customersApi.createEnvDatabase(activeEnv.value.id, {
        engine: newDbEngine.value,
        logical_name: newDbName.value.trim(),
        username: newDbUser.value.trim() || undefined,
        password: newDbPassword.value.trim() || undefined,
      })
      newDbName.value = ''
      newDbUser.value = ''
      newDbPassword.value = ''
      dbActionMsg.value = 'Database & user created successfully with full permissions.'
      await loadDbList()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbActionMsg.value = err.response?.data?.error?.message ?? 'Create failed.'
    } finally {
      dbBusy.value = false
    }
  }

  async function importDatabaseSql(dbId?: string | null, sqlContent?: string) {
    if (!activeEnv.value || !sqlContent?.trim()) return
    dbBusy.value = true
    dbActionMsg.value = 'Importing SQL file…'
    try {
      const { data } = await customersApi.importEnvDatabaseSql(activeEnv.value.id, dbId, sqlContent.trim())
      dbActionMsg.value = data.message || 'SQL import completed successfully.'
      await loadDbList()
      if (selectedDbId.value) await loadDb(true)
      return data
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'SQL import failed.'
      dbActionMsg.value = msg
      throw new Error(msg)
    } finally {
      dbBusy.value = false
    }
  }

  async function backupDatabase(dbId: string) {
    if (!activeEnv.value) return
    dbBusy.value = true
    dbActionMsg.value = 'Generating database backup…'
    try {
      const { data } = await customersApi.backupEnvDatabase(activeEnv.value.id, dbId)
      dbActionMsg.value = 'Database backup generated successfully.'
      return data
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbActionMsg.value = err.response?.data?.error?.message ?? 'Backup failed.'
    } finally {
      dbBusy.value = false
    }
  }

  async function deleteDatabase(dbId: string) {
    if (!activeEnv.value) return
    if (!confirm('Delete this database? A backup is taken first when supported.')) return
    dbBusy.value = true
    dbActionMsg.value = 'Deleting…'
    try {
      await customersApi.deleteEnvDatabase(activeEnv.value.id, dbId)
      if (selectedDbId.value === dbId) selectedDbId.value = ''
      dbActionMsg.value = 'Database deleted.'
      await loadDbList()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbActionMsg.value = err.response?.data?.error?.message ?? 'Delete failed.'
    } finally {
      dbBusy.value = false
    }
  }

  async function resetDbPassword(dbId: string) {
    if (!activeEnv.value) return
    if (!confirm('Generate a new password for this database?')) return
    dbBusy.value = true
    dbActionMsg.value = 'Resetting password…'
    try {
      const { data } = await customersApi.resetEnvDatabasePassword(activeEnv.value.id, dbId)
      if (selectedDbId.value === dbId && data) {
        dbCreds.value = {
          engine: data.engine,
          name: data.name,
          username: data.username,
          host: data.host || 'localhost',
          port: data.port || 3306,
          password_set: Boolean(data.password),
          password: data.password || null,
        }
      }
      dbActionMsg.value = 'Password reset — copy the new value now.'
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbActionMsg.value = err.response?.data?.error?.message ?? 'Reset failed.'
    } finally {
      dbBusy.value = false
    }
  }

  function selectDatabase(dbId: string) {
    selectedDbId.value = dbId
    loadDb(true)
  }

  async function loadDbSchema() {
    if (!activeEnv.value) return
    dbStudioBusy.value = true
    dbStudioMsg.value = ''
    try {
      const { data } = await customersApi.getEnvDatabaseSchema(activeEnv.value.id)
      dbSchema.value = data
      if (!data.tables?.length) {
        dbStudioMsg.value = 'This database has no tables yet.'
        dbRows.value = null
        return
      }
      if (dbSelectedTable.value && data.tables.some((t) => t.name === dbSelectedTable.value)) {
        await loadDbRows(dbSelectedTable.value, dbRowOffset.value)
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbSchema.value = null
      dbStudioMsg.value = err.response?.data?.error?.message ?? 'Could not open tables.'
    } finally {
      dbStudioBusy.value = false
    }
  }

  async function loadDbRows(table: string, offset = 0) {
    if (!activeEnv.value) return
    dbSelectedTable.value = table
    dbRowOffset.value = Math.max(0, offset)
    dbStudioBusy.value = true
    try {
      const { data } = await customersApi.getEnvDatabaseRows(activeEnv.value.id, {
        table,
        limit: 50,
        offset: dbRowOffset.value,
      })
      dbRows.value = data
      if (!data.rows?.length && dbRowOffset.value > 0) {
        dbStudioMsg.value = 'No more rows.'
      } else {
        dbStudioMsg.value = ''
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbStudioMsg.value = err.response?.data?.error?.message ?? 'Could not load rows.'
    } finally {
      dbStudioBusy.value = false
    }
  }

  async function runDbQuery() {
    if (!activeEnv.value || !dbSql.value.trim()) return
    dbStudioBusy.value = true
    dbStudioMsg.value = ''
    try {
      const { data } = await customersApi.queryEnvDatabase(activeEnv.value.id, dbSql.value.trim(), 100)
      dbRows.value = data
      dbSelectedTable.value = ''
      if (data.message) dbStudioMsg.value = data.message
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      dbStudioMsg.value = err.response?.data?.error?.message ?? 'Query failed.'
    } finally {
      dbStudioBusy.value = false
    }
  }

  async function loadFtp(reveal = true) {
    if (!activeEnv.value) return
    ftpInfo.value = 'Loading…'
    try {
      const { data } = await customersApi.getEnvFtp(activeEnv.value.id, reveal)
      ftpCreds.value = {
        enabled: data.enabled,
        username: data.username,
        host: data.host,
        wordpress_host: data.wordpress_host || 'localhost',
        port: data.port,
        password_set: data.password_set,
        password: data.password || null,
        home: data.home,
        connection_type: data.connection_type,
        sftp_coming_note: data.sftp_coming_note,
        hint: data.hint,
        message: data.message,
      }
      ftpInfo.value = ''
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not load FTP.'
      ftpInfo.value = msg
      ftpCreds.value = { host: '', error: msg }
    }
    await Promise.allSettled([loadSsh(), loadSftp(reveal)])
  }

  async function loadSftp(reveal = true) {
    if (!activeEnv.value) return
    sftpInfo.value = 'Loading…'
    try {
      const { data } = await customersApi.getEnvSftp(activeEnv.value.id, reveal)
      sftpCreds.value = data
      sftpInfo.value = ''
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not load SFTP.'
      sftpInfo.value = msg
      sftpCreds.value = { host: 'ifnotus.space', error: msg }
    }
  }

  async function ensureSftp(resetPassword = false) {
    if (!activeEnv.value) return
    sftpInfo.value = 'Loading…'
    try {
      const { data } = await customersApi.ensureEnvSftp(activeEnv.value.id, resetPassword)
      sftpCreds.value = data
      sftpInfo.value = ''
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not create SFTP account.'
      sftpInfo.value = msg
      sftpCreds.value = { ...(sftpCreds.value || { host: 'ifnotus.space' }), error: msg }
    }
  }

  async function addSftpKey() {
    if (!activeEnv.value || !sftpKeyInput.value.trim()) return
    try {
      await customersApi.addEnvSftpKey(activeEnv.value.id, {
        public_key: sftpKeyInput.value.trim(),
        name: sftpKeyName.value.trim() || undefined,
      })
      sftpKeyInput.value = ''
      sftpKeyName.value = ''
      await loadSftp(true)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      sftpInfo.value = err.response?.data?.error?.message ?? 'Could not add SSH key.'
    }
  }

  async function removeSftpKey(keyId: string) {
    if (!activeEnv.value) return
    try {
      await customersApi.deleteEnvSftpKey(activeEnv.value.id, keyId)
      await loadSftp(false)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      sftpInfo.value = err.response?.data?.error?.message ?? 'Could not remove SSH key.'
    }
  }

  function setSftpKeyInput(value: string) {
    sftpKeyInput.value = value
  }

  function setSftpKeyName(value: string) {
    sftpKeyName.value = value
  }

  async function loadSsh() {
    if (!activeEnv.value) return
    try {
      const { data } = await customersApi.getEnvSsh(activeEnv.value.id, false)
      sshCreds.value = data
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      sshCreds.value = { host: 'ssh.ifnotus.space', error: err.response?.data?.error?.message ?? 'Could not load SSH.' }
    }
  }

  async function ensureSsh() {
    if (!activeEnv.value) return
    try {
      const { data } = await customersApi.ensureEnvSsh(activeEnv.value.id)
      sshCreds.value = data
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      sshCreds.value = {
        ...(sshCreds.value || { host: 'ssh.ifnotus.space' }),
        error: err.response?.data?.error?.message ?? 'Could not enable SSH.',
      }
    }
  }

  async function ensureFtp(resetPassword = false) {
    if (!activeEnv.value) return
    ftpInfo.value = 'Loading…'
    try {
      const { data } = await customersApi.ensureEnvFtp(activeEnv.value.id, resetPassword)
      ftpCreds.value = {
        enabled: data.enabled,
        username: data.username,
        host: data.host,
        wordpress_host: data.wordpress_host || 'localhost',
        port: data.port,
        password_set: data.password_set,
        password: data.password || null,
        home: data.home,
        connection_type: data.connection_type,
        hint: data.hint,
        message: data.message || 'Your FTP login is ready.',
      }
      ftpInfo.value = ''
      await loadSsh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not create FTP account.'
      ftpInfo.value = msg
      ftpCreds.value = { ...(ftpCreds.value || { host: '' }), error: msg }
    }
  }

  async function repairFs() {
    if (!activeEnv.value) return
    try {
      const { data } = await customersApi.repairEnvFilesystem(activeEnv.value.id)
      fileMsg.value = data.message
      await loadFtp(true)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      fileMsg.value = err.response?.data?.error?.message ?? 'Could not repair file access.'
    }
  }

  function mapDns(
    data: {
      domain?: string | null
      addon_domain?: string | null
      custom_domain?: string | null
      nameservers?: string[]
      custom_domains?: string[]
      available_domains?: string[]
      custom_domains_used?: number
      custom_domains_limit?: number
      can_assign?: boolean
      recommended_ip?: string
      records?: Array<{ record_type: string; host: string; value: string; ttl?: number }>
      message?: string
      namecheap_pushed?: boolean
      included_hostname?: boolean
      ns_live?: boolean | null
      resolves?: boolean | null
      dns_live?: boolean
      dns_mode?: string | null
      a_records_live?: boolean
      cpanel_live?: boolean
      ssl_ready?: boolean
      status_summary?: string
      checklist?: Array<{ id: string; label: string; done: boolean; detail?: string }>
      panel_hostname?: string | null
      panel_url?: string | null
      mail_hostname?: string | null
    },
    fallbackDomain?: string | null,
  ) {
    return {
      domain: data.domain || fallbackDomain,
      addon: data.addon_domain || null,
      custom: data.custom_domain || null,
      nameservers: data.nameservers?.length ? data.nameservers : ['ns1.ifnotus.space', 'ns2.ifnotus.space'],
      customDomains: data.custom_domains || [],
      availableDomains: data.available_domains || [],
      used: data.custom_domains_used ?? 0,
      limit: data.custom_domains_limit ?? 1,
      canAssign: Boolean(data.can_assign),
      ip: data.recommended_ip || '',
      records: data.records || [],
      message: data.message,
      namecheap: Boolean(data.namecheap_pushed),
      includedHostname: Boolean(data.included_hostname),
      nsLive: data.ns_live ?? null,
      resolves: data.resolves ?? null,
      dnsLive: Boolean(data.dns_live),
      dnsMode: data.dns_mode ?? null,
      aRecordsLive: Boolean(data.a_records_live),
      cpanelLive: Boolean(data.cpanel_live),
      sslReady: Boolean(data.ssl_ready),
      statusSummary: data.status_summary || data.message || '',
      checklist: data.checklist || [],
      panelHostname: data.panel_hostname || null,
      panelUrl: data.panel_url || null,
      mailHostname: data.mail_hostname || null,
    }
  }

  async function loadDns() {
    if (!activeEnv.value) return
    dnsInfo.value = 'Loading…'
    try {
      const { data } = await customersApi.getEnvDns(activeEnv.value.id)
      dnsData.value = mapDns(data, activeEnv.value.domain)
      dnsInfo.value = ''
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not load DNS.'
      dnsInfo.value = msg
      dnsData.value = { ip: '', error: msg }
    }
  }

  async function ensureDns() {
    if (!activeEnv.value) return
    dnsInfo.value = 'Updating…'
    try {
      const { data } = await customersApi.ensureEnvDnsA(activeEnv.value.id)
      dnsData.value = mapDns(data, activeEnv.value.domain)
      dnsInfo.value = ''
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not update nameservers.'
      dnsInfo.value = msg
      if (dnsData.value) dnsData.value = { ...dnsData.value, error: msg }
    }
  }

  async function attachCustomDomain(domainName: string) {
    if (!activeEnv.value) return
    const name = domainName.trim().toLowerCase()
    if (!name) {
      dnsInfo.value = 'Enter a domain such as studio.online.'
      return
    }
    dnsInfo.value = 'Adding…'
    try {
      const { data } = await customersApi.attachEnvCustomDomain(activeEnv.value.id, name)
      dnsData.value = mapDns(data, name)
      dnsInfo.value = ''
      const refreshed = await customersApi.dashboard()
      dash.value = refreshed.data
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not add that domain.'
      dnsInfo.value = msg
      if (dnsData.value) dnsData.value = { ...dnsData.value, error: msg }
    }
  }

  async function unassignCustomDomain(domainName: string) {
    if (!activeEnv.value) return
    const name = domainName.trim().toLowerCase()
    if (!name) return
    dnsInfo.value = 'Unassigning…'
    try {
      const { data } = await customersApi.unassignEnvCustomDomain(activeEnv.value.id, name)
      dnsData.value = mapDns(data, data.domain || activeEnv.value.domain)
      dnsInfo.value = ''
      const refreshed = await customersApi.dashboard()
      dash.value = refreshed.data
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      const msg = err.response?.data?.error?.message ?? 'Could not unassign that domain.'
      dnsInfo.value = msg
      if (dnsData.value) dnsData.value = { ...dnsData.value, error: msg }
    }
  }

  async function loadMonitoring() {
    if (!activeEnv.value) return
    monitoringMsg.value = 'Loading…'
    monitoringSnapshot.value = null
    try {
      const { data } = await customersApi.getEnvMonitoring(activeEnv.value.id)
      monitoringSnapshot.value = data
      monitoringMsg.value = ''
      if (data.disk?.pct != null) usagePct.value = Number(data.disk.pct) || 0
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      monitoringMsg.value = err.response?.data?.error?.message ?? 'Could not load monitoring.'
    }
  }

  async function loadUsage(opts?: { quiet?: boolean }) {
    if (!activeEnv.value) return
    if (!opts?.quiet) {
      usageInfo.value = 'Loading…'
      usageStatus.value = ''
      usagePct.value = 0
    }
    try {
      const { data } = await customersApi.getEnvUsage(activeEnv.value.id)
      usageSnapshot.value = data
      usagePct.value = Number(data.storage_pct) || 0
      const cpuBit =
        data.cpu_usage_vcpu != null
          ? `${Number(data.cpu_usage_vcpu).toFixed(2)} / ${formatCpu(data.cpu_limit)} vCPU`
          : `${formatCpu(data.cpu_limit)} vCPU`
      const memBit =
        data.memory_usage_mb != null && data.memory_limit_mb != null
          ? `${Math.round(data.memory_usage_mb)} / ${Math.round(data.memory_limit_mb)} MB RAM`
          : `${formatRamGb(data.ram_limit_gb)} RAM`
      const procBit =
        data.process_count != null
          ? ` · ${data.process_count}${data.process_limit != null ? ` / ${data.process_limit}` : ''} processes`
          : ''
      usageInfo.value = `${cpuBit} · ${memBit} · disk ${data.storage_used_gb} / ${data.storage_limit_gb} GB · ${data.file_count} files${procBit}`
      if (data.message) usageInfo.value += ` — ${data.message}`
      usageStatus.value =
        data.storage_status === 'over' || data.hard_exceeded
          ? 'over'
          : data.storage_status === 'warning' || data.soft_warning
            ? 'warning'
            : 'ok'
      if (!usagePollTimer) startUsagePoll()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      if (!opts?.quiet) {
        usageInfo.value = err.response?.data?.error?.message ?? 'Could not load usage.'
        usageStatus.value = ''
        usageSnapshot.value = null
      }
    }
  }

  async function checkHealth(envId?: string) {
    const id = envId || activeEnv.value?.id
    if (!id) return
    healthInfo.value = 'Checking…'
    try {
      const { data } = await customersApi.checkEnvHealth(id)
      healthInfo.value = data.summary || healthLabel(data.health_status)
      if (dash.value) {
        const env = dash.value.environments.find((e) => e.id === id)
        if (env) env.health_status = data.health_status
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      healthInfo.value = err.response?.data?.error?.message ?? 'Health check failed.'
    }
  }

  async function issueSsl() {
    if (!activeEnv.value) return
    sslMsg.value = 'Turning on secure HTTPS…'
    try {
      const { data } = await customersApi.issueEnvSsl(activeEnv.value.id)
      sslMsg.value =
        data.message ||
        (data.queued
          ? 'Working on it — HTTPS will be ready shortly after your domain points here.'
          : data.success
            ? 'HTTPS is on. Your site is secured.'
            : 'Could not turn on HTTPS yet. Check that your domain points here first.')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      sslMsg.value = err.response?.data?.error?.message ?? 'Could not turn on HTTPS.'
    }
  }

  async function loadBackups() {
    if (!activeEnv.value) return
    backupMsg.value = 'Loading…'
    try {
      const { data } = await customersApi.listEnvBackups(activeEnv.value.id)
      backups.value = data
      const pending = data.some((b) => ['pending', 'queued', 'running'].includes(String(b.status)))
      backupMsg.value = data.length
        ? pending
          ? 'Backup in progress — this list refreshes automatically.'
          : ''
        : 'No backups yet.'
      if (pending) scheduleBackupPoll()
      else stopBackupPoll()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      backupMsg.value = err.response?.data?.error?.message ?? 'Could not load backups.'
      stopBackupPoll()
    }
  }

  let backupPollTimer: ReturnType<typeof setTimeout> | null = null
  function stopBackupPoll() {
    if (backupPollTimer) {
      clearTimeout(backupPollTimer)
      backupPollTimer = null
    }
  }
  function scheduleBackupPoll() {
    stopBackupPoll()
    backupPollTimer = setTimeout(() => {
      void loadBackups()
    }, 4000)
  }

  async function createBackup() {
    if (!activeEnv.value) return
    backupMsg.value = 'Queueing backup…'
    try {
      const { data } = await customersApi.createEnvBackup(activeEnv.value.id)
      backupMsg.value = `Backup ${data.status}. Working on your restore point…`
      await loadBackups()
      scheduleBackupPoll()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      backupMsg.value = err.response?.data?.error?.message ?? 'Backup failed.'
    }
  }

  async function restoreBackup(id: string) {
    if (!activeEnv.value) return
    if (!confirm('Restore this backup? Current site files will be replaced.')) return
    backupMsg.value = 'Queueing restore…'
    try {
      const { data } = await customersApi.restoreEnvBackup(activeEnv.value.id, id)
      backupMsg.value = data.message
      scheduleBackupPoll()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      backupMsg.value = err.response?.data?.error?.message ?? 'Restore failed.'
    }
  }

  async function downloadBackup(id: string, filename?: string | null) {
    if (!activeEnv.value) return
    backupMsg.value = 'Preparing download…'
    try {
      const token = localStorage.getItem('access_token')
      const res = await fetch(customersApi.downloadEnvBackupUrl(activeEnv.value.id, id), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) {
        let msg = 'Download failed.'
        try {
          const body = await res.json()
          msg = body?.error?.message || body?.message || msg
        } catch {
          /* ignore */
        }
        backupMsg.value = msg
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || `backup-${id}.tar.gz`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      backupMsg.value = 'Download started.'
    } catch {
      backupMsg.value = 'Download failed.'
    }
  }

  async function deleteBackup(id: string) {
    if (!activeEnv.value) return
    if (!confirm('Delete this backup permanently?')) return
    backupMsg.value = 'Deleting backup…'
    try {
      await customersApi.deleteEnvBackup(activeEnv.value.id, id)
      backupMsg.value = 'Backup deleted.'
      await loadBackups()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      backupMsg.value = err.response?.data?.error?.message ?? 'Could not delete backup.'
    }
  }

  async function loadStacks() {
    if (!activeEnv.value) return
    try {
      const { data } = await customersApi.listEnvStacks(activeEnv.value.id)
      stacks.value = data.stacks
      currentStack.value = data.current || null
      if (data.current?.stack && !selectedStack.value) {
        selectedStack.value = String(data.current.stack)
      } else if (!selectedStack.value && stacks.value[0]) {
        selectedStack.value = stacks.value[0].id
      }

      const progress = data.progress
      const status = String(progress?.status || '').toLowerCase()

      if (progress && ['queued', 'running'].includes(status)) {
        stackProgress.value = progress
        stackOutcome.value = 'running'
        stackBusy.value = true
        applyStackProgress(progress)
        const jobId = data.active_job_id || progress.job_id
        if (jobId && !stackPollTimer) startStackPoll(activeEnv.value.id, String(jobId))
        return
      }

      if (progress && status === 'failed') {
        stackProgress.value = progress
        stackOutcome.value = 'error'
        stackBusy.value = false
        stackMsg.value = String(progress.error || progress.message || 'Install failed.')
        return
      }

      if (data.current) {
        stackProgress.value = progress?.status === 'success' ? progress : null
        stackOutcome.value = 'success'
        stackBusy.value = false
        stackMsg.value = String(
          data.current.message ||
            progress?.message ||
            `${data.current.stack_name || data.current.stack || 'Stack'} is installed on this site.`,
        )
        return
      }

      if (!stackBusy.value) {
        stackOutcome.value = 'idle'
        stackProgress.value = null
        stackMsg.value = ''
      }
    } catch {
      stacks.value = [
        { id: 'static', name: 'Static site', description: 'HTML starter' },
        { id: 'wordpress', name: 'WordPress', description: 'WordPress + MySQL' },
        { id: 'laravel', name: 'Laravel', description: 'Laravel via Composer' },
        { id: 'nodejs', name: 'Node.js', description: 'Express app' },
      ]
    }
  }

  async function loadAppCatalog() {
    if (!activeEnv.value) return
    try {
      const { data } = await customersApi.listEnvApplicationCatalog(activeEnv.value.id)
      appCatalog.value = data
      const current = String(newAppFramework.value || '').toLowerCase()
      const known = new Set(data.map((f) => String(f.id || '').toLowerCase()))
      if (!known.has(current)) {
        const firstPython = data.find((f) =>
          ['python', 'fastapi', 'flask', 'django'].includes(String(f.id || '').toLowerCase()) && f.allowed,
        )
        newAppFramework.value = firstPython?.id || 'fastapi'
      }

      const fw = newAppFramework.value
      if (fw && !newAppRuntimeVersion.value) {
        const hit = data.find((f) => f.id === fw)
        const isPhp = ['php', 'laravel', 'wordpress'].includes(String(fw).toLowerCase())
        const isNode = ['nodejs', 'express', 'react', 'vue'].includes(String(fw).toLowerCase())
        const versions = hit?.runtime_versions?.length
          ? hit.runtime_versions
          : isPhp
            ? ['8.1', '8.2', '8.3']
            : isNode
              ? ['18', '20', '22']
              : ['3.9', '3.10', '3.11', '3.12', '3.13']
        const preferred = isPhp ? '8.3' : isNode ? '20' : '3.12'
        newAppRuntimeVersion.value = versions.includes(preferred) ? preferred : versions[0] ?? preferred
      }
    } catch {
      appCatalog.value = []
      newAppRuntimeVersion.value = null
    }
  }

  async function loadApplications() {
    if (!activeEnv.value) return
    try {
      const { data } = await customersApi.listEnvApplications(activeEnv.value.id)
      applications.value = data
    } catch {
      applications.value = []
    }
  }

  async function createApplication() {
    if (!activeEnv.value) {
      appMsg.value = 'No hosting site selected.'
      return
    }
    if (newAppRootPlacement.value !== 'public_html' && !newAppName.value.trim()) {
      appMsg.value = 'Enter an application name first.'
      return
    }
    appBusy.value = true
    appMsg.value = ''
    let startCommand: string | undefined = undefined
    if (newAppFramework.value === 'python' || newAppFramework.value === 'fastapi') {
      const mod = newAppPythonModule.value.trim()
      const obj = newAppPythonObject.value.trim()
      if (mod || obj) {
        const modOk = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(mod)
        const objOk = /^[A-Za-z_][A-Za-z0-9_]*$/.test(obj)
        if (!modOk || !objOk) {
          appMsg.value = 'Invalid ASGI entry. Use module like `app.main` and object like `app`, or leave blank to auto-detect.'
          appBusy.value = false
          return
        }
        startCommand = `gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} ${mod}:${obj}`
      }
      // Blank entry → backend auto-detects from uploaded project (or scaffolds a stub).
    } else if (newAppFramework.value === 'django') {
      const mod = (newAppPythonModule.value.trim() || '').replace(/\.py$/, '')
      const obj = newAppPythonObject.value.trim()
      if (mod || obj) {
        const m = mod || 'config.wsgi'
        const o = obj || 'application'
        const modOk = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(m)
        const objOk = /^[A-Za-z_][A-Za-z0-9_]*$/.test(o)
        if (!modOk || !objOk) {
          appMsg.value = 'Invalid WSGI entry. Use module like `config.wsgi` and object like `application`, or leave blank to auto-detect.'
          appBusy.value = false
          return
        }
        startCommand = `gunicorn -b 127.0.0.1:{port} ${m}:${o}`
      }
    } else if (newAppFramework.value === 'flask') {
      const mod = newAppPythonModule.value.trim()
      const obj = newAppPythonObject.value.trim()
      if (mod || obj) {
        startCommand = `gunicorn -b 127.0.0.1:{port} ${mod || 'app'}:${obj || 'app'}`
      }
    }
    const placement = newAppRootPlacement.value
    const serveAtDomain = placement === 'public_html' || newAppServeAtDomain.value
    const appName =
      placement === 'public_html'
        ? newAppName.value.trim() || activeEnv.value.domain || 'website'
        : newAppName.value.trim()
    if (!appName) {
      appMsg.value = 'Enter an application name first.'
      appBusy.value = false
      return
    }
    const homeLabel = activeEnv.value.hosting_name || 'user'
    const fw = String(newAppFramework.value || '').toLowerCase()
    const isPythonApp = ['python', 'fastapi', 'django', 'flask'].includes(fw)
    const isPhpApp = ['php', 'laravel'].includes(fw)
    const logPath =
      newAppLogPath.value.trim() ||
      (isPythonApp ? `/home3/${homeLabel}/logs/passenger.log` : undefined)
    try {
      const { data } = await customersApi.createEnvApplication(activeEnv.value.id, {
        name: appName,
        framework: newAppFramework.value,
        runtime_version: newAppRuntimeVersion.value || undefined,
        start_command: isPhpApp ? undefined : startCommand,
        root_placement: placement,
        serve_at_domain: serveAtDomain,
        log_path: isPhpApp ? undefined : logPath || undefined,
        env_vars: envVarsToRecord(newAppEnvVars.value),
      })
      newAppName.value = ''
      newAppLogPath.value = ''
      newAppEnvVars.value = []
      showAppCreateForm.value = false
      await loadApplications()
      if (data.id) {
        try {
          const deployed = await customersApi.deployEnvApplication(activeEnv.value.id, data.id)
          appMsg.value = deployed.data.message || data.message || 'Application created.'
          await loadApplications()
        } catch (deployErr: unknown) {
          const err = deployErr as { response?: { data?: { error?: { message?: string }; message?: string } } }
          appMsg.value =
            err.response?.data?.error?.message ||
            err.response?.data?.message ||
            'Application created. Use Deploy if it did not start.'
        }
      } else {
        appMsg.value = data.message || 'Application created.'
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      appMsg.value = err.response?.data?.error?.message ?? 'Could not create application.'
    } finally {
      appBusy.value = false
    }
  }

  async function deployApplication(id: string) {
    if (!activeEnv.value) return
    appBusy.value = true
    appMsg.value = ''
    try {
      const { data } = await customersApi.deployEnvApplication(activeEnv.value.id, id)
      appMsg.value = data.message || 'Deployed.'
      await loadApplications()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } } }
      appMsg.value = err.response?.data?.message ?? 'Deploy failed.'
    } finally {
      appBusy.value = false
    }
  }

  async function restartApplication(id: string) {
    if (!activeEnv.value) return
    appBusy.value = true
    appMsg.value = ''
    try {
      const { data } = await customersApi.restartEnvApplication(activeEnv.value.id, id)
      appMsg.value = data.message || 'Restarted.'
      await loadApplications()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string }; message?: string } } }
      appMsg.value = err.response?.data?.error?.message || err.response?.data?.message || 'Restart failed.'
    } finally {
      appBusy.value = false
    }
  }

  async function stopApplication(id: string) {
    if (!activeEnv.value) return
    appBusy.value = true
    appMsg.value = ''
    try {
      const { data } = await customersApi.stopEnvApplication(activeEnv.value.id, id)
      appMsg.value = data.message || 'Stopped.'
      await loadApplications()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string }; message?: string } } }
      appMsg.value = err.response?.data?.error?.message || err.response?.data?.message || 'Stop failed.'
    } finally {
      appBusy.value = false
    }
  }

  async function startApplication(id: string) {
    if (!activeEnv.value) return
    appBusy.value = true
    appMsg.value = ''
    try {
      const { data } = await customersApi.startEnvApplication(activeEnv.value.id, id)
      appMsg.value = data.message || 'Started.'
      await loadApplications()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string }; message?: string } } }
      appMsg.value = err.response?.data?.error?.message || err.response?.data?.message || 'Start failed.'
    } finally {
      appBusy.value = false
    }
  }

  async function refreshApplication(id: string) {
    if (!activeEnv.value) return
    appBusy.value = true
    appMsg.value = ''
    try {
      const { data } = await customersApi.refreshEnvApplication(activeEnv.value.id, id)
      appMsg.value = data.message || 'Status refreshed.'
      await loadApplications()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string }; message?: string } } }
      appMsg.value = err.response?.data?.error?.message || err.response?.data?.message || 'Refresh failed.'
      await loadApplications()
    } finally {
      appBusy.value = false
    }
  }

  function parseStartCommand(cmd: string | null | undefined): { module: string; object: string } {
    const raw = String(cmd || '').trim()
    const m = raw.match(/([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z_][A-Za-z0-9_]*)\s*$/)
    if (m) return { module: m[1], object: m[2] }
    return { module: 'app.main', object: 'app' }
  }

  function beginEditApplication(id: string) {
    const app = applications.value.find((a) => a.id === id)
    if (!app) return
    editingAppId.value = id
    editAppName.value = app.name || ''
    editAppLogPath.value = app.log_path || ''
    editAppServeAtDomain.value = Boolean(app.uses_site_root)
    editAppRuntimeVersion.value = app.runtime_version || null
    // Keys only from API — leave values blank so secrets are not echoed; user re-enters to change.
    editAppEnvVars.value = (app.env_var_keys || []).map((key) => ({ key, value: '' }))
    editEnvVarsDirty.value = false
    const parsed = parseStartCommand((app as { start_command?: string }).start_command)
    if (String(app.framework || '').toLowerCase() === 'django') {
      editAppPythonModule.value = parsed.module === 'app.main' ? 'config.wsgi' : parsed.module
      editAppPythonObject.value = parsed.object === 'app' ? 'application' : parsed.object
    } else {
      editAppPythonModule.value = parsed.module
      editAppPythonObject.value = parsed.object
    }
    showAppCreateForm.value = false
  }

  function cancelEditApplication() {
    editingAppId.value = null
    editAppEnvVars.value = []
    editEnvVarsDirty.value = false
  }

  async function saveEditApplication() {
    if (!activeEnv.value || !editingAppId.value) return
    const app = applications.value.find((a) => a.id === editingAppId.value)
    if (!app) return
    appBusy.value = true
    appMsg.value = ''
    const fw = String(app.framework || '').toLowerCase()
    const isPhp = ['php', 'laravel'].includes(fw) || String(app.runtime || '').toLowerCase() === 'php'
    let startCommand: string | undefined
    if (['python', 'fastapi', 'django', 'flask'].includes(fw)) {
      const mod = editAppPythonModule.value.trim()
      const obj = editAppPythonObject.value.trim()
      const modOk = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(mod)
      const objOk = /^[A-Za-z_][A-Za-z0-9_]*$/.test(obj)
      if (!modOk || !objOk) {
        appMsg.value = 'Invalid startup entry for this application.'
        appBusy.value = false
        return
      }
      startCommand =
        fw === 'fastapi' || fw === 'python'
          ? `gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} ${mod}:${obj}`
          : `gunicorn -b 127.0.0.1:{port} ${mod}:${obj}`
    } else if (isPhp) {
      startCommand = ''
    }
    try {
      const { data } = await customersApi.updateEnvApplication(activeEnv.value.id, editingAppId.value, {
        name: editAppName.value.trim() || undefined,
        runtime_version: editAppRuntimeVersion.value || undefined,
        start_command: startCommand,
        log_path: isPhp ? undefined : editAppLogPath.value.trim() || undefined,
        serve_at_domain: editAppServeAtDomain.value,
        // Only replace env when the user edited the variables section (avoids wiping secrets).
        env_vars: editEnvVarsDirty.value ? envVarsToRecord(editAppEnvVars.value) : undefined,
        restart: !isPhp,
      })
      appMsg.value = data.message || 'Application updated.'
      editingAppId.value = null
      editAppEnvVars.value = []
      editEnvVarsDirty.value = false
      await loadApplications()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string }; message?: string } } }
      appMsg.value = err.response?.data?.error?.message || err.response?.data?.message || 'Update failed.'
    } finally {
      appBusy.value = false
    }
  }

  async function deleteApplication(id: string) {
    if (!activeEnv.value || !confirm('Delete this application?')) return
    appBusy.value = true
    try {
      await customersApi.deleteEnvApplication(activeEnv.value.id, id)
      appMsg.value = 'Application removed.'
      await loadApplications()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      appMsg.value = err.response?.data?.error?.message ?? 'Delete failed.'
    } finally {
      appBusy.value = false
    }
  }

  async function installStack() {
    if (!activeEnv.value || !selectedStack.value) return
    const pick = stacks.value.find((s) => s.id === selectedStack.value)
    if (pick && pick.one_click === false) {
      stackMsg.value =
        `${pick.name} is included on your pack — deploy it with Files or Git. One-click install is only for Static/PHP, WordPress, Laravel, and Node.js for now.`
      return
    }
    const needsReplace = Boolean(currentStack.value) || fileEntries.value.length > 1
    if (needsReplace && !confirm('Replace existing site files with this stack?')) return
    stopStackPoll()
    stackBusy.value = true
    stackOutcome.value = 'running'
    stackMsg.value = 'Starting install…'
    stackProgress.value = {
      status: 'queued',
      stack: selectedStack.value,
      step: 'prepare',
      label: 'Starting install…',
      percent: 2,
      steps: [],
    }
    try {
      const { data } = await customersApi.installEnvStack(activeEnv.value.id, {
        stack: selectedStack.value,
        replace: true,
      })
      applyStackProgress(data.progress, data.message)
      if (!data.queued) {
        stackBusy.value = false
        stackOutcome.value = 'success'
        stackMsg.value = data.message || 'Stack installed successfully.'
        currentStack.value = data.current || data.result || null
        await loadFiles()
        await loadStacks()
        return
      }
      if (data.job_id) {
        startStackPoll(activeEnv.value.id, data.job_id)
      } else {
        stackBusy.value = false
        stackOutcome.value = 'error'
        stackMsg.value = 'Install was queued but no job id was returned.'
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      stackBusy.value = false
      stackOutcome.value = 'error'
      stackMsg.value = err.response?.data?.error?.message ?? 'Install failed.'
      if (stackProgress.value) {
        stackProgress.value = {
          ...stackProgress.value,
          status: 'failed',
          error: stackMsg.value,
          label: 'Install failed',
        }
      }
    }
  }

  async function clearStack(dropDatabase = false) {
    if (!activeEnv.value) return
    stopStackPoll()
    stackBusy.value = true
    stackMsg.value = 'Clearing installation…'
    try {
      const { data } = await customersApi.clearEnvStack(activeEnv.value.id, {
        drop_database: Boolean(dropDatabase),
      })
      currentStack.value = null
      stackProgress.value = null
      stackOutcome.value = 'idle'
      stackMsg.value = data.message || 'Installation cleared.'
      await loadFiles()
      await loadStacks()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      stackOutcome.value = 'error'
      stackMsg.value = err.response?.data?.error?.message ?? 'Could not clear installation.'
    } finally {
      stackBusy.value = false
    }
  }

  async function loadLogs() {
    if (!activeEnv.value) return
    logBusy.value = true
    logMsg.value = ''
    try {
      const { data } = await customersApi.listEnvLogs(activeEnv.value.id)
      logEntries.value = data.entries || []
      logMsg.value = data.message || ''
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      logMsg.value = err.response?.data?.error?.message ?? 'Could not load logs.'
    } finally {
      logBusy.value = false
    }
  }

  async function loadCron() {
    if (!activeEnv.value) return
    try {
      const { data } = await customersApi.listEnvCron(activeEnv.value.id)
      cronJobs.value = data.jobs
      cronLimits.value = {
        max_jobs: data.max_jobs ?? 10,
        min_interval_minutes: data.min_interval_minutes ?? 5,
        jobs_used: data.jobs_used ?? data.jobs.length,
        runs_as: data.runs_as,
        note: data.note,
      }
      if (data.min_interval_minutes && data.min_interval_minutes >= 15) {
        cronSchedule.value = `*/${data.min_interval_minutes} * * * *`
      }
    } catch {
      cronJobs.value = []
      cronLimits.value = null
    }
  }

  async function addCron() {
    if (!activeEnv.value) return
    cronBusy.value = true
    cronMsg.value = ''
    try {
      await customersApi.createEnvCron(activeEnv.value.id, {
        schedule: cronSchedule.value,
        command: cronCommand.value,
        enabled: true,
      })
      cronMsg.value = 'Cron job added.'
      await loadCron()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      cronMsg.value = err.response?.data?.error?.message ?? 'Could not add cron job.'
    } finally {
      cronBusy.value = false
    }
  }

  async function toggleCron(job: { id: string; enabled: boolean }) {
    if (!activeEnv.value) return
    try {
      await customersApi.updateEnvCron(activeEnv.value.id, job.id, { enabled: !job.enabled })
      await loadCron()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      cronMsg.value = err.response?.data?.error?.message ?? 'Update failed.'
    }
  }

  async function runCron(jobId: string) {
    if (!activeEnv.value) return
    cronMsg.value = 'Running…'
    try {
      const { data } = await customersApi.runEnvCron(activeEnv.value.id, jobId)
      cronMsg.value = `Last run: ${data.last_status || 'done'}${data.last_output ? ` — ${data.last_output.slice(0, 120)}` : ''}`
      await loadCron()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      cronMsg.value = err.response?.data?.error?.message ?? 'Run failed.'
    }
  }

  async function deleteCron(jobId: string) {
    if (!activeEnv.value) return
    if (!confirm('Delete this cron job?')) return
    try {
      await customersApi.deleteEnvCron(activeEnv.value.id, jobId)
      await loadCron()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      cronMsg.value = err.response?.data?.error?.message ?? 'Delete failed.'
    }
  }

  async function loadGitStatus() {
    if (!activeEnv.value) return
    gitBusy.value = true
    try {
      const { data } = await customersApi.getEnvGit(activeEnv.value.id)
      gitStatus.value = data
      if (!gitRepoPath.value) {
        gitRepoPath.value = `${data.home_display || '/home3/user'}/`
      }
      if (data.message && !gitMsg.value) {
        gitMsg.value = data.message
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      gitMsg.value = err.response?.data?.error?.message ?? 'Could not check Git status.'
    } finally {
      gitBusy.value = false
    }
  }

  async function cloneGitRepo() {
    if (!activeEnv.value) return
    if (gitCloneRemote.value && !gitCloneUrl.value.trim()) {
      gitMsg.value = 'Enter a clone URL.'
      return
    }
    gitBusy.value = true
    gitMsg.value = gitCloneRemote.value ? 'Cloning repository…' : 'Creating repository…'
    try {
      const { data } = await customersApi.cloneEnvGit(activeEnv.value.id, {
        repo_url: gitCloneRemote.value ? gitCloneUrl.value.trim() : undefined,
        branch: gitCloneBranch.value.trim() || undefined,
        name: gitRepoName.value.trim() || undefined,
        repo_path: gitRepoPath.value.trim() || undefined,
        clone: gitCloneRemote.value,
        serve_as_website: gitServeAsWebsite.value,
      })
      gitMsg.value = data.message || (gitCloneRemote.value ? 'Repository cloned.' : 'Repository created.')
      gitCloneUrl.value = ''
      gitCloneBranch.value = ''
      gitRepoName.value = ''
      await loadGitStatus()
      await loadFiles()
      if (!gitCreateAnother.value) gitView.value = 'list'
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      gitMsg.value = err.response?.data?.error?.message ?? 'Git clone failed.'
    } finally {
      gitBusy.value = false
    }
  }

  async function activateGitWebsite(repoPath: string) {
    if (!activeEnv.value || !repoPath) return
    gitBusy.value = true
    gitMsg.value = 'Pointing the website at this folder…'
    try {
      const { data } = await customersApi.activateEnvGit(activeEnv.value.id, { repo_path: repoPath })
      gitMsg.value = data.message || 'Website document root updated.'
      await loadGitStatus()
      await loadFiles()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      gitMsg.value = err.response?.data?.error?.message ?? 'Could not activate website for this path.'
    } finally {
      gitBusy.value = false
    }
  }

  async function pullGitRepo(repoPath?: string) {
    if (!activeEnv.value) return
    gitBusy.value = true
    gitMsg.value = 'Pulling latest commits from remote…'
    try {
      const { data } = await customersApi.pullEnvGit(activeEnv.value.id, {
        repo_path: repoPath || undefined,
      })
      gitMsg.value = data.message || 'Pulled latest commits successfully.'
      await loadGitStatus()
      await loadFiles()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      gitMsg.value = err.response?.data?.error?.message ?? 'Git pull failed.'
    } finally {
      gitBusy.value = false
    }
  }

  async function loadGitHistory(repoPath: string) {
    if (!activeEnv.value) return
    gitBusy.value = true
    try {
      const { data } = await customersApi.gitEnvHistory(activeEnv.value.id, { repo_path: repoPath })
      gitHistory.value = data.commits || []
      gitHistoryPath.value = data.path_display || repoPath
      gitView.value = 'history'
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      gitMsg.value = err.response?.data?.error?.message ?? 'Could not load history.'
    } finally {
      gitBusy.value = false
    }
  }

  async function removeGitRepo(repoPath: string) {
    if (!activeEnv.value) return
    if (!confirm('Remove this repository from Git Version Control? Site files are kept unless this is a dedicated clone folder.')) return
    gitBusy.value = true
    try {
      const { data } = await customersApi.removeEnvGit(activeEnv.value.id, {
        repo_path: repoPath,
        delete_files: false,
      })
      gitMsg.value = data.message || 'Repository removed.'
      gitExpandedId.value = null
      await loadGitStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      gitMsg.value = err.response?.data?.error?.message ?? 'Could not remove repository.'
    } finally {
      gitBusy.value = false
    }
  }

  function resetToolState() {
    filePath.value = '.'
    editingFile.value = ''
    fileContent.value = ''
    dbInfo.value = ''
    dbCreds.value = null
    dbList.value = []
    selectedDbId.value = ''
    dbActionMsg.value = ''
    dbSchema.value = null
    dbRows.value = null
    gitStatus.value = null
    gitMsg.value = ''
    gitCloneUrl.value = ''
    gitCloneBranch.value = ''
    gitView.value = 'list'
    gitRepoName.value = ''
    gitExpandedId.value = null
    gitHistory.value = []
    ftpInfo.value = ''
    ftpCreds.value = null
    sftpInfo.value = ''
    sftpCreds.value = null
    sftpKeyInput.value = ''
    sftpKeyName.value = ''
    sshCreds.value = null
    usageInfo.value = ''
    usageSnapshot.value = null
    dnsInfo.value = ''
    dnsData.value = null
    sslMsg.value = ''
    backupMsg.value = ''
    stackMsg.value = ''
    backups.value = []
    stopBackupPoll()
    logEntries.value = []
    logMsg.value = ''
  }

  async function hydrateActiveEnv() {
    if (!activeEnv.value) return
    await Promise.allSettled([loadFiles(), loadUsage(), loadMonitoring(), loadStacks(), loadCron(), loadSsh(), checkHealth()])
  }

  async function selectEnv(id: string) {
    const lock = lockedEnvId.value
    if (lock && id !== lock) return
    activeEnvId.value = id
    resetToolState()
    await hydrateActiveEnv()
  }

  /** Sync activeEnvId from a known environment (e.g. route param or query). */
  function setActiveEnvId(id: string) {
    const lock = lockedEnvId.value
    if (lock && id && id !== lock) return
    if (lock) {
      activeEnvId.value = lock
      return
    }
    activeEnvId.value = id
  }

  return {
    activeEnvId,
    activeEnv,
    dbCanWrite,
    filePath,
    fileEntries,
    fileContent,
    editingFile,
    fileMsg,
    dbInfo,
    dbCreds,
    dbSchema,
    dbRows,
    dbStudioBusy,
    dbStudioMsg,
    dbSelectedTable,
    dbRowOffset,
    dbSql,
    dbList,
    selectedDbId,
    dbBusy,
    dbActionMsg,
    newDbEngine,
    newDbName,
    newDbUser,
    newDbPassword,
    gitStatus,
    gitBusy,
    gitMsg,
    gitCloneUrl,
    gitCloneBranch,
    gitView,
    gitCloneRemote,
    gitRepoName,
    gitRepoPath,
    gitCreateAnother,
    gitServeAsWebsite,
    gitExpandedId,
    gitSearch,
    gitHistory,
    gitHistoryPath,
    loadGitStatus,
    cloneGitRepo,
    activateGitWebsite,
    pullGitRepo,
    loadGitHistory,
    removeGitRepo,
    ftpInfo,
    ftpCreds,
    sftpCreds,
    sftpInfo,
    sftpKeyInput,
    sftpKeyName,
    sshCreds,
    usageInfo,
    logEntries,
    logMsg,
    logBusy,
    usageStatus,
    usagePct,
    usageSnapshot,
    monitoringSnapshot,
    monitoringMsg,
    healthInfo,
    dnsInfo,
    dnsData,
    sslMsg,
    backups,
    backupMsg,
    stackMsg,
    stackBusy,
    stackProgress,
    stackJobId,
    stackOutcome,
    selectedStack,
    stacks,
    currentStack,
    cronJobs,
    cronSchedule,
    cronCommand,
    cronMsg,
    cronBusy,
    cronLimits,
    appCatalog,
    applications,
    appMsg,
    appBusy,
    newAppName,
    newAppFramework,
    newAppRuntimeVersion,
    newAppGitUrl,
    newAppPythonModule,
    newAppPythonObject,
    newAppRootPlacement,
    newAppServeAtDomain,
    newAppLogPath,
    showAppCreateForm,
    editingAppId,
    editAppName,
    editAppLogPath,
    editAppPythonModule,
    editAppPythonObject,
    editAppServeAtDomain,
    editAppRuntimeVersion,
    editAppEnvVars,
    newAppEnvVars,
    addEnvVarRow,
    removeEnvVarRow,
    updateEnvVarRow,
    beginEditApplication,
    cancelEditApplication,
    saveEditApplication,
    setActiveEnvId,
    selectEnv,
    hydrateActiveEnv,
    loadFiles,
    openEntry,
    goUp,
    saveFile,
    loadDb,
    loadDbList,
    loadDbSchema,
    loadDbRows,
    runDbQuery,
    createDatabase,
    deleteDatabase,
    resetDbPassword,
    selectDatabase,
    importDatabaseSql,
    backupDatabase,
    loadFtp,
    loadSftp,
    ensureSftp,
    addSftpKey,
    removeSftpKey,
    setSftpKeyInput,
    setSftpKeyName,
    loadSsh,
    ensureSsh,
    ensureFtp,
    repairFs,
    loadDns,
    ensureDns,
    attachCustomDomain,
    unassignCustomDomain,
    loadUsage,
    loadMonitoring,
    checkHealth,
    issueSsl,
    loadBackups,
    createBackup,
    restoreBackup,
    downloadBackup,
    deleteBackup,
    loadStacks,
    loadAppCatalog,
    loadApplications,
    createApplication,
    deployApplication,
    restartApplication,
    stopApplication,
    startApplication,
    refreshApplication,
    deleteApplication,
    installStack,
    clearStack,
    loadLogs,
    loadCron,
    addCron,
    toggleCron,
    runCron,
    deleteCron,
  }
}

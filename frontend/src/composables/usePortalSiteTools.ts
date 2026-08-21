import { computed, onUnmounted, ref, toValue, type MaybeRefOrGetter, type Ref } from 'vue'
import { customersApi } from '@/api'
import type { CustomerDashboard } from '@/types/platform'
import type { DbQueryResult, DbSchema } from '@/types/databases'
import { formatCpu, formatRamGb } from '@/lib/planResources'

export type PortalSiteTab = 'files' | 'stack' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail' | ''

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
  const healthInfo = ref('')
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
    message?: string
    namecheap?: boolean
    includedHostname?: boolean
    nsLive?: boolean | null
    resolves?: boolean | null
    sslReady?: boolean
    statusSummary?: string
    checklist?: Array<{ id: string; label: string; done: boolean; detail?: string }>
    panelHostname?: string | null
    panelUrl?: string | null
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

  const selectedStack = ref('static')
  const stacks = ref<
    Array<{
      id: string
      name: string
      description: string
      icon?: string
      level?: string
      one_click?: boolean
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
  })

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

  async function loadDb(reveal = true) {
    if (!activeEnv.value) return
    dbInfo.value = 'Loading…'
    try {
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
    await loadSsh()
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
      message?: string
      namecheap_pushed?: boolean
      included_hostname?: boolean
      ns_live?: boolean | null
      resolves?: boolean | null
      ssl_ready?: boolean
      status_summary?: string
      checklist?: Array<{ id: string; label: string; done: boolean; detail?: string }>
      panel_hostname?: string | null
      panel_url?: string | null
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
      ip: '',
      message: data.message,
      namecheap: Boolean(data.namecheap_pushed),
      includedHostname: Boolean(data.included_hostname),
      nsLive: data.ns_live ?? null,
      resolves: data.resolves ?? null,
      sslReady: Boolean(data.ssl_ready),
      statusSummary: data.status_summary || data.message || '',
      checklist: data.checklist || [],
      panelHostname: data.panel_hostname || null,
      panelUrl: data.panel_url || null,
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

  async function loadUsage() {
    if (!activeEnv.value) return
    usageInfo.value = 'Loading…'
    usageStatus.value = ''
    usagePct.value = 0
    try {
      const { data } = await customersApi.getEnvUsage(activeEnv.value.id)
      usagePct.value = Number(data.storage_pct) || 0
      usageInfo.value = `${formatCpu(data.cpu_limit)} vCPU · ${formatRamGb(data.ram_limit_gb)} RAM · disk ${data.storage_used_gb} / ${data.storage_limit_gb} GB · ${data.file_count} files`
      if (data.message) usageInfo.value += ` — ${data.message}`
      usageStatus.value =
        data.storage_status === 'over' || data.hard_exceeded
          ? 'over'
          : data.storage_status === 'warning' || data.soft_warning
            ? 'warning'
            : 'ok'
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      usageInfo.value = err.response?.data?.error?.message ?? 'Could not load usage.'
      usageStatus.value = ''
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
      backupMsg.value = data.length ? '' : 'No backups yet.'
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      backupMsg.value = err.response?.data?.error?.message ?? 'Could not load backups.'
    }
  }

  async function createBackup() {
    if (!activeEnv.value) return
    backupMsg.value = 'Queueing backup…'
    try {
      const { data } = await customersApi.createEnvBackup(activeEnv.value.id)
      backupMsg.value = `Backup ${data.status}. Refresh in a moment.`
      await loadBackups()
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
    } catch (e: unknown) {
      const err = e as { response?: { data?: { error?: { message?: string } } } }
      backupMsg.value = err.response?.data?.error?.message ?? 'Restore failed.'
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
    } catch {
      cronJobs.value = []
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

  function resetToolState() {
    filePath.value = '.'
    editingFile.value = ''
    fileContent.value = ''
    dbInfo.value = ''
    dbCreds.value = null
    dbSchema.value = null
    dbRows.value = null
    ftpInfo.value = ''
    ftpCreds.value = null
    sshCreds.value = null
    usageInfo.value = ''
    dnsInfo.value = ''
    dnsData.value = null
    sslMsg.value = ''
    backupMsg.value = ''
    stackMsg.value = ''
    backups.value = []
    logEntries.value = []
    logMsg.value = ''
  }

  async function hydrateActiveEnv() {
    if (!activeEnv.value) return
    await Promise.allSettled([loadFiles(), loadUsage(), loadStacks(), loadCron(), loadSsh(), checkHealth()])
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
    ftpInfo,
    ftpCreds,
    sshCreds,
    usageInfo,
    logEntries,
    logMsg,
    logBusy,
    usageStatus,
    usagePct,
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
    setActiveEnvId,
    selectEnv,
    hydrateActiveEnv,
    loadFiles,
    openEntry,
    goUp,
    saveFile,
    loadDb,
    loadDbSchema,
    loadDbRows,
    runDbQuery,
    loadFtp,
    loadSsh,
    ensureSsh,
    ensureFtp,
    repairFs,
    loadDns,
    ensureDns,
    attachCustomDomain,
    unassignCustomDomain,
    loadUsage,
    checkHealth,
    issueSsl,
    loadBackups,
    createBackup,
    restoreBackup,
    loadStacks,
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

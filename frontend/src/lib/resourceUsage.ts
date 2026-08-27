/** Threshold helpers for hosting resource meters (Phase E). */

export type ResourceTier = 'ok' | 'warning' | 'high' | 'critical' | 'over'

export type EnvUsageSnapshot = {
  cpu_limit?: number
  ram_limit_gb?: number
  storage_limit_gb?: number
  storage_used_gb?: number
  storage_pct?: number
  file_count?: number
  soft_warning?: boolean
  hard_exceeded?: boolean
  storage_status?: string
  cpu_usage_percent?: number | null
  cpu_usage_vcpu?: number | null
  memory_usage_mb?: number | null
  memory_limit_mb?: number | null
  memory_pct?: number | null
  process_count?: number | null
  process_limit?: number | null
  resources_enforced?: boolean
  resource_slice?: string | null
  metrics_source?: string | null
  metrics_updated_at?: string | null
  resource_statuses?: ResourceStatusBundle | null
  message?: string | null
  note?: string
}

export type ResourceStatusLevel = 'allocated' | 'reported' | 'enforced' | 'monitored'

export type ResourceDimensionStatus = {
  status?: ResourceStatusLevel
  label?: string
  allocated?: boolean
  reported?: boolean
  enforced?: boolean
  limit?: number | string | null
  unit?: string | null
  detail?: string | null
}

export type ResourceStatusBundle = {
  disk?: ResourceDimensionStatus
  cpu?: ResourceDimensionStatus
  memory?: ResourceDimensionStatus
  processes?: ResourceDimensionStatus
  bandwidth?: ResourceDimensionStatus
  resources_enforced?: boolean
  summary?: string
}

export function resourceStatusLabel(
  dim: ResourceDimensionStatus | null | undefined,
): string {
  if (!dim) return 'Allocated'
  return dim.label || dim.status || 'Allocated'
}

export function resourceStatusClass(
  dim: ResourceDimensionStatus | null | undefined,
): string {
  const s = dim?.status || 'allocated'
  if (s === 'enforced') return 'rs-enforced'
  if (s === 'monitored') return 'rs-monitored'
  if (s === 'reported') return 'rs-reported'
  return 'rs-allocated'
}

export function resourceTier(pct: number | null | undefined): ResourceTier {
  if (pct == null || Number.isNaN(pct)) return 'ok'
  if (pct >= 100) return 'over'
  if (pct >= 95) return 'critical'
  if (pct >= 90) return 'high'
  if (pct >= 80) return 'warning'
  return 'ok'
}

/** Map tier → CSS class used by existing `.bar.warning` / `.bar.over` meters. */
export function barClassForTier(tier: ResourceTier): '' | 'warning' | 'over' {
  if (tier === 'over' || tier === 'critical') return 'over'
  if (tier === 'high' || tier === 'warning') return 'warning'
  return ''
}

export function processPct(usage: EnvUsageSnapshot | null | undefined): number | null {
  if (!usage) return null
  const count = usage.process_count
  const limit = usage.process_limit
  if (count == null || limit == null || limit <= 0) return null
  return Math.min(100, (Number(count) / Number(limit)) * 100)
}

export function formatUpdatedAt(iso?: string | null): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

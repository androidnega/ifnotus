import type { HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { planMatrix, sshHeadline, visibleStacks } from '@/lib/planMatrix'

export type PackItem = {
  id: string
  label: string
  detail: string
}

export function customDomainLimit(plan: HostingPlan): number {
  const n = planMatrix(plan).custom_domains
  if (n == null) return 999
  if (Number.isFinite(n)) return Math.max(0, n)
  return Number(plan.price_monthly) > 0 ? 1 : 0
}

/** Public marketing copy — buyer-facing, no internal hostnames. */
export function publicPackItems(plan: HostingPlan): PackItem[] {
  const matrix = planMatrix(plan)
  const domains = customDomainLimit(plan)
  const stacks = visibleStacks(plan)
    .filter((s) => s.level === 'yes')
    .map((s) => s.label)
  const limited = visibleStacks(plan)
    .filter((s) => s.level === 'limited')
    .map((s) => s.label)
  const items: PackItem[] = [
    { id: 'cpu', label: 'CPU', detail: `${formatCpu(plan.cpu_cores)} vCPU` },
    { id: 'ram', label: 'Memory', detail: formatRamGb(plan.ram_gb) },
    { id: 'disk', label: 'Storage', detail: `${plan.storage_gb} GB` },
    { id: 'bw', label: 'Bandwidth', detail: `${plan.bandwidth_tb} TB / month` },
    { id: 'ssl', label: 'HTTPS', detail: 'SSL included' },
    {
      id: 'domains',
      label: 'Domains',
      detail: domains >= 999 ? 'Unlimited professional domains*' : `${domains} professional domain${domains === 1 ? '' : 's'}`,
    },
    { id: 'ssh', label: 'SSH', detail: sshHeadline(plan) },
    { id: 'ftp', label: 'FTP', detail: matrix.sftp === 'no' ? 'Not on this pack' : 'File access included (SFTP coming for entitled plans)' },
    { id: 'stacks', label: 'Included stacks', detail: stacks.slice(0, 8).join(', ') || 'Upgrade for more runtimes' },
  ]
  if (limited.length) {
    items.push({ id: 'limited', label: 'Available with limits', detail: limited.slice(0, 6).join(', ') })
  }
  items.push(
    { id: 'ai', label: 'AI engineer', detail: `${plan.ai_credits} credits / month` },
    { id: 'support', label: 'Support', detail: 'Tickets from your panel' },
  )
  return items.filter((i) => i.detail !== 'Not on this pack')
}

export function packItems(plan: HostingPlan): PackItem[] {
  return publicPackItems(plan)
}

export function packHighlights(plan: HostingPlan): PackItem[] {
  return packItems(plan).slice(0, 6)
}

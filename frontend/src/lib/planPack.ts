import type { HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { planMatrix, sshHeadline, visibleStacks } from '@/lib/planMatrix'

export type PackItem = {
  id: string
  label: string
  detail: string
}

export function customDomainLimit(plan: HostingPlan): number {
  const fromCaps = plan.capabilities?.custom_domains
  if (fromCaps != null && Number.isFinite(Number(fromCaps))) return Math.max(0, Number(fromCaps))
  const fromCard = plan.catalog_card?.domains
  if (fromCard != null && Number.isFinite(Number(fromCard))) return Math.max(0, Number(fromCard))
  const n = planMatrix(plan).custom_domains
  if (n == null) return 999
  if (Number.isFinite(n)) return Math.max(0, n)
  return Number(plan.price_monthly) > 0 ? 1 : 0
}

/** Prefer backend catalog_card highlights; fall back to derived pack items. */
export function publicPackItems(plan: HostingPlan): PackItem[] {
  const card = plan.catalog_card
  if (card?.highlights?.length) {
    const base: PackItem[] = [
      { id: 'cpu', label: 'CPU', detail: `${formatCpu(plan.cpu_cores)} vCPU` },
      { id: 'ram', label: 'Memory', detail: formatRamGb(plan.ram_gb) },
      { id: 'disk', label: 'Storage', detail: `${plan.storage_gb} GB` },
      ...card.highlights.map((h) => ({ id: h.id, label: h.label, detail: h.detail })),
    ]
    if (card.stacks_included?.length) {
      base.push({
        id: 'stacks',
        label: 'Included stacks',
        detail: card.stacks_included.slice(0, 8).join(', '),
      })
    }
    if (card.stacks_limited?.length) {
      base.push({
        id: 'limited',
        label: 'Available with limits',
        detail: card.stacks_limited.slice(0, 6).join(', '),
      })
    }
    if (card.stacks_beta?.length) {
      base.push({
        id: 'beta-stacks',
        label: 'Beta stacks',
        detail: `${card.stacks_beta.slice(0, 8).join(', ')} (verify before customer use)`,
      })
    }
    if (card.product_status === 'beta') {
      base.push({ id: 'status', label: 'Availability', detail: 'Limited beta on shared hosting' })
    }
    if (card.production_notes?.length) {
      base.push({
        id: 'notes',
        label: 'Good to know',
        detail: card.production_notes[0],
      })
    }
    if (card.blurb) {
      base.push({ id: 'blurb', label: 'About', detail: card.blurb })
    }
    return base
  }

  // Legacy path when API has not yet attached catalog_card
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
      detail:
        domains >= 999
          ? 'Unlimited professional domains*'
          : `${domains} professional domain${domains === 1 ? '' : 's'}`,
    },
    { id: 'ssh', label: 'SSH', detail: sshHeadline(plan) },
    {
      id: 'ftp',
      label: 'File transfer',
      detail:
        matrix.sftp === 'no'
          ? 'FTP only on this pack'
          : matrix.sftp === 'limited'
            ? 'FTP included · SFTP beta'
            : 'FTP and SFTP included',
    },
    {
      id: 'stacks',
      label: 'Included stacks',
      detail: stacks.slice(0, 8).join(', ') || 'Upgrade for more runtimes',
    },
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

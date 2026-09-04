/** Format plan RAM stored as GB fraction (0.25 → "256 MB"). */
export function formatRamGb(ramGb: number | string): string {
  const gb = typeof ramGb === 'string' ? Number(ramGb) : ramGb
  if (!Number.isFinite(gb) || gb <= 0) return '—'
  if (gb < 1) {
    const mb = Math.round(gb * 1024)
    return `${mb} MB`
  }
  const nice = Number.isInteger(gb) ? String(gb) : String(Number(gb.toFixed(2)))
  return `${nice} GB`
}

/** Format live/enforced RAM from megabytes (MemoryHigh etc.). */
export function formatRamFromMb(mb: number | string): string {
  const n = typeof mb === 'string' ? Number(mb) : mb
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n >= 1024) {
    const gb = n / 1024
    const nice = Number.isInteger(gb) ? String(gb) : String(Number(gb.toFixed(2)))
    return `${nice} GB`
  }
  return `${Math.round(n)} MB`
}

export function formatCpu(cpu: number | string): string {
  const n = typeof cpu === 'string' ? Number(cpu) : cpu
  if (!Number.isFinite(n) || n <= 0) return '—'
  return Number.isInteger(n) ? `${n}` : String(Number(n.toFixed(2)))
}

/** Convert MB input from staff UI into plan ram_gb. */
export function mbToRamGb(mb: number): number {
  return Math.round((mb / 1024) * 10000) / 10000
}

export function ramGbToMb(ramGb: number | string): number {
  const gb = typeof ramGb === 'string' ? Number(ramGb) : ramGb
  return Math.max(64, Math.round(gb * 1024))
}

const RAM_SNAPS_MB = [
  128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096, 6144, 8192, 12288, 16384, 24576, 32768,
]

function snapRamMb(raw: number): number {
  return RAM_SNAPS_MB.reduce((best, n) => (Math.abs(n - raw) < Math.abs(best - raw) ? n : best))
}

/**
 * Derive resources from monthly GHS price.
 * Anchors: ₵30 → 0.25 vCPU / 256 MB · ₵70 → 0.5 vCPU / 512 MB
 */
export function resourcesFromPrice(priceMonthly: number | string): {
  cpu_cores: number
  ram_gb: number
  ram_mb: number
  storage_gb: number
  bandwidth_tb: number
  ai_credits: number
} {
  const price = Math.max(0, Number(priceMonthly) || 0)
  const cpuRaw = 0.25 + (price - 30) * (0.25 / 40)
  const ramRawMb = 256 + (price - 30) * (256 / 40)
  const cpu = Math.round(Math.max(0.1, Math.min(16, cpuRaw)) * 20) / 20
  const ramMb = snapRamMb(Math.max(128, Math.min(32768, ramRawMb)))
  const storageRaw = 2 + (price - 30) * (2 / 40)
  const storageSnaps = [2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50]
  const storage_gb = storageSnaps.reduce((best, n) =>
    Math.abs(n - Math.max(2, Math.min(50, storageRaw))) < Math.abs(best - Math.max(2, Math.min(50, storageRaw)))
      ? n
      : best,
  )
  return {
    cpu_cores: cpu,
    ram_gb: mbToRamGb(ramMb),
    ram_mb: ramMb,
    storage_gb,
    bandwidth_tb: Math.max(0.5, Math.round((price / 70) * 10) / 10),
    ai_credits: Math.max(5, Math.round(price / 5)),
  }
}

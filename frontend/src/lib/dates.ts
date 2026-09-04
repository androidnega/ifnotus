/** YYYY-MM-DD in local timezone (avoids UTC shift from toISOString). */
export function localDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function monthStartLocal(d = new Date()): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

export function daysAgoLocal(days: number, from = new Date()): Date {
  const d = new Date(from)
  d.setDate(d.getDate() - days)
  return d
}

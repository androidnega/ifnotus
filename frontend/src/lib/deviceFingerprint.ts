/** Lightweight device fingerprint for access tracing (not cryptographic identity). */

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

function canvasSignal(): string {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 120
    canvas.height = 40
    const ctx = canvas.getContext('2d')
    if (!ctx) return 'no-canvas'
    ctx.textBaseline = 'top'
    ctx.font = '14px JetBrains Mono, monospace'
    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, 120, 40)
    ctx.fillStyle = '#10b981'
    ctx.fillText('IFNOTUS', 4, 10)
    return canvas.toDataURL().slice(-64)
  } catch {
    return 'canvas-blocked'
  }
}

export async function getDeviceFingerprint(): Promise<string> {
  const parts = [
    navigator.userAgent,
    navigator.language,
    String(screen.width),
    String(screen.height),
    String(screen.colorDepth),
    String(new Date().getTimezoneOffset()),
    canvasSignal(),
    navigator.hardwareConcurrency?.toString() ?? '',
    (navigator as Navigator & { deviceMemory?: number }).deviceMemory?.toString() ?? '',
  ]
  return sha256Hex(parts.join('|'))
}

/**
 * Web Audio API synthesizer for staff sound notifications.
 * Generates clean, crisp, harmonic bell chimes without relying on external mp3/wav files.
 */

let audioCtx: AudioContext | null = null

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null
  try {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    if (!audioCtx && AudioContextClass) {
      audioCtx = new AudioContextClass()
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      void audioCtx.resume()
    }
    return audioCtx
  } catch {
    return null
  }
}

const SOUND_MUTED_KEY = 'ifnotus_staff_bell_muted'

export function isSoundMuted(): boolean {
  try {
    return localStorage.getItem(SOUND_MUTED_KEY) === '1'
  } catch {
    return false
  }
}

export function setSoundMuted(muted: boolean): void {
  try {
    if (muted) {
      localStorage.setItem(SOUND_MUTED_KEY, '1')
    } else {
      localStorage.removeItem(SOUND_MUTED_KEY)
    }
  } catch {
    /* ignore */
  }
}

/**
 * Plays a pleasant, two-tone crystal harmonic bell chime (880Hz -> 1320Hz)
 * Perfect for new orders, MoMo payment alerts, and billing confirmations.
 */
export function playOrderBell(): void {
  if (isSoundMuted()) return

  const ctx = getAudioContext()
  if (!ctx) return

  try {
    const now = ctx.currentTime

    // Tone 1: High crisp bell ding (880Hz + harmonic overtone at 1760Hz)
    const osc1 = ctx.createOscillator()
    const gain1 = ctx.createGain()
    osc1.type = 'sine'
    osc1.frequency.setValueAtTime(880, now) // A5
    osc1.frequency.exponentialRampToValueAtTime(1320, now + 0.12) // E6

    gain1.gain.setValueAtTime(0.3, now)
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.9)

    osc1.connect(gain1)
    gain1.connect(ctx.destination)
    osc1.start(now)
    osc1.stop(now + 0.95)

    // Tone 2: Harmonic overtone chime (1320Hz -> 1760Hz) starting +150ms
    const osc2 = ctx.createOscillator()
    const gain2 = ctx.createGain()
    osc2.type = 'triangle'
    osc2.frequency.setValueAtTime(1320, now + 0.15)
    osc2.frequency.exponentialRampToValueAtTime(1760, now + 0.28)

    gain2.gain.setValueAtTime(0, now)
    gain2.gain.setValueAtTime(0.25, now + 0.15)
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 1.2)

    osc2.connect(gain2)
    gain2.connect(ctx.destination)
    osc2.start(now + 0.15)
    osc2.stop(now + 1.25)
  } catch (err) {
    console.warn('[Sound] Could not play notification bell:', err)
  }
}

let activeRingInterval: number | null = null
let activeRingTimeout: number | null = null
let ringGainNode: GainNode | null = null

/**
 * Stop any ongoing ticket ringing alert.
 */
export function stopTicketRing(): void {
  if (activeRingInterval !== null) {
    clearInterval(activeRingInterval)
    activeRingInterval = null
  }
  if (activeRingTimeout !== null) {
    clearTimeout(activeRingTimeout)
    activeRingTimeout = null
  }
  if (ringGainNode) {
    try {
      ringGainNode.gain.setValueAtTime(0, ringGainNode.context.currentTime)
    } catch {
      /* ignore */
    }
    ringGainNode = null
  }
}

/**
 * Plays a continuous phone-style alert chime / beep pattern for ~15 seconds.
 * Perfect for incoming support ticket messages requiring immediate agent attention.
 * Can be stopped anytime with `stopTicketRing()`.
 */
export function playTicketRing15s(onStop?: () => void): { stop: () => void } {
  stopTicketRing()

  if (isSoundMuted()) {
    onStop?.()
    return { stop: stopTicketRing }
  }

  const ctx = getAudioContext()
  if (!ctx) {
    onStop?.()
    return { stop: stopTicketRing }
  }

  function playRingBurst() {
    if (!ctx) return
    try {
      const now = ctx.currentTime

      // Master gain for this burst to allow quick silence
      const masterGain = ctx.createGain()
      masterGain.gain.setValueAtTime(0.35, now)
      masterGain.connect(ctx.destination)
      ringGainNode = masterGain

      // Pulse 1: 0.0s to 0.4s
      const osc1a = ctx.createOscillator()
      const osc1b = ctx.createOscillator()
      const gain1 = ctx.createGain()

      osc1a.type = 'sine'
      osc1b.type = 'sine'
      osc1a.frequency.setValueAtTime(784, now) // G5
      osc1b.frequency.setValueAtTime(1046.5, now) // C6

      gain1.gain.setValueAtTime(0, now)
      gain1.gain.linearRampToValueAtTime(0.3, now + 0.04)
      gain1.gain.setValueAtTime(0.3, now + 0.35)
      gain1.gain.linearRampToValueAtTime(0, now + 0.42)

      osc1a.connect(gain1)
      osc1b.connect(gain1)
      gain1.connect(masterGain)

      osc1a.start(now)
      osc1b.start(now)
      osc1a.stop(now + 0.45)
      osc1b.stop(now + 0.45)

      // Pulse 2: 0.5s to 0.9s
      const osc2a = ctx.createOscillator()
      const osc2b = ctx.createOscillator()
      const gain2 = ctx.createGain()

      osc2a.type = 'sine'
      osc2b.type = 'sine'
      osc2a.frequency.setValueAtTime(880, now + 0.5) // A5
      osc2b.frequency.setValueAtTime(1174.66, now + 0.5) // D6

      gain2.gain.setValueAtTime(0, now + 0.5)
      gain2.gain.linearRampToValueAtTime(0.35, now + 0.54)
      gain2.gain.setValueAtTime(0.35, now + 0.85)
      gain2.gain.linearRampToValueAtTime(0, now + 0.92)

      osc2a.connect(gain2)
      osc2b.connect(gain2)
      gain2.connect(masterGain)

      osc2a.start(now + 0.5)
      osc2b.start(now + 0.5)
      osc2a.stop(now + 0.95)
      osc2b.stop(now + 0.95)
    } catch (err) {
      console.warn('[Sound] Ticket ring error:', err)
    }
  }

  // Play immediately
  playRingBurst()

  // Repeat every 1.8 seconds
  activeRingInterval = window.setInterval(() => {
    playRingBurst()
  }, 1800)

  // Automatically shut off after 15 seconds (15,000ms)
  activeRingTimeout = window.setTimeout(() => {
    stopTicketRing()
    onStop?.()
  }, 15000)

  return { stop: stopTicketRing }
}

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

import type { CustomerProfile } from '@/types/platform'

export type ProfileStageId =
  | 'first_name'
  | 'last_name'
  | 'email'
  | 'phone'
  | 'company'
  | 'password'

export type ProfileStageKind = 'required' | 'optional'

export type ProfileStageDef = {
  id: ProfileStageId
  kind: ProfileStageKind
  title: string
  subtitle: string
  placeholder: string
  inputType: 'text' | 'email' | 'tel' | 'password'
  autocomplete: string
  minLength?: number
  required: boolean
}

/** Order of prompts — required first, then soft account enrichment. */
export const PROFILE_STAGE_ORDER: ProfileStageDef[] = [
  {
    id: 'first_name',
    kind: 'required',
    title: 'What should we call you?',
    subtitle: 'Just your first name — takes a second.',
    placeholder: 'First name',
    inputType: 'text',
    autocomplete: 'given-name',
    required: true,
  },
  {
    id: 'last_name',
    kind: 'required',
    title: 'And your family name?',
    subtitle: 'Needed for invoices and student project addresses.',
    placeholder: 'Family name',
    inputType: 'text',
    autocomplete: 'family-name',
    minLength: 2,
    required: true,
  },
  {
    id: 'email',
    kind: 'required',
    title: 'Where should we send updates?',
    subtitle: 'Required before you place a paid order. We’ll use this for receipts and notices.',
    placeholder: 'Email',
    inputType: 'email',
    autocomplete: 'email',
    required: true,
  },
  {
    id: 'phone',
    kind: 'required',
    title: 'Confirm your mobile number',
    subtitle: 'We use this to keep your account secure.',
    placeholder: 'Mobile number',
    inputType: 'tel',
    autocomplete: 'tel',
    required: true,
  },
  {
    id: 'company',
    kind: 'optional',
    title: 'Do you have a company name?',
    subtitle: 'Optional — helpful on invoices. You can skip and add it later in settings.',
    placeholder: 'Company (optional)',
    inputType: 'text',
    autocomplete: 'organization',
    required: false,
  },
  {
    id: 'password',
    kind: 'optional',
    title: 'Set a password for next time',
    subtitle: 'Optional — lets you sign in with email as well as phone. Skip if you prefer OTP only.',
    placeholder: 'Choose a password',
    inputType: 'password',
    autocomplete: 'new-password',
    minLength: 8,
    required: false,
  },
]

const PENDING_EMAIL = '@phone.pending.ifnotus'
const DEFER_PREFIX = 'ifnotus.profile.defer.'

function isPendingEmail(email?: string | null): boolean {
  return (email || '').includes(PENDING_EMAIL)
}

function isPlaceholderName(value?: string | null): boolean {
  const v = (value || '').trim().toLowerCase()
  return !v || v === 'customer' || v === 'new customer'
}

export function profileHasField(profile: CustomerProfile, id: ProfileStageId): boolean {
  switch (id) {
    case 'first_name':
      return !isPlaceholderName(profile.first_name)
    case 'last_name':
      return !isPlaceholderName(profile.last_name) && (profile.last_name || '').trim().length >= 2
    case 'email':
      return Boolean(profile.email?.trim()) && !isPendingEmail(profile.email)
    case 'phone':
      return Boolean((profile.phone || '').trim())
    case 'company':
      return Boolean((profile.company || '').trim())
    case 'password':
      // Backend does not expose password_set — skip sticks in localStorage.
      return isStageDeferred('password')
    default:
      return true
  }
}

export function isStageDeferred(id: ProfileStageId): boolean {
  try {
    return localStorage.getItem(DEFER_PREFIX + id) === '1'
  } catch {
    return false
  }
}

export function deferStage(id: ProfileStageId): void {
  try {
    localStorage.setItem(DEFER_PREFIX + id, '1')
  } catch {
    /* ignore */
  }
}

export function clearDeferredStages(): void {
  for (const stage of PROFILE_STAGE_ORDER) {
    try {
      localStorage.removeItem(DEFER_PREFIX + stage.id)
    } catch {
      /* ignore */
    }
  }
}

/** Stages still needed — dynamic from live profile + optional deferrals. */
export function missingProfileStages(
  profile: CustomerProfile,
  opts: { includeOptional?: boolean } = {},
): ProfileStageDef[] {
  const includeOptional = opts.includeOptional !== false
  const fromApi = new Set(profile.missing_for_order || [])
  return PROFILE_STAGE_ORDER.filter((stage) => {
    if (stage.kind === 'optional' && !includeOptional) return false
    if (stage.kind === 'optional' && isStageDeferred(stage.id)) return false
    if (stage.kind === 'required') {
      // Prefer API missing list when present; fall back to local field checks.
      if (fromApi.size > 0) return fromApi.has(stage.id)
      return !profileHasField(profile, stage.id)
    }
    return !profileHasField(profile, stage.id)
  })
}

export function nextProfileStage(
  profile: CustomerProfile,
  opts: { includeOptional?: boolean } = {},
): ProfileStageDef | null {
  return missingProfileStages(profile, opts)[0] || null
}

export function profileStageProgress(profile: CustomerProfile): {
  done: number
  total: number
  remaining: number
  next: ProfileStageDef | null
  requiredRemaining: number
  complete: boolean
} {
  const required = PROFILE_STAGE_ORDER.filter((s) => s.kind === 'required')
  const requiredDone = required.filter((s) => profileHasField(profile, s.id)).length
  const missing = missingProfileStages(profile, { includeOptional: true })
  const requiredRemaining = missing.filter((s) => s.kind === 'required').length
  return {
    done: requiredDone,
    total: required.length,
    remaining: missing.length,
    next: missing[0] || null,
    requiredRemaining,
    complete: requiredRemaining === 0,
  }
}

export function stagePayload(
  id: ProfileStageId,
  value: string,
): Record<string, string> {
  const trimmed = value.trim()
  switch (id) {
    case 'first_name':
      return { first_name: trimmed }
    case 'last_name':
      return { last_name: trimmed }
    case 'email':
      return { email: trimmed }
    case 'phone':
      return { phone: trimmed }
    case 'company':
      return { company: trimmed }
    case 'password':
      return { password: value }
    default:
      return {}
  }
}

export interface IpBlacklistEntry {
  id: string
  ip_address: string
  reason: string
  failed_attempt_count: number
  blocked_at: string
  blocked_until?: string | null
  is_active: boolean
  unlocked_at?: string | null
  unlocked_by_user_id?: string | null
  unlock_note?: string | null
  last_device_fingerprint?: string | null
  last_user_agent?: string | null
}

export interface AccessAttemptEntry {
  id: string
  attempted_at: string
  ip_address: string
  username_or_email?: string | null
  user_id?: string | null
  event_type: string
  success: boolean
  failure_reason?: string | null
  device_fingerprint?: string | null
  user_agent?: string | null
  request_id?: string | null
}

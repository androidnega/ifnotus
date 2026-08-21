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
  source?: string
}

export interface FirewallRuleEntry {
  id: string
  cidr: string
  action: 'allow' | 'deny' | string
  note?: string | null
  enabled: boolean
  created_by_user_id?: string | null
  created_at: string
  updated_at: string
}

export interface BlockedActionEntry {
  id: string
  action_key: string
  label?: string | null
  reason?: string | null
  enabled: boolean
  created_by_user_id?: string | null
  created_at: string
  updated_at: string
}

export interface SystemActionLogEntry {
  id: string
  occurred_at: string
  actor_user_id?: string | null
  actor_username?: string | null
  source: string
  method: string
  path: string
  action_key?: string | null
  status_code?: number | null
  ip_address?: string | null
  user_agent?: string | null
  request_id?: string | null
  summary?: string | null
  success: boolean
}

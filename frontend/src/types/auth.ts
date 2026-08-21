export interface LoginRequest {
  email: string
  password: string
  device_fingerprint?: string
  totp_code?: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface LoginResponse {
  status: 'ok' | 'challenge_required' | 'totp_required'
  access_token?: string | null
  refresh_token?: string | null
  token_type?: string
  expires_in?: number | null
  challenge_id?: string | null
  ip_address?: string | null
  message?: string | null
}

export interface VerifyDeviceRequest {
  challenge_id: string
  code: string
  device_fingerprint?: string
}

export interface User {
  id: string
  email: string
  username: string
  full_name: string | null
  is_active: boolean
  is_superuser: boolean
  roles: string[]
  permissions: string[]
  last_login_at?: string | null
  last_login_ip?: string | null
  created_at: string
  updated_at: string
  /** Active lesser staff view (superadmin privilege switch). Never a client role. */
  privilege_viewing_as?: string | null
  /** True when this account may enter a lesser staff privilege view. */
  can_privilege_switch?: boolean
}

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy'
  version: string
  environment: string
  timestamp: string
}

export interface ApiError {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
}

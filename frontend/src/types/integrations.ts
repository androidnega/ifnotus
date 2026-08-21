export interface NamecheapIntegrationStatus {
  configured: boolean
  api_user?: string | null
  api_key_masked?: string | null
  client_ip?: string | null
  api_url?: string | null
}

export interface PaystackIntegrationStatus {
  configured: boolean
  public_key?: string | null
  secret_key_masked?: string | null
  base_url?: string | null
  demo_mode: boolean
}

export interface SmtpIntegrationStatus {
  configured: boolean
  host?: string | null
  port: number
  username?: string | null
  password_set: boolean
  password_masked?: string | null
  from_address?: string | null
  use_tls: boolean
}

export interface SmsIntegrationStatus {
  provider: string
  configured: boolean
  api_url?: string | null
  api_key_masked?: string | null
  api_secret_set: boolean
  sender_id?: string | null
}

export interface IntegrationsStatus {
  updated_at?: string | null
  namecheap: NamecheapIntegrationStatus
  paystack: PaystackIntegrationStatus
  smtp: SmtpIntegrationStatus
  sms: SmsIntegrationStatus
  momo: {
    network: string
    number?: string | null
    account_name?: string | null
  }
}

export interface IntegrationsUpdatePayload {
  namecheap?: {
    api_user?: string | null
    api_key?: string | null
    clear_api_key?: boolean
    client_ip?: string | null
    api_url?: string | null
  }
  paystack?: {
    public_key?: string | null
    secret_key?: string | null
    clear_secret_key?: boolean
    base_url?: string | null
  }
  smtp?: {
    host?: string | null
    port?: number | null
    username?: string | null
    password?: string | null
    clear_password?: boolean
    from_address?: string | null
    use_tls?: boolean | null
  }
  sms?: {
    provider?: string | null
    api_url?: string | null
    api_key?: string | null
    clear_api_key?: boolean
    api_secret?: string | null
    clear_api_secret?: boolean
    sender_id?: string | null
  }
  momo?: {
    network?: string | null
    number?: string | null
    account_name?: string | null
  }
}

/** Staff product-console types (customers / plans / orders). */

export interface StaffCustomerListItem {
  id: string
  email: string
  full_name: string
  phone?: string | null
  company?: string | null
  email_verified: boolean
  created_at: string
  environment_count: number
  subscription_count: number
  credits_remaining: number
  hosting_status?: 'none' | 'live' | 'suspended' | 'setting_up' | 'awaiting_payment' | 'inactive' | string
  primary_domain?: string | null
  awaiting_payment_count?: number
}

export interface StaffSubscriptionItem {
  id: string
  plan_id: string
  plan_name?: string | null
  status: string
  cpu_allocated: number
  ram_allocated: number
  storage_allocated: number
  expires_at?: string | null
  auto_renew: boolean
  grace_until?: string | null
}

export interface StaffEnvironmentItem {
  id: string
  subscription_id: string
  domain?: string | null
  hosting_name?: string | null
  status: string
  health_status: string
  isolation_type: string
  cpu_limit: number
  ram_limit_gb: number
  storage_limit_gb: number
  document_root?: string | null
  db_engine?: string | null
  db_name?: string | null
  created_at?: string | null
  container_id?: string | null
  ftp_username?: string | null
  stack?: Record<string, unknown> | null
  stack_progress?: Record<string, unknown> | null
}

export interface StaffAuditItem {
  id: string
  occurred_at: string
  action: string
  target_type?: string | null
  target_id?: string | null
  result: string
  metadata?: Record<string, unknown>
}

export interface StaffOrderItem {
  id: string
  customer_id: string
  customer_email?: string | null
  customer_name?: string | null
  customer_phone?: string | null
  plan_id: string
  plan_name?: string | null
  domain_name?: string | null
  domain_extension?: string | null
  plan_price?: string | number | null
  domain_price?: string | number | null
  total_price: string | number
  currency: string
  payment_status: string
  provisioning_status: string
  order_kind?: string | null
  paystack_reference?: string | null
  invoice_number?: string | null
  payment_method?: string | null
  momo_transaction_id?: string | null
  payment_amount_received?: string | number | null
  payment_notes?: string | null
  payment_confirmed_at?: string | null
  paid_at?: string | null
  created_at: string
}

export interface StaffAccountingSummary {
  period: { from: string; to: string }
  currency: string
  totals: {
    cash_collected_period?: number
    cash_collected_all_time?: number
    complimentary_period?: number
    complimentary_all_time?: number
    invoiced_paid_period?: number
    collected_period: number
    collected_all_time: number
    awaiting_confirm: number
    awaiting_confirm_count: number
    outstanding: number
    outstanding_count: number
    failed_count: number
    paid_count_period: number
    cash_count_period?: number
  }
  by_kind: Record<string, number>
  by_channel?: Record<string, number>
  by_day: Array<{ date: string; collected: number; complimentary?: number; count: number }>
  recent_paid: StaffAccountingLedgerItem[]
  pipeline?: {
    steps: Array<{ id: string; label: string; hint: string }>
  }
}

export interface StaffAccountingLedgerItem {
  id: string
  invoice_number?: string | null
  customer_id: string
  customer_name?: string | null
  customer_email?: string | null
  plan_name?: string | null
  order_kind: string
  currency: string
  invoiced: number
  collected?: number | null
  complimentary?: number | null
  entry_type?: string
  payment_status: string
  payment_method?: string | null
  momo_transaction_id?: string | null
  payment_notes?: string | null
  paid_at?: string | null
  payment_confirmed_at?: string | null
  created_at: string
}

export interface StaffCustomerDetail {
  customer: import('@/types/platform').CustomerProfile
  credits_remaining: number
  subscriptions: StaffSubscriptionItem[]
  environments: StaffEnvironmentItem[]
  orders: StaffOrderItem[]
  audit?: StaffAuditItem[]
}

export interface StaffEnvHealth {
  environment_id: string
  domain?: string | null
  status: string
  health_status: string
  summary: string
  checks: Record<string, unknown>
  checked_at?: string | null
  message?: string | null
}

export interface StaffEnvUsage {
  environment_id: string
  domain?: string | null
  cpu_limit: number
  ram_limit_gb: number
  storage_limit_gb: number
  storage_used_bytes: number
  storage_used_gb: number
  storage_pct: number
  file_count: number
  isolation_type: string
  soft_warning: boolean
  hard_exceeded: boolean
  storage_status: string
  message?: string | null
  container_id?: string | null
  ftp_username?: string | null
}

export interface StaffEnvStacks {
  environment_id: string
  stacks: Array<{
    id: string
    name: string
    description: string
    icon?: string
    level?: string
    allowed?: boolean
  }>
  current?: Record<string, unknown> | null
  progress?: Record<string, unknown> | null
  active_job_id?: string | null
}

export interface StaffEnvLogs {
  environment_id: string
  sources: string[]
  entries: Array<{ source: string; message: string }>
  message?: string | null
}

export interface StaffPlanInput {
  slug?: string | null
  name: string
  cpu_cores: number
  ram_gb: number
  storage_gb: number
  bandwidth_tb: number | string
  ai_credits: number
  price_monthly: number | string
  price_yearly?: number | string | null
  currency?: string
  features?: Record<string, unknown>
  sort_order?: number
  is_active?: boolean
  size_from_price?: boolean
}

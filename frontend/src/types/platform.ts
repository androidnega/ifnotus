export type HostingPlan = {
  id: string
  slug: string
  name: string
  cpu_cores: number
  ram_gb: number
  storage_gb: number
  bandwidth_tb: number
  ai_credits: number
  price_monthly: number
  price_yearly: number | null
  currency: string
  features: Record<string, unknown>
  /** Backend capabilities_for() — prefer over client FALLBACK. */
  capabilities?: {
    kind?: string
    matrix_key?: string
    custom_domains?: number | null
    repos?: number | null
    mailboxes?: number | null
    mail?: { enabled?: boolean; mailboxes?: number | null; storage_mb?: number | null }
    cron_limits?: { max_jobs?: number; min_interval_minutes?: number }
    ssh_mode?: string
    on?: Record<string, boolean>
    levels?: Record<string, string>
    stacks?: Record<string, string>
    isolation?: string
  }
  /** Backend catalog_card_for() — buyer-facing highlights. */
  catalog_card?: {
    display_name?: string
    blurb?: string
    product_status?: string
    production_notes?: string[]
    transfer?: { ftp?: string; sftp?: string }
    stacks_beta?: string[]
    highlights?: Array<{ id: string; label: string; detail: string }>
    stacks_included?: string[]
    stacks_limited?: string[]
    ssh_mode?: string
    mailboxes?: number | null
    domains?: number | null
  }
  sort_order: number
  is_active: boolean
}

/** PHASE 35 — Cloud VPS/VDS teaser; never purchasable on shared node. */
export type ComingSoonProduct = {
  matrix_key: string
  slug: string
  name: string
  kind: string
  status: string
  blurb: string
  sellable: boolean
  requires_external_vm: boolean
}

export type CustomerProfile = {
  id: string
  email: string
  full_name: string
  first_name?: string | null
  last_name?: string | null
  phone?: string | null
  company?: string | null
  email_verified: boolean
  phone_verified?: boolean
  profile_complete?: boolean
  onboarding_stage?: string
  onboarding_completed_at?: string | null
  can_order?: boolean
  can_student_hostname?: boolean
  missing_for_order?: string[]
  missing_for_student?: string[]
  two_factor_enabled: boolean
  created_at: string
  last_login_at?: string | null
  last_login_ip?: string | null
}

export type CustomerEnvironment = {
  id: string
  subscription_id: string
  customer_id: string
  status: string
  cpu_limit: number
  ram_limit_gb: number
  storage_limit_gb: number
  domain?: string | null
  hosting_name?: string | null
  document_root?: string | null
  health_status: string
  isolation_type?: string
  container_port?: number | null
  db_engine?: string | null
  db_name?: string | null
  db_username?: string | null
  db_host?: string | null
  db_port?: number | null
  db_password_set?: boolean
  created_at: string
  capabilities?: {
    kind?: string
    matrix_key?: string
    custom_domains?: number | null
    repos?: number | null
    mailboxes?: number | null
    mail?: {
      enabled?: boolean
      mailboxes?: number | null
      storage_mb?: number | null
    }
    ssh_mode?: string
    on?: Record<string, boolean>
    levels?: Record<string, string>
    stacks?: Record<string, string>
    isolation?: string
  }
}

export type CustomerSubscription = {
  id: string
  plan_id: string
  status: string
  cpu_allocated: number
  ram_allocated: number
  storage_allocated: number
  expires_at?: string | null
  auto_renew: boolean
  billing_term_months?: number
  grace_until?: string | null
}

export type CustomerDashboard = {
  brand: string
  customer: CustomerProfile
  credits: {
    customer_id: string
    credits_remaining: number
    total_allocated: number
    lifetime_used: number
    tokens_remaining?: number | null
    tokens_per_credit?: number | null
  }
  environments: CustomerEnvironment[]
  subscriptions: CustomerSubscription[]
  unread_notifications: number
  usage: Record<string, number>
  orders?: CustomerOrder[]
  momo?: { network: string; number: string; account_name: string } | null
  plans?: HostingPlan[]
}

export type CustomerOrder = {
  id: string
  plan_id: string
  domain_name?: string | null
  domain_extension?: string | null
  plan_price?: number | string
  domain_price?: number | string
  total_price: number | string
  currency: string
  payment_status: string
  provisioning_status: string
  invoice_number?: string | null
  payment_method?: string | null
  momo_transaction_id?: string | null
  created_at: string
  paid_at?: string | null
  expires_at?: string | null
  order_kind?: string | null
  billing_term_months?: number
  meta_json?: {
    billing_term_months?: number
    term_label?: string
    monthly_price?: number
    term_subtotal?: number
    term_discount_pct?: number
    term_discount_amount?: number
    entitlement_ends_at?: string
    [key: string]: unknown
  }
}

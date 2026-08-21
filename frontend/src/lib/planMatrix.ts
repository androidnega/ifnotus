import type { HostingPlan } from '@/types/platform'

export type FeatureLevel = 'yes' | 'limited' | 'no'

export const STACK_KEYS = [
  'php',
  'laravel',
  'wordpress',
  'mysql',
  'python',
  'django',
  'fastapi',
  'flask',
  'nodejs',
  'nextjs',
  'express',
  'react',
  'vue',
  'postgres',
  'mongodb',
  'redis',
  'docker',
] as const

export type StackKey = (typeof STACK_KEYS)[number]

export const STACK_LABELS: Record<StackKey, string> = {
  php: 'PHP',
  laravel: 'Laravel',
  wordpress: 'WordPress',
  mysql: 'MySQL / MariaDB',
  python: 'Python',
  django: 'Django',
  fastapi: 'FastAPI',
  flask: 'Flask',
  nodejs: 'Node.js',
  nextjs: 'Next.js',
  express: 'Express.js',
  react: 'React / Vite',
  vue: 'Vue / Nuxt',
  postgres: 'PostgreSQL',
  mongodb: 'MongoDB',
  redis: 'Redis',
  docker: 'Docker',
}

export type PlanMatrix = {
  matrix_key?: string
  kind: 'managed' | 'vps' | 'vds' | string
  custom_domains: number | null
  ssh: 'no' | 'limited' | 'jail' | 'root' | string
  stacks: Partial<Record<StackKey, FeatureLevel>>
  sftp?: FeatureLevel
  file_manager?: FeatureLevel
  cron?: FeatureLevel
  env_vars?: FeatureLevel
  ssl?: FeatureLevel
  dns?: FeatureLevel
  git?: FeatureLevel
  db_manage?: FeatureLevel
  ai?: FeatureLevel
  preview?: FeatureLevel
  staging?: FeatureLevel
  docker?: FeatureLevel
  root?: FeatureLevel
  vcpu?: number | null
  ram_gb?: number | null
  storage_gb?: number | null
  storage_kind?: string
}

const Y = 'yes' as const
const L = 'limited' as const
const N = 'no' as const

/** Client fallback when the API still returns a legacy features list. */
const FALLBACK: Record<string, Pick<PlanMatrix, 'kind' | 'custom_domains' | 'ssh' | 'stacks' | 'sftp' | 'file_manager' | 'cron' | 'ssl' | 'db_manage' | 'ai'>> = {
  'student-starter': {
    kind: 'managed', custom_domains: 1, ssh: 'limited',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: N, django: N, fastapi: N, flask: N, nodejs: N, nextjs: N, express: N, react: N, vue: N, postgres: N, mongodb: N, redis: N, docker: N },
  },
  personal: {
    kind: 'managed', custom_domains: 1, ssh: 'no',
    sftp: Y, file_manager: Y, cron: L, ssl: Y, db_manage: L, ai: L,
    stacks: { php: Y, laravel: L, wordpress: Y, mysql: L, python: L, django: N, fastapi: N, flask: L, nodejs: L, nextjs: N, express: L, react: Y, vue: L, postgres: L, mongodb: N, redis: N, docker: N },
  },
  'club-connect': {
    kind: 'managed', custom_domains: 3, ssh: 'limited',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: L, redis: L, docker: N },
  },
  'student-pro': {
    kind: 'managed', custom_domains: 5, ssh: 'jail',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: Y, redis: L, docker: L },
  },
  'student-elite': {
    kind: 'managed', custom_domains: 10, ssh: 'jail',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: Y, redis: Y, docker: L },
  },
  'business-pro': {
    kind: 'managed', custom_domains: 20, ssh: 'jail',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: Y, redis: Y, docker: Y },
  },
  'macho-power': {
    kind: 'managed', custom_domains: 40, ssh: 'jail',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: Y, redis: Y, docker: Y },
  },
  'monster-cloud': {
    kind: 'managed', custom_domains: 100, ssh: 'jail',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: Y, redis: Y, docker: Y },
  },
  'cloud-vps': {
    kind: 'vps', custom_domains: null, ssh: 'root',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: Y, redis: Y, docker: Y },
  },
  'cloud-vds': {
    kind: 'vds', custom_domains: null, ssh: 'root',
    sftp: Y, file_manager: Y, cron: Y, ssl: Y, db_manage: Y, ai: Y,
    stacks: { php: Y, laravel: Y, wordpress: Y, mysql: Y, python: Y, django: Y, fastapi: Y, flask: Y, nodejs: Y, nextjs: Y, express: Y, react: Y, vue: Y, postgres: Y, mongodb: Y, redis: Y, docker: Y },
  },
}

function asLevel(v: unknown): FeatureLevel {
  if (v === 'yes' || v === 'limited' || v === 'no') return v
  if (v === true) return 'yes'
  if (v === false) return 'no'
  return 'no'
}

export function planMatrixKey(plan: HostingPlan | null | undefined): string {
  const stored = String(plan?.features?.matrix_key || '')
  if (stored) return stored
  const slug = (plan?.slug || '').toLowerCase()
  if (slug.includes('vds')) return 'cloud-vds'
  if (slug.includes('vps')) return 'cloud-vps'
  if (slug.includes('personal')) return 'personal'
  if (slug.includes('starter')) return 'student-starter'
  if (slug.includes('club')) return 'club-connect'
  if (slug.includes('elite')) return 'student-elite'
  if (slug.includes('student-pro') || slug === 'student-pro') return 'student-pro'
  if (slug.includes('business')) return 'business-pro'
  if (slug.includes('macho')) return 'macho-power'
  if (slug.includes('monster')) return 'monster-cloud'
  const name = (plan?.name || '').toLowerCase()
  if (name.includes('vds')) return 'cloud-vds'
  if (name.includes('vps')) return 'cloud-vps'
  if (name.includes('personal')) return 'personal'
  if (name.includes('starter')) return 'student-starter'
  if (name.includes('club')) return 'club-connect'
  if (name.includes('elite')) return 'student-elite'
  if (name.includes('student pro')) return 'student-pro'
  if (name.includes('business')) return 'business-pro'
  if (name.includes('macho')) return 'macho-power'
  if (name.includes('monster')) return 'monster-cloud'
  return 'personal'
}

export function planMatrix(plan: HostingPlan | null | undefined): PlanMatrix {
  const key = planMatrixKey(plan)
  const fb = FALLBACK[key] || FALLBACK.personal
  const feats = Array.isArray(plan?.features) ? {} : ((plan?.features || {}) as Record<string, unknown>)
  const stacksRaw = (feats.stacks || {}) as Record<string, unknown>
  // Prefer matrix fallback for stacks (matches backend features_for). Stale plan.features.stacks
  // used to advertise Python/Django/etc. on Student Starter.
  const stacks: Partial<Record<StackKey, FeatureLevel>> = { ...fb.stacks }
  const keyIsManaged = Boolean(FALLBACK[key])
  if (!keyIsManaged) {
    for (const stackKey of STACK_KEYS) {
      if (stackKey in stacksRaw) stacks[stackKey] = asLevel(stacksRaw[stackKey])
    }
  }
  const domains = feats.custom_domains ?? fb.custom_domains
  return {
    matrix_key: key,
    kind: String(feats.kind || fb.kind),
    custom_domains: domains == null || domains === '' ? null : Number(domains),
    ssh: String(feats.ssh || fb.ssh),
    stacks,
    sftp: asLevel(feats.sftp ?? fb.sftp),
    file_manager: asLevel(feats.file_manager ?? fb.file_manager),
    cron: asLevel(feats.cron ?? fb.cron),
    env_vars: asLevel(feats.env_vars ?? 'no'),
    ssl: asLevel(feats.ssl ?? fb.ssl),
    dns: asLevel(feats.dns ?? 'limited'),
    git: asLevel(feats.git ?? 'no'),
    db_manage: asLevel(feats.db_manage ?? fb.db_manage),
    ai: asLevel(feats.ai ?? fb.ai),
    preview: asLevel(feats.preview ?? 'no'),
    staging: asLevel(feats.staging ?? 'no'),
    docker: asLevel((feats.stacks as Record<string, unknown> | undefined)?.docker ?? feats.docker ?? 'no'),
    root: asLevel(feats.root ?? 'no'),
    vcpu: feats.vcpu == null ? null : Number(feats.vcpu),
    ram_gb: feats.ram_gb == null ? null : Number(feats.ram_gb),
    storage_gb: feats.storage_gb == null ? null : Number(feats.storage_gb),
    storage_kind: feats.storage_kind ? String(feats.storage_kind) : undefined,
  }
}

export function visibleStacks(plan: HostingPlan | null | undefined) {
  const matrix = planMatrix(plan)
  return STACK_KEYS.map((id) => ({
    id,
    label: STACK_LABELS[id],
    level: matrix.stacks[id] || 'no',
  })).filter((s) => s.level === 'yes')
}

/** Included + limited (limited shown faded in UI). Excludes `no`. */
export function packStacksForDisplay(plan: HostingPlan | null | undefined) {
  const matrix = planMatrix(plan)
  return STACK_KEYS.map((id) => ({
    id,
    label: STACK_LABELS[id],
    level: (matrix.stacks[id] || 'no') as FeatureLevel,
  })).filter((s) => s.level !== 'no')
}

export function sshHeadline(plan: HostingPlan | null | undefined) {
  const mode = planMatrix(plan).ssh
  if (mode === 'root') return 'Full root SSH'
  if (mode === 'jail') return 'SSH included'
  if (mode === 'limited') return 'SSH with limits'
  return 'SSH not on this pack'
}

export function envCan(
  env: { capabilities?: { on?: Record<string, boolean> } } | null | undefined,
  key: string,
) {
  const on = env?.capabilities?.on
  if (!on) return true
  return Boolean(on[key])
}

export function featureOn(plan: HostingPlan | null | undefined, key: keyof PlanMatrix) {
  const v = planMatrix(plan)[key]
  if (v === 'yes' || v === 'limited') return true
  if (key === 'ssh') return ['limited', 'jail', 'root'].includes(String(v))
  return false
}

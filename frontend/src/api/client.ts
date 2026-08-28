import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { getDeviceFingerprint } from '@/lib/deviceFingerprint'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

let cachedFingerprint: string | null = null
let fingerprintPromise: Promise<string> | null = null

async function resolveFingerprint(): Promise<string | null> {
  if (cachedFingerprint) return cachedFingerprint
  if (typeof window === 'undefined') return null
  if (!fingerprintPromise) {
    fingerprintPromise = getDeviceFingerprint()
      .then((fp) => {
        cachedFingerprint = fp
        return fp
      })
      .catch(() => {
        fingerprintPromise = null
        return ''
      })
  }
  const fp = await fingerprintPromise
  return fp || null
}

export async function ensureDeviceFingerprint(): Promise<string | undefined> {
  const fp = await resolveFingerprint()
  return fp || undefined
}

function attachAuth(config: InternalAxiosRequestConfig) {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (cachedFingerprint) {
    config.headers['X-Device-Fingerprint'] = cachedFingerprint
  }
  return config
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

apiClient.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  await resolveFingerprint()
  return attachAuth(config)
})

function authRedirectPath(): string {
  if (typeof window === 'undefined') return '/login'
  const path = window.location.pathname || ''
  const search = window.location.search || ''
  const next = `${path}${search}`
  const host = (window.location.hostname || '').toLowerCase()
  if (host === 'cpanel.ifnotus.space') {
    if (next && next !== '/login' && !next.startsWith('/login?')) {
      return `/login?redirect=${encodeURIComponent(next)}`
    }
    return '/login'
  }
  // Custom-domain hosting panel — customer login stays on cpanel.<domain>.
  if (host.startsWith('cpanel.') && host !== 'cpanel.ifnotus.space') {
    if (next && next !== '/login' && next.startsWith('/') && !next.startsWith('//')) {
      return `/login?redirect=${encodeURIComponent(next)}`
    }
    return `/login?redirect=${encodeURIComponent(`/go/hosting?host=${encodeURIComponent(host)}`)}`
  }
  // Customer hosting deep-links (portal SSO) must never hit staff login.
  if (path.startsWith('/go/') || path.startsWith('/hosting') || path.startsWith('/account')) {
    if (next && next !== '/login' && next.startsWith('/') && !next.startsWith('//')) {
      return `/login?redirect=${encodeURIComponent(next)}`
    }
    return '/login'
  }
  const staffSurface =
    path.startsWith('/panel') ||
    path.startsWith('/admin/') ||
    path.startsWith('/monitoring') ||
    path.startsWith('/applications') ||
    path.startsWith('/operations') ||
    path.startsWith('/servers') ||
    path.startsWith('/security') ||
    path.startsWith('/settings') ||
    path.startsWith('/platform') ||
    path.startsWith('/support') ||
    path.startsWith('/mail') ||
    path.startsWith('/ssl') ||
    path.startsWith('/files') ||
    path.startsWith('/databases') ||
    path.startsWith('/domains') ||
    path.startsWith('/terminal')
  if (staffSurface) {
    return `/login?redirect=${encodeURIComponent(next)}`
  }
  if (next && next !== '/login' && next.startsWith('/') && !next.startsWith('//')) {
    return `/login?redirect=${encodeURIComponent(next)}`
  }
  return '/login'
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status
    const requestUrl = String(error.config?.url ?? '')
    const path = window.location.pathname || ''
    const onAuthPage =
      path.startsWith('/login') ||
      path.startsWith('/signup') ||
      path.startsWith('/staff/login') ||
      path.startsWith('/admin_1')
    const isAuthFlow =
      requestUrl.includes('/auth/login') ||
      requestUrl.includes('/auth/probe') ||
      requestUrl.includes('/auth/me') ||
      requestUrl.includes('/auth/logout') ||
      requestUrl.includes('/customers/phone/') ||
      requestUrl.includes('/customers/login')

    if (status === 401 && !onAuthPage && !isAuthFlow) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.location.href = authRedirectPath()
    }
    return Promise.reject(error)
  },
)

export default apiClient

/** Long-running client for file uploads/downloads (no request timeout). */
export const transferClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 0,
})

transferClient.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  await resolveFingerprint()
  return attachAuth(config)
})

transferClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status
    if (status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.location.href = authRedirectPath()
    }
    return Promise.reject(error)
  },
)

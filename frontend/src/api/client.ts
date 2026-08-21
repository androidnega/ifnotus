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

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status
    const requestUrl = String(error.config?.url ?? '')
    const onLoginPage = window.location.pathname.startsWith('/login')
    const isAuthFlow =
      requestUrl.includes('/auth/login') ||
      requestUrl.includes('/auth/probe') ||
      requestUrl.includes('/auth/me') ||
      requestUrl.includes('/auth/logout')

    if (status === 401 && !onLoginPage && !isAuthFlow) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.location.href = '/login'
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
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

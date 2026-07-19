import type { AxiosError } from 'axios'

/** Extract a human-readable message from Axios / API error envelopes. */
export function getApiErrorMessage(error: unknown, fallback = 'Request failed'): string {
  const axiosErr = error as AxiosError<{ error?: { message?: string }; detail?: string | Array<{ msg?: string }> }>
  const data = axiosErr.response?.data
  if (data && typeof data === 'object') {
    if (data.error?.message) return data.error.message
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail) && data.detail[0]?.msg) return String(data.detail[0].msg)
  }
  if (error instanceof Error && error.message) return error.message
  return fallback
}

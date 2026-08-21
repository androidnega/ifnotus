/** Server-Sent Event helpers for the SNR Dev agent. */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export type AiStreamEvent = {
  type: string
  text?: string
  phase?: string
  name?: string
  path?: string
  content?: string
  success?: boolean
  message?: string
  details?: Record<string, unknown>
  configured?: boolean
  session_id?: string
  pending_actions?: import('@/types/ai').AiPendingAction[]
  tool_traces?: import('@/types/ai').AiToolTrace[]
  usage?: {
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
    weighted_tokens?: number
    credits_charged?: number
    credits_remaining?: number
    tokens_remaining?: number
    tokens_per_credit?: number
  }
  credits_remaining?: number
  tokens_remaining?: number
  credits_charged?: number
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('access_token')
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export async function* readSseStream(response: Response): AsyncGenerator<AiStreamEvent> {
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(text || `Request failed (${response.status})`)
  }
  if (!response.body) {
    throw new Error('No response stream')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      const line = chunk
        .split('\n')
        .map((l) => l.trim())
        .find((l) => l.startsWith('data:'))
      if (!line) continue
      const data = line.replace(/^data:\s?/, '')
      if (data === '[DONE]') return
      try {
        yield JSON.parse(data) as AiStreamEvent
      } catch {
        /* ignore malformed */
      }
    }
  }
}

export async function streamAiChat(
  body: Record<string, unknown>,
  opts?: { path?: string },
): Promise<Response> {
  const path = opts?.path || '/ai/chat/stream'
  return fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
}

export async function streamAiApply(
  token: string,
  confirmPassword?: string,
  opts?: { path?: string },
): Promise<Response> {
  const path = opts?.path || '/ai/actions/apply/stream'
  return fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      token,
      ...(confirmPassword ? { confirm_password: confirmPassword } : {}),
    }),
  })
}

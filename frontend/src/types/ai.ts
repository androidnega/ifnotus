export interface AiSettings {
  configured: boolean
  model: string
  base_url: string
  api_key_masked: string | null
  agent_name?: string
  updated_at: string | null
}

export interface AiChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  name?: string | null
  tool_call_id?: string | null
}

export interface AiPendingAction {
  id: string
  type: 'write_file' | 'terminal' | 'mkdir' | 'write_files' | 'create_database' | 'drop_database' | 'run_sql' | 'run_mongo'
  reason: string
  path?: string | null
  content?: string | null
  command?: string | null
  cwd?: string | null
  app_id?: string | null
  root_id?: string | null
  token: string
  preview?: string | null
  critical?: boolean
  files?: Array<{ path?: string; absolute_path?: string; content?: string }> | null
  database?: Record<string, unknown> | null
  edits?: Array<{ old_text: string; new_text: string }> | null
  patch?: boolean
}

export interface AiToolTrace {
  name: string
  arguments: Record<string, unknown>
  result_preview: string
}

export interface AiChatResponse {
  reply: string
  pending_actions: AiPendingAction[]
  tool_traces: AiToolTrace[]
  configured: boolean
  session_id?: string | null
}

export interface AiPanelMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  pending?: AiPendingAction[]
  traces?: AiToolTrace[]
}

export interface AiSessionSummary {
  id: string
  title: string
  surface: string
  path?: string | null
  app_id?: string | null
  root_id?: string | null
  message_count: number
  created_at?: string | null
  updated_at?: string | null
}

export interface AiSessionDetail {
  id: string
  title: string
  surface: string
  path?: string | null
  app_id?: string | null
  root_id?: string | null
  messages: Array<{ id?: string; role: string; content: string }>
  created_at?: string | null
  updated_at?: string | null
}

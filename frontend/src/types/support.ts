export type SupportTicketStatus = 'open' | 'pending' | 'closed'
export type SupportTicketPriority = 'low' | 'normal' | 'high'

export interface SupportTicketMessage {
  id: string
  ticket_id: string
  author_user_id?: string | null
  author_role: 'customer' | 'staff' | string
  body: string
  created_at?: string | null
}

export interface SupportTicket {
  id: string
  customer_id: string
  environment_id?: string | null
  subject: string
  status: SupportTicketStatus | string
  priority: SupportTicketPriority | string
  created_at?: string | null
  updated_at?: string | null
  customer_email?: string | null
  customer_name?: string | null
  messages?: SupportTicketMessage[]
}

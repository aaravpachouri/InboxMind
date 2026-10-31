export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');

function cookieValue(name: string): string | undefined {
  const prefix = `${name}=`;
  const entry = document.cookie.split('; ').find((item) => item.startsWith(prefix));
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : undefined;
}

export type EmailSummary = {
  id: string;
  thread_id: string;
  from_address: string;
  to_addresses?: string;
  subject: string;
  snippet?: string;
  internal_date?: string;
  labels?: string[];
  is_unread?: boolean;
  is_sent?: boolean;
  has_attachments?: boolean;
  priority?: string;
  category?: string;
  ai_summary?: string;
};

export type EmailDetail = EmailSummary & {
  cc_addresses?: string;
  body_text?: string;
  attachment_metadata?: Array<{ attachment_id: string; filename: string; mime_type?: string; size?: number }>;
  ai_analysis?: Record<string, unknown>;
  raw_headers?: Record<string, string>;
};

export type TaskItem = {
  id: number;
  title: string;
  description?: string;
  due_date?: string | null;
  priority?: 'low' | 'medium' | 'high' | 'urgent';
  status?: 'open' | 'in_progress' | 'done' | 'dismissed';
  source_email_id?: string | null;
  created_at?: string;
};

export type DraftItem = {
  id: number;
  to_addresses: string[];
  cc_addresses?: string[];
  bcc_addresses?: string[];
  subject: string;
  body_text: string;
  status: string;
  source_email_id?: string | null;
  gmail_draft_id?: string | null;
  created_at?: string;
  updated_at?: string;
  sent_at?: string | null;
  ai_provider?: string;
  warning?: string | null;
};

export type Briefing = {
  generated_at?: string;
  period_hours?: number;
  provider?: string;
  summary?: string;
  counts?: Record<string, number>;
  important_emails?: EmailSummary[];
  tasks_due_today_or_overdue?: TaskItem[];
  next_steps?: string[];
};

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  headers.set('Accept', 'application/json');
  const method = (options.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = cookieValue('inboxmind_csrf');
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path.startsWith('/') ? path : `/${path}`}`, {
      ...options,
      headers,
      credentials: 'include',
      cache: 'no-store',
    });
  } catch (error) {
    throw new ApiError(
      `Cannot reach InboxMind API at ${API_BASE}. Check your internet connection and API deployment.`,
      0,
      error,
    );
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try { body = JSON.parse(text); } catch { body = text; }
  }
  if (!response.ok) {
    const asRecord = body && typeof body === 'object' ? body as Record<string, unknown> : null;
    const detail = asRecord?.detail;
    const message = typeof detail === 'string'
      ? detail
      : `Request failed (${response.status}). ${typeof body === 'string' ? body : ''}`.trim();
    throw new ApiError(message, response.status, detail ?? body);
  }
  return body as T;
}

export function qp(values: Record<string, string | number | boolean | undefined | null>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  });
  return params.toString() ? `?${params}` : '';
}

export function formatDate(value?: string | null, mode: 'relative' | 'date' = 'relative'): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  if (mode === 'date') return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (sameDay) return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(date);
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  const days = Math.round((now.getTime() - date.getTime()) / 86400000);
  if (days >= 0 && days < 7) return new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(date);
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
}

export function senderName(address?: string): string {
  const input = address || '';
  const match = input.match(/^\s*([^<]+?)\s*<([^>]+)>\s*$/);
  if (match) return match[1].replace(/^"|"$/g, '').trim();
  return input.includes('@') ? input.split('@')[0].replace(/[._-]/g, ' ') : input || 'Unknown sender';
}

export function initials(value?: string): string {
  const name = senderName(value).trim();
  const words = name.split(/\s+/).filter(Boolean);
  return (words.length > 1 ? `${words[0][0]}${words[1][0]}` : name.slice(0, 2)).toUpperCase();
}

export function priorityLabel(value?: string): string {
  return (value || 'normal').replace(/_/g, ' ');
}

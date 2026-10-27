// Talks to the Python server (pipeline/tetclipper_pipeline/server): one POST
// per command, one shared SSE stream for every event (pipeline progress,
// spec changes, chat). The desktop app serves the editor itself (same
// origin); the hosted editor on Vercel reaches the API at VITE_API_URL and
// sends the user's sign-in token.
import type { ClipSpecInput } from '@tetclipper/composition'

export const API = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').replace(/\/$/, '')

let token: string | null = null // Supabase access token (commands, uploads)
let mediaToken: string | null = null // long-lived, for <video> and the event stream

/** Called when the user signs in, their token refreshes, or they sign out. */
export function setAuth(access: string | null, media: string | null) {
  token = access
  if (media !== mediaToken) {
    mediaToken = media
    if (source) {
      source.close()
      source = null
      if (listeners.size) connect()
    }
  }
}

const authHeaders = (): Record<string, string> => (token ? { Authorization: `Bearer ${token}` } : {})
const withMedia = (url: string) => (mediaToken ? `${url}${url.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(mediaToken)}` : url)

export async function invoke<T = unknown>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(`${API}/api/cmd/${name}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(args)
  })
  const text = await res.text()
  if (res.status === 401) throw new Error('Your session ended. Sign in again.')
  if (!res.ok) throw new Error(text.replace(/^"|"$/g, '') || `${name} failed (${res.status})`)
  return (text ? JSON.parse(text) : null) as T
}

/** How this server signs people in: none (desktop app), supabase (online) or token. */
export async function authConfig(): Promise<{ mode: 'none' | 'supabase' | 'token' }> {
  const res = await fetch(`${API}/api/auth-config`)
  // A server from before online sign-in has no such route: it needs no sign-in.
  if (res.status === 404 && API === '') return { mode: 'none' }
  if (!res.ok) throw new Error(`The tetclipper server didn't answer (${res.status}).`)
  return res.json()
}

type Listener = (event: ServerEvent) => void
const listeners = new Set<Listener>()
let source: EventSource | null = null

function connect() {
  source = new EventSource(withMedia(`${API}/api/events`))
  source.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data) as ServerEvent
      listeners.forEach((l) => l(event))
    } catch {
      /* ignore malformed lines */
    }
  }
}

/** Subscribe to every server event. Returns the unsubscribe function. */
export function onEvent(fn: Listener): () => void {
  listeners.add(fn)
  if (!source) connect()
  return () => listeners.delete(fn)
}

export async function upload(file: File): Promise<string> {
  const res = await fetch(`${API}/api/upload?name=${encodeURIComponent(file.name)}`, { method: 'POST', body: file, headers: authHeaders() })
  if (!res.ok) throw new Error(`upload failed (${res.status})`)
  return ((await res.json()) as { path: string }).path
}

/** A file on the server (under the user's workspace) as a URL the browser can load. */
export function fileUrl(path: string, download = false): string {
  return withMedia(`${API}/files?path=${encodeURIComponent(path)}${download ? '&download=1' : ''}`)
}

const isUrl = (s: string) => /^(https?:|data:|blob:|\/)/.test(s)

/** A path from the spec (relative to the job dir) → a URL the browser can load. */
export function mediaUrl(jobDir: string, src: string): string {
  if (!src || isUrl(src)) return src
  const sep = jobDir.includes('\\') ? '\\' : '/'
  return fileUrl(`${jobDir}${sep}${src.split('/').join(sep)}`)
}

/** The spec with every relative asset path resolved for the Player. */
export function resolveForPlayer(spec: ClipSpecInput, jobDir: string): ClipSpecInput {
  return {
    ...spec,
    source: { ...spec.source, src: mediaUrl(jobDir, spec.source.src) },
    intro: spec.intro ? { ...spec.intro, src: mediaUrl(jobDir, spec.intro.src) } : spec.intro,
    music: spec.music ? { ...spec.music, src: mediaUrl(jobDir, spec.music.src) } : spec.music,
    matte: spec.matte ? { ...spec.matte, src: mediaUrl(jobDir, spec.matte.src) } : spec.matte,
    effects: spec.effects?.map((e) => ((e.type === 'image' || e.type === 'background') && e.src ? { ...e, src: mediaUrl(jobDir, e.src) } : e))
  }
}

export interface HistoryEntry {
  version: number
  reason: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'error'
  text: string
  ts?: number
  model?: string | null
  cost?: number | null
}

/** Which AI answers in the Studio chat (set by the admin under AI model). */
export interface Engine {
  provider: string
  model: string
  label: string
  ready: boolean
}

export interface ClipData {
  jobId: string
  jobDir: string
  clip: number
  title: string
  spec: ClipSpecInput
  history: HistoryEntry[]
  chat: { messages: ChatMessage[]; busy: boolean; available: boolean; engine: Engine; notice?: string | null }
  render: { output: string; spec_version: number | null; rendered_at: string } | null
}

export interface AiProvider {
  id: string
  label: string
  kind: 'cli' | 'anthropic' | 'openai'
  note: string | null
  key_url: string | null
  default: string
  models: string[]
  key: string | null // masked hint of the saved key
}

export interface AiSettings {
  provider: string
  model: string
  base_url: string
  prices: Record<string, { in: number | null; out: number | null }>
  known_prices: Record<string, [number, number]>
  providers: AiProvider[]
}

export interface JobSummary {
  id: string
  title: string
  section: [number, number] | null
  clips: { clip: number; rendered: boolean; style: string | null; score: number | null; summary: string | null }[]
}

export type ServerEvent =
  | { event: 'job'; job_id: string; dir: string }
  | { event: 'progress'; stage: string; fraction: number; message: string }
  | { event: 'result'; ok: boolean; job_id?: string; clip?: number; error?: string; output?: unknown }
  | { event: 'exited'; code: number }
  | { event: 'spec'; job_id: string; clip: number; spec: ClipSpecInput; source: string; history: HistoryEntry[] }
  | { event: 'studio-chat'; job_id: string; clip: number; kind: 'text' | 'delta' | 'tool' | 'done'; text?: string; error?: string | null; model?: string | null; cost?: number | null }

export function fmt(t: number): string {
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return `${m}:${s.toFixed(1).padStart(4, '0')}`
}

/** '12:30', '1:02:03', '750' → seconds (NaN when unparseable). */
export function parseClock(text: string): number {
  const parts = text.trim().split(':').map(Number)
  if (!parts.length || parts.length > 3 || parts.some((p) => !Number.isFinite(p) || p < 0)) return NaN
  return parts.reduce((acc, p) => acc * 60 + p, 0)
}

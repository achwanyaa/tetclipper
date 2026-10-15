// Talks to the Python server (pipeline/tetclipper_pipeline/server): one POST
// per command, one shared SSE stream for every event (pipeline progress,
// spec changes, chat).
import type { ClipSpecInput } from '@tetclipper/composition'

export async function invoke<T = unknown>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(`/api/cmd/${name}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args)
  })
  const text = await res.text()
  if (!res.ok) throw new Error(text.replace(/^"|"$/g, '') || `${name} failed (${res.status})`)
  return (text ? JSON.parse(text) : null) as T
}

type Listener = (event: ServerEvent) => void
const listeners = new Set<Listener>()
let source: EventSource | null = null

/** Subscribe to every server event. Returns the unsubscribe function. */
export function onEvent(fn: Listener): () => void {
  listeners.add(fn)
  if (!source) {
    source = new EventSource('/api/events')
    source.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as ServerEvent
        listeners.forEach((l) => l(event))
      } catch {
        /* ignore malformed lines */
      }
    }
  }
  return () => listeners.delete(fn)
}

export async function upload(file: File): Promise<string> {
  const res = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, { method: 'POST', body: file })
  if (!res.ok) throw new Error(`upload failed (${res.status})`)
  return ((await res.json()) as { path: string }).path
}

const isUrl = (s: string) => /^(https?:|data:|blob:|\/)/.test(s)

/** A path from the spec (relative to the job dir) → a URL the browser can load. */
export function mediaUrl(jobDir: string, src: string): string {
  if (!src || isUrl(src)) return src
  const sep = jobDir.includes('\\') ? '\\' : '/'
  return `/files?path=${encodeURIComponent(`${jobDir}${sep}${src.split('/').join(sep)}`)}`
}

/** The spec with every relative asset path resolved for the Player. */
export function resolveForPlayer(spec: ClipSpecInput, jobDir: string): ClipSpecInput {
  return {
    ...spec,
    source: { ...spec.source, src: mediaUrl(jobDir, spec.source.src) },
    intro: spec.intro ? { ...spec.intro, src: mediaUrl(jobDir, spec.intro.src) } : spec.intro,
    effects: spec.effects?.map((e) => (e.type === 'image' ? { ...e, src: mediaUrl(jobDir, e.src) } : e))
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
}

export interface ClipData {
  jobId: string
  jobDir: string
  clip: number
  title: string
  spec: ClipSpecInput
  history: HistoryEntry[]
  chat: { messages: ChatMessage[]; busy: boolean; available: boolean }
  render: { output: string; spec_version: number | null; rendered_at: string } | null
}

export interface JobSummary {
  id: string
  title: string
  section: [number, number] | null
  clips: { clip: number; rendered: boolean; style: string | null }[]
}

export type ServerEvent =
  | { event: 'job'; job_id: string; dir: string }
  | { event: 'progress'; stage: string; fraction: number; message: string }
  | { event: 'result'; ok: boolean; job_id?: string; clip?: number; error?: string; output?: unknown }
  | { event: 'exited'; code: number }
  | { event: 'spec'; job_id: string; clip: number; spec: ClipSpecInput; source: string; history: HistoryEntry[] }
  | { event: 'studio-chat'; job_id: string; clip: number; kind: 'text' | 'delta' | 'tool' | 'done'; text?: string; error?: string | null }

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

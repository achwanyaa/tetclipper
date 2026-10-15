// One transport for the whole UI: Tauri inside the desktop app, HTTP + SSE
// against `tetclipper serve` in a plain browser. Components import from here,
// never from @tauri-apps directly.
import { convertFileSrc as tauriFileSrc, invoke as tauriInvoke } from '@tauri-apps/api/core'
import { listen as tauriListen } from '@tauri-apps/api/event'
import { getCurrentWebview } from '@tauri-apps/api/webview'
import { open as tauriOpen, type OpenDialogOptions } from '@tauri-apps/plugin-dialog'
import { openUrl as tauriOpenUrl } from '@tauri-apps/plugin-opener'

export const isTauri = '__TAURI_INTERNALS__' in window

/** Where `tetclipper serve` lives. Same origin by default (it serves the UI
 *  itself, and the Vite dev server proxies to it). */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (isTauri) return tauriInvoke<T>(cmd, args)
  const res = await fetch(`${API_BASE}/api/cmd/${cmd}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args ?? {})
  })
  const text = await res.text()
  const value = text ? JSON.parse(text) : null
  // A hosted server wants its access token: App shows the login screen.
  if (res.status === 401) throw AUTH_REQUIRED
  // Errors reject with the message string, like a rejected Tauri invoke.
  if (!res.ok) throw typeof value === 'string' ? value : text
  return value as T
}

export const AUTH_REQUIRED = 'AUTH_REQUIRED'

/** Trade the deployment's access token for the cookie every later request
 *  (including <video> and the event stream) rides on. */
export async function login(token: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token })
  })
  return res.ok
}

type Handler<T> = (event: { payload: T }) => void
const handlers = new Map<string, Set<Handler<any>>>()
let source: EventSource | null = null
const openHandlers = new Set<() => void>()

/** Called every time the event stream (re)connects. Events sent while it was
 *  down are lost, so callers re-check whatever they were waiting for. */
export function onStreamOpen(handler: () => void): () => void {
  openHandlers.add(handler)
  return () => {
    openHandlers.delete(handler)
  }
}

/** Only one event channel exists (`pipeline-event`); the server sends every
 *  pipeline line on /api/events. */
export async function listen<T>(event: string, handler: Handler<T>): Promise<() => void> {
  if (isTauri) return tauriListen<T>(event, handler)
  if (!handlers.has(event)) handlers.set(event, new Set())
  handlers.get(event)!.add(handler)
  if (!source) {
    source = new EventSource(`${API_BASE}/api/events`)
    source.onopen = () => openHandlers.forEach((h) => h())
    source.onmessage = (msg) => {
      const payload = JSON.parse(msg.data)
      handlers.get('pipeline-event')?.forEach((h) => h({ payload }))
    }
  }
  return () => {
    handlers.get(event)?.delete(handler)
  }
}

export function fileUrl(path: string): string {
  return isTauri ? tauriFileSrc(path) : `${API_BASE}/files?path=${encodeURIComponent(path)}`
}

export async function openUrl(url: string): Promise<void> {
  if (isTauri) return tauriOpenUrl(url)
  window.open(url, '_blank', 'noopener')
}

/** Send a browser File to the server; resolves to its path there. */
export async function uploadFile(file: File, onProgress?: (fraction: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/api/upload?name=${encodeURIComponent(file.name)}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total)
    xhr.onload = () =>
      xhr.status < 300 ? resolve(JSON.parse(xhr.responseText).path) : reject(xhr.responseText)
    xhr.onerror = () => reject('upload failed')
    xhr.send(file)
  })
}

function pickBrowserFiles(opts: OpenDialogOptions): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = !!opts.multiple || !!opts.directory
    if (opts.directory) input.webkitdirectory = true
    const exts = opts.filters?.flatMap((f) => f.extensions) ?? []
    if (exts.length) input.accept = exts.map((e) => `.${e}`).join(',')
    input.onchange = () => resolve(Array.from(input.files ?? []))
    input.oncancel = () => resolve([])
    input.click()
  })
}

/** Same contract as the Tauri dialog's `open`: path, paths, or null.
 *  In a browser the picked files are uploaded first. */
export async function openDialog(
  opts: OpenDialogOptions & { onProgress?: (fraction: number) => void } = {}
): Promise<string | string[] | null> {
  if (isTauri) return tauriOpen(opts)
  const files = await pickBrowserFiles(opts)
  if (files.length === 0) return null
  const paths: string[] = []
  for (const [i, file] of files.entries()) {
    paths.push(await uploadFile(file, (f) => opts.onProgress?.((i + f) / files.length)))
  }
  return opts.multiple || opts.directory ? paths : paths[0]
}

export type DropEvent =
  | { type: 'enter' | 'over' | 'leave' }
  | { type: 'uploading'; name: string; fraction: number }
  | { type: 'drop'; paths: string[] }

/** File drops on the window. Tauri hands over paths; a browser hands over
 *  Files, which are uploaded (accept decides which) before `drop` fires. */
export async function onFileDrop(
  handler: (event: DropEvent) => void,
  accept: (name: string) => boolean = () => true
): Promise<() => void> {
  if (isTauri) {
    return getCurrentWebview().onDragDropEvent(({ payload }) => {
      if (payload.type === 'drop') handler({ type: 'drop', paths: payload.paths })
      else handler({ type: payload.type })
    })
  }
  const over = (e: DragEvent) => {
    e.preventDefault()
    handler({ type: 'over' })
  }
  const leave = (e: DragEvent) => {
    if (!e.relatedTarget) handler({ type: 'leave' })
  }
  const drop = async (e: DragEvent) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer?.files ?? [])
    const wanted = files.find((f) => accept(f.name))
    if (!wanted) {
      handler({ type: 'drop', paths: files.map((f) => f.name) })
      return
    }
    const path = await uploadFile(wanted, (fraction) =>
      handler({ type: 'uploading', name: wanted.name, fraction })
    )
    handler({ type: 'drop', paths: [path] })
  }
  window.addEventListener('dragover', over)
  window.addEventListener('dragleave', leave)
  window.addEventListener('drop', drop)
  return () => {
    window.removeEventListener('dragover', over)
    window.removeEventListener('dragleave', leave)
    window.removeEventListener('drop', drop)
  }
}

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClipSpecInput } from '@tetclipper/composition'
import { invoke, onEvent, type ClipData, type JobSummary } from './api'
import { Canvas } from './components/Canvas'
import { Chat } from './components/Chat'
import { Sidebar } from './components/Sidebar'

export interface Run {
  kind: 'cut' | 'render'
  jobId?: string
  clip?: number
  fraction: number
  message: string
  error?: string
}

export interface EditorState {
  playhead: number | null // source seconds
  selection: [number, number] | null // word indices
}

const SAVE_DELAY = 350

export function App() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [open, setOpen] = useState<{ jobId: string; clip: number } | null>(null)
  const [data, setData] = useState<ClipData | null>(null)
  const [spec, setSpec] = useState<ClipSpecInput | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [editor, setEditor] = useState<EditorState>({ playhead: null, selection: null })
  const [error, setError] = useState<string | null>(null)
  const saveTimer = useRef<number | undefined>(undefined)
  const pending = useRef<{ spec: ClipSpecInput; reason: string } | null>(null)
  const openRef = useRef(open)
  openRef.current = open
  const runRef = useRef(run)
  runRef.current = run

  const refreshJobs = useCallback(() => {
    invoke<JobSummary[]>('studio_jobs').then(setJobs).catch((e) => setError(String(e.message ?? e)))
  }, [])

  const loadClip = useCallback(async (jobId: string, clip: number) => {
    try {
      const d = await invoke<ClipData>('studio_clip', { jobId, clip })
      setData(d)
      setSpec(d.spec)
      setEditor({ playhead: null, selection: null })
      setError(null)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    }
  }, [])

  useEffect(refreshJobs, [refreshJobs])
  useEffect(() => {
    if (open) loadClip(open.jobId, open.clip)
  }, [open, loadClip])

  // Server events: live spec changes (Claude, undo), pipeline progress.
  useEffect(
    () =>
      onEvent((ev) => {
        const cur = openRef.current
        if (ev.event === 'spec' && cur && ev.job_id === cur.jobId && ev.clip === cur.clip) {
          if (ev.source !== 'editor') setSpec(ev.spec)
          setData((d) => (d ? { ...d, history: [...d.history.filter((h) => !ev.history.some((n) => n.version === h.version)), ...ev.history] } : d))
        } else if (ev.event === 'job' && runRef.current?.kind === 'cut') {
          setRun((r) => (r ? { ...r, jobId: ev.job_id } : r))
          refreshJobs()
        } else if (ev.event === 'progress' && runRef.current) {
          setRun((r) => (r ? { ...r, fraction: ev.fraction >= 0 ? ev.fraction : r.fraction, message: ev.message } : r))
        } else if ((ev.event === 'result' || ev.event === 'exited') && runRef.current) {
          const r = runRef.current
          const ok = ev.event === 'result' && ev.ok
          const err = ev.event === 'result' ? ev.error : `pipeline exited (${ev.code})`
          refreshJobs()
          if (!ok) {
            setRun({ ...r, error: err ?? 'failed', fraction: 1 })
            return
          }
          setRun(null)
          if (r.kind === 'cut' && ev.event === 'result' && ev.job_id) setOpen({ jobId: ev.job_id, clip: 0 })
          if (r.kind === 'render' && cur) loadClip(cur.jobId, cur.clip)
        }
      }),
    [refreshJobs, loadClip]
  )

  /** Apply an edit locally at once; persist it after a short pause (sliders). */
  const update = useCallback(
    (next: ClipSpecInput, reason: string) => {
      const cur = openRef.current
      if (!cur) return
      setSpec(next)
      pending.current = { spec: next, reason }
      window.clearTimeout(saveTimer.current)
      saveTimer.current = window.setTimeout(async () => {
        const p = pending.current
        pending.current = null
        if (!p) return
        try {
          const res = await invoke<{ history: ClipData['history'] }>('studio_save', { jobId: cur.jobId, clip: cur.clip, spec: p.spec, reason: p.reason })
          setData((d) => (d ? { ...d, history: res.history } : d))
          setError(null)
        } catch (e) {
          setError(String((e as Error).message ?? e))
        }
      }, SAVE_DELAY)
    },
    []
  )

  const undo = useCallback(async () => {
    if (!open) return
    try {
      const res = await invoke<{ spec: ClipSpecInput; history: ClipData['history'] }>('studio_undo', open)
      setSpec(res.spec)
      setData((d) => (d ? { ...d, history: res.history } : d))
    } catch (e) {
      setError(String((e as Error).message ?? e))
    }
  }, [open])

  const startRender = useCallback(async () => {
    if (!open) return
    setRun({ kind: 'render', jobId: open.jobId, clip: open.clip, fraction: 0, message: 'Starting render…' })
    try {
      await invoke('studio_render', open)
    } catch (e) {
      setRun((r) => (r ? { ...r, error: String((e as Error).message ?? e) } : r))
    }
  }, [open])

  const startCut = useCallback(async (args: { source: string; start: number; end: number; captions: string; language: string }) => {
    setRun({ kind: 'cut', fraction: 0, message: 'Starting…' })
    try {
      await invoke('studio_cut', args)
    } catch (e) {
      setRun((r) => (r ? { ...r, error: String((e as Error).message ?? e) } : r))
    }
  }, [])

  return (
    <div className="studio">
      <Sidebar
        jobs={jobs}
        open={open}
        run={run}
        onOpen={(jobId, clip) => setOpen({ jobId, clip })}
        onCut={startCut}
        onDismissRun={() => setRun(null)}
      />
      <main className="center">
        {error && (
          <div className="banner error" onClick={() => setError(null)}>
            {error}
          </div>
        )}
        {data && spec ? (
          <Canvas
            key={`${data.jobId}/${data.clip}`}
            data={data}
            spec={spec}
            editor={editor}
            setEditor={setEditor}
            update={update}
            undo={undo}
            run={run}
            onRender={startRender}
            setError={setError}
          />
        ) : (
          <div className="empty">
            <h1>tetclipper Studio</h1>
            <p>Paste a YouTube link and a range on the left, or open a clip.</p>
          </div>
        )}
      </main>
      {data && <Chat key={`${data.jobId}/${data.clip}`} data={data} editor={editor} />}
    </div>
  )
}

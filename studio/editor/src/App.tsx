import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClipSpecInput } from '@tetclipper/composition'
import { invoke, onEvent, type AiSettings as AiSettingsData, type ClipData, type JobSummary } from './api'
import { AiSettings } from './components/AiSettings'
import { Canvas } from './components/Canvas'
import { Home } from './components/Home'
import { NewClip, type CutArgs, type FindArgs } from './components/NewClip'
import { TopBar, type Step } from './components/TopBar'
import { useTheme } from './theme'

export interface Run {
  kind: 'cut' | 'find' | 'render'
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
  const theme = useTheme()
  const [screen, setScreen] = useState<'home' | 'new'>('home')
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [open, setOpen] = useState<{ jobId: string; clip: number } | null>(null)
  const [data, setData] = useState<ClipData | null>(null)
  const [spec, setSpec] = useState<ClipSpecInput | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [editor, setEditor] = useState<EditorState>({ playhead: null, selection: null })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [ai, setAi] = useState<AiSettingsData | null>(null)
  const [aiOpen, setAiOpen] = useState(false)
  const saveTimer = useRef<number | undefined>(undefined)
  const pending = useRef<{ spec: ClipSpecInput; reason: string } | null>(null)
  const openRef = useRef(open)
  openRef.current = open
  const runRef = useRef(run)
  runRef.current = run

  const refreshJobs = useCallback(() => {
    invoke<JobSummary[]>('studio_jobs')
      .then((j) => {
        setJobs(j)
        setLoadError(null)
      })
      .catch((e) => setLoadError(String(e.message ?? e)))
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
    invoke<AiSettingsData>('ai_settings_get').then(setAi).catch(() => undefined)
  }, [])
  useEffect(() => {
    if (open) loadClip(open.jobId, open.clip)
    else {
      setData(null)
      setSpec(null)
    }
  }, [open, loadClip])

  // Server events: live spec changes (Claude, undo), pipeline progress.
  useEffect(
    () =>
      onEvent((ev) => {
        const cur = openRef.current
        if (ev.event === 'spec' && cur && ev.job_id === cur.jobId && ev.clip === cur.clip) {
          if (ev.source !== 'editor') setSpec(ev.spec)
          setData((d) => (d ? { ...d, history: [...d.history.filter((h) => !ev.history.some((n) => n.version === h.version)), ...ev.history] } : d))
        } else if (ev.event === 'job' && (runRef.current?.kind === 'cut' || runRef.current?.kind === 'find')) {
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
          if ((r.kind === 'cut' || r.kind === 'find') && ev.event === 'result' && ev.job_id) setOpen({ jobId: ev.job_id, clip: 0 })
          if (r.kind === 'render' && cur) loadClip(cur.jobId, cur.clip)
        }
      }),
    [refreshJobs, loadClip]
  )

  /** Apply an edit locally at once; persist it after a short pause (sliders). */
  const update = useCallback((next: ClipSpecInput, reason: string) => {
    const cur = openRef.current
    if (!cur) return
    setSpec(next)
    setSaving(true)
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
      } finally {
        if (!pending.current) setSaving(false)
      }
    }, SAVE_DELAY)
  }, [])

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

  const startJob = useCallback(async (kind: 'cut' | 'find', args: CutArgs | FindArgs) => {
    setRun({ kind, fraction: 0, message: 'Starting…' })
    setOpen(null)
    setScreen('home')
    try {
      await invoke(kind === 'cut' ? 'studio_cut' : 'studio_find', { ...args })
    } catch (e) {
      setRun((r) => (r ? { ...r, error: String((e as Error).message ?? e) } : r))
    }
  }, [])

  const goHome = () => {
    setOpen(null)
    setScreen('home')
    refreshJobs()
  }

  // Which of Video → Edit → Render → Share we're on.
  const latest = data?.history[data.history.length - 1]?.version ?? 0
  const rendering = !!(run?.kind === 'render' && open && run.jobId === open.jobId && run.clip === open.clip && !run.error)
  const step: Step | null = open ? (rendering ? 'Render' : data?.render && data.render.spec_version === latest ? 'Share' : 'Edit') : screen === 'new' ? 'Video' : null
  const jobBusy = (run?.kind === 'cut' || run?.kind === 'find') && !run.error

  return (
    <div className="app">
      <TopBar
        step={step}
        open={open}
        title={data?.title ?? null}
        style={spec?.captions?.style ?? null}
        jobs={jobs}
        saving={saving}
        canUndo={(data?.history.length ?? 0) > 1}
        theme={theme}
        engine={ai ? (ai.providers.find((p) => p.id === ai.provider)?.kind === 'cli' ? 'Claude Code' : ai.model) : null}
        onAi={() => setAiOpen(true)}
        onHome={goHome}
        onOpen={(jobId, clip) => setOpen({ jobId, clip })}
        onUndo={undo}
      />

      {aiOpen && (
        <AiSettings
          onClose={() => setAiOpen(false)}
          onSaved={(s) => {
            setAi(s)
            if (open) loadClip(open.jobId, open.clip) // the chat shows the new engine
          }}
        />
      )}

      {error && (
        <div className="toast" onClick={() => setError(null)} title="Dismiss">
          <span>
            <b>Something went wrong.</b> {error}
          </span>
          <span className="muted">✕</span>
        </div>
      )}

      {open ? (
        data && spec ? (
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
          <div className="home">
            <span className="muted">Opening clip…</span>
          </div>
        )
      ) : screen === 'new' ? (
        <NewClip busy={jobBusy} onCut={(a) => startJob('cut', a)} onFind={(a) => startJob('find', a)} />
      ) : (
        <Home
          jobs={jobs}
          loadError={loadError}
          run={run}
          onOpen={(jobId, clip) => setOpen({ jobId, clip })}
          onNew={() => setScreen('new')}
          onFind={(a) => startJob('find', a)}
          onDismissRun={() => setRun(null)}
          onRetry={refreshJobs}
        />
      )}
    </div>
  )
}

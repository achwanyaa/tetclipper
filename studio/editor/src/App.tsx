import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClipSpecInput } from '@tetclipper/composition'
import { authConfig, fileUrl, invoke, isAwake, onEvent, onWake, setAuth, setWorking, type AiSettings as AiSettingsData, type ClipData, type JobSummary, type ReviewItem, type ReviewStatus, type ReviewSummary, type Role } from './api'
import { signOut, useSession } from './auth'
import { AiSettings } from './components/AiSettings'
import { Canvas } from './components/Canvas'
import { Home } from './components/Home'
import { NewClip, type CutArgs, type LongArgs, type FindArgs } from './components/NewClip'
import { Record } from './components/Record'
import { Review } from './components/Review'
import { SignIn } from './components/SignIn'
import { TopBar, type Step } from './components/TopBar'
import { useTheme } from './theme'

export interface Run {
  kind: 'cut' | 'find' | 'render'
  title?: string
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

interface Me {
  mode: 'none' | 'supabase'
  user: { id: string; email: string } | null
  admin: boolean
  role?: Role
  name?: string
  media_token: string | null
}

export interface Account {
  email: string
  admin: boolean
  role: Role
  name: string
}

export type View = 'edit' | 'review' | 'record'
const REVIEW_POLL = 60 * 1000

/** Sign-in gate. The desktop app's server needs no sign-in; the online one
 *  (Supabase) shows the sign-in screen until there's a session. */
export function App() {
  const [mode, setMode] = useState<'loading' | 'none' | 'supabase' | 'token' | 'offline'>('loading')
  const [offline, setOffline] = useState<string | null>(null)
  const { session, stage, setStage } = useSession()
  const [me, setMe] = useState<Me | null>(null)
  const token = session?.access_token ?? null

  const connect = useCallback(() => {
    setMode('loading')
    authConfig()
      .then((c) => setMode(c.mode))
      .catch((e) => {
        setOffline(String(e.message ?? e))
        setMode('offline')
      })
  }, [])
  useEffect(connect, [connect])

  // Keep the API's tokens current: the access token refreshes hourly; the
  // media token (videos, live events) lasts a day, so renew it twice a day.
  useEffect(() => {
    if (mode !== 'supabase') return
    if (!token) {
      setAuth(null, null)
      setMe(null)
      return
    }
    setAuth(token, me?.media_token ?? null)
    const refresh = () =>
      invoke<Me>('me')
        .then((m) => {
          setAuth(token, m.media_token)
          setMe(m)
        })
        .catch(() => undefined)
    if (!me) refresh()
    const timer = window.setInterval(refresh, 12 * 3600 * 1000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, token])

  if (mode === 'loading' || (mode === 'supabase' && (stage === 'loading' || (stage === 'signed-in' && !me)))) {
    return (
      <div className="splash">
        <b>Connecting…</b>
        <span className="muted">The cloud is waking up. This takes a few seconds after a quiet spell.</span>
      </div>
    )
  }
  if (mode === 'offline') {
    return (
      <div className="splash">
        <b>Can't reach the tetclipper server</b>
        <span className="muted">{offline}</span>
        <button className="tonal" onClick={connect}>
          Try again
        </button>
      </div>
    )
  }
  if (mode === 'supabase' && stage === 'set-password') return <SignIn setPasswordMode onPasswordSet={() => setStage('signed-in')} />
  if (mode === 'supabase' && stage !== 'signed-in') return <SignIn />
  return (
    <Studio
      account={me?.user ? { email: me.user.email, admin: me.admin, role: me.role ?? (me.admin ? 'admin' : 'editor'), name: me.name ?? me.user.email } : null}
      onSignOut={mode === 'supabase' ? signOut : undefined}
    />
  )
}

function Studio({ account, onSignOut }: { account: Account | null; onSignOut?: () => void }) {
  const theme = useTheme()
  const isAdmin = !account || account.admin
  const role: Role = account?.role ?? 'admin' // the desktop app's one user does everything
  const [screen, setScreen] = useState<'home' | 'new'>('home')
  const [view, setView] = useState<View>('edit')
  const [reviews, setReviews] = useState<ReviewSummary[] | null>(null)
  const [reviewItem, setReviewItem] = useState<ReviewItem | null>(null) // the open clip's, if it was sent
  const [reviewFocus, setReviewFocus] = useState<{ id: string; status: ReviewStatus; n: number } | null>(null)
  const sendAfterRender = useRef<{ jobId: string; clip: number; message: string | null } | null>(null)
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

  const refreshReviews = useCallback(() => {
    invoke<ReviewSummary[]>('review_list')
      .then(setReviews)
      .catch(() => undefined)
  }, [])
  const loadReview = useCallback((jobId: string, clip: number) => {
    invoke<ReviewItem | null>('review_for_clip', { jobId, clip })
      .then((r) => {
        const cur = openRef.current
        if (cur && cur.jobId === jobId && cur.clip === clip) setReviewItem(r)
      })
      .catch(() => undefined)
  }, [])

  const loadClip = useCallback(
    async (jobId: string, clip: number) => {
      try {
        const d = await invoke<ClipData>('studio_clip', { jobId, clip })
        setData(d)
        setSpec(d.spec)
        setEditor({ playhead: null, selection: null })
        setError(null)
        loadReview(jobId, clip)
      } catch (e) {
        setError(String((e as Error).message ?? e))
      }
    },
    [loadReview]
  )

  useEffect(refreshJobs, [refreshJobs])

  // The review list: on start, when the tab comes back, and every minute while
  // someone is here (never from a hidden or idle tab, so the server can sleep).
  useEffect(() => {
    refreshReviews()
    const onVisible = () => !document.hidden && refreshReviews()
    document.addEventListener('visibilitychange', onVisible)
    const timer = window.setInterval(() => isAwake() && refreshReviews(), REVIEW_POLL)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.clearInterval(timer)
    }
  }, [refreshReviews])
  useEffect(() => {
    if (view !== 'edit') refreshReviews()
  }, [view, refreshReviews])

  /** Send the open clip's current render for review. */
  const sendForReview = useCallback(
    async (message: string | null, target?: { jobId: string; clip: number }) => {
      const cur = target ?? openRef.current
      if (!cur) return
      try {
        await invoke('review_submit', { jobId: cur.jobId, clip: cur.clip, message })
        loadReview(cur.jobId, cur.clip)
        refreshReviews()
      } catch (e) {
        setError(String((e as Error).message ?? e))
      }
    },
    [loadReview, refreshReviews]
  )
  const noteFixed = useCallback(async (noteId: string, fixed: boolean) => {
    const item = reviewItemRef.current
    if (!item) return
    // Tick at once; the server's answer (or the old state, if it fails) follows.
    setReviewItem((r) => (r && r.id === item.id ? { ...r, notes: r.notes.map((n) => (n.id === noteId ? { ...n, fixed } : n)) } : r))
    try {
      setReviewItem(await invoke<ReviewItem>('review_note_fixed', { id: item.id, noteId, fixed }))
    } catch (e) {
      setReviewItem((r) => (r && r.id === item.id ? item : r))
      setError(String((e as Error).message ?? e))
    }
  }, [])
  const reviewItemRef = useRef(reviewItem)
  reviewItemRef.current = reviewItem
  useEffect(() => {
    if (isAdmin) invoke<AiSettingsData>('ai_settings_get').then(setAi).catch(() => undefined)
  }, [isAdmin])

  // While anything runs, re-read the job list every 5 s: progress lives on the
  // server, so this works even when a live event never reaches this browser.
  const anyRunning = jobs.some((j) => j.progress?.state === 'running') || ((run?.kind === 'cut' || run?.kind === 'find') && !run.error)
  useEffect(() => {
    setWorking(anyRunning)
    if (!anyRunning) return
    const timer = window.setInterval(() => isAwake() && refreshJobs(), 5000)
    return () => window.clearInterval(timer)
  }, [anyRunning, refreshJobs])

  // A cut or find we started finished without its live "result" event: clear
  // the card and open the clip, as the event would have.
  const watched = useRef(new Set<string>())
  useEffect(() => {
    const r = runRef.current
    if (!r || r.error || (r.kind !== 'cut' && r.kind !== 'find')) {
      watched.current.clear()
      return
    }
    for (const j of jobs) if (j.progress?.state === 'running' || j.id === r.jobId) watched.current.add(j.id)
    const finished = jobs.find((j) => watched.current.has(j.id) && (j.progress?.state === 'done' || j.progress?.state === 'failed'))
    if (!finished) return
    watched.current.clear()
    setRun(null)
    if (finished.progress?.state === 'done' && finished.clips.length && !openRef.current) setOpen({ jobId: finished.id, clip: 0 })
  }, [jobs])
  useEffect(() => {
    setReviewItem(null)
    if (open) loadClip(open.jobId, open.clip)
    else {
      setData(null)
      setSpec(null)
    }
  }, [open, loadClip])

  // The light preview copy is being made: switch to it as soon as it's there.
  const waitingFor = data?.previewing ? data.jobId : null
  const waitingClip = data?.clip ?? 0
  useEffect(() => {
    if (!waitingFor) return
    const timer = window.setInterval(() => {
      if (!isAwake()) return
      invoke<{ preview: string | null; previewing: boolean }>('studio_preview', { jobId: waitingFor, clip: waitingClip })
        .then((p) => {
          if (!p.previewing) setData((d) => (d && d.jobId === waitingFor ? { ...d, preview: p.preview, previewing: false } : d))
        })
        .catch(() => undefined)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [waitingFor, waitingClip])

  // Back after a pause in the event stream: if the server restarted meanwhile the
  // gap can't be replayed, so re-read what could have changed.
  const dataRef = useRef(data)
  dataRef.current = data
  useEffect(
    () =>
      onWake(async () => {
        refreshJobs()
        const cur = openRef.current
        if (!cur || pending.current) return
        try {
          const d = await invoke<ClipData>('studio_clip', { jobId: cur.jobId, clip: cur.clip })
          const was = dataRef.current
          const changed =
            !was ||
            was.history[was.history.length - 1]?.version !== d.history[d.history.length - 1]?.version ||
            was.chat.messages.length !== d.chat.messages.length ||
            was.chat.busy !== d.chat.busy
          if (changed && !pending.current && openRef.current === cur) {
            setData(d)
            setSpec(d.spec)
          }
        } catch {
          /* the next edit or reload will surface it */
        }
      }),
    [refreshJobs]
  )

  // Server events: live spec changes (AI, undo), pipeline progress.
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
          const send = sendAfterRender.current
          const sendThis = r.kind === 'render' && send && send.jobId === r.jobId && send.clip === r.clip
          if (sendThis) sendAfterRender.current = null
          if (!ok) {
            setRun({ ...r, error: err ?? 'failed', fraction: 1 })
            return
          }
          setRun(null)
          if ((r.kind === 'cut' || r.kind === 'find') && ev.event === 'result' && ev.job_id) setOpen({ jobId: ev.job_id, clip: 0 })
          if (r.kind === 'render' && cur) loadClip(cur.jobId, cur.clip)
          // "Render and send for review again": the render is done, send it.
          if (sendThis && send) sendForReview(send.message, { jobId: send.jobId, clip: send.clip })
        }
      }),
    [refreshJobs, loadClip, sendForReview]
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
      sendAfterRender.current = null
      setRun((r) => (r ? { ...r, error: String((e as Error).message ?? e) } : r))
    }
  }, [open])
  /** Render, then send for review when the render is done. If the tab closes
   *  first, "Send for review" is simply there next time. */
  const renderAndSend = useCallback(
    (message: string | null) => {
      if (!open) return
      sendAfterRender.current = { ...open, message }
      startRender()
    },
    [open, startRender]
  )

  const startJob = useCallback(async (kind: 'cut' | 'find' | 'long', args: CutArgs | FindArgs | LongArgs) => {
    setRun(kind === 'long' ? { kind: 'cut', title: 'Preparing the full video', fraction: 0, message: 'Starting…' } : { kind, fraction: 0, message: 'Starting…' })
    setOpen(null)
    setScreen('home')
    try {
      await invoke(kind === 'long' ? 'studio_long' : kind === 'cut' ? 'studio_cut' : 'studio_find', { ...args })
    } catch (e) {
      setRun((r) => (r ? { ...r, error: String((e as Error).message ?? e) } : r))
    }
  }, [])

  const goHome = () => {
    setOpen(null)
    setScreen('home')
    setView('edit')
    refreshJobs()
  }
  const openClip = (jobId: string, clip: number) => {
    setView('edit')
    setOpen({ jobId, clip })
  }
  const reviewer = role === 'admin' || role === 'reviewer'
  // The count beside Review: videos waiting for the team, or your own sent back.
  const reviewCount = (reviews ?? []).filter((i) => (reviewer ? i.status === 'to_review' : i.status === 'needs_work')).length

  // Which of Video → Edit → Render → Share we're on.
  const latest = data?.history[data.history.length - 1]?.version ?? 0
  const rendering = !!(run?.kind === 'render' && open && run.jobId === open.jobId && run.clip === open.clip && !run.error)
  const editing = view === 'edit'
  const step: Step | null = !editing ? null : open ? (rendering ? 'Render' : data?.render && data.render.spec_version === latest ? 'Share' : 'Edit') : screen === 'new' ? 'Video' : null
  const jobBusy = (run?.kind === 'cut' || run?.kind === 'find') && !run.error

  return (
    <div className="app">
      <TopBar
        step={step}
        open={editing ? open : null}
        view={view}
        onView={(v) => {
          setView(v)
          if (v === 'edit' && !open) setScreen('home')
        }}
        reviewCount={reviewCount}
        title={data?.title ?? null}
        style={spec?.captions?.style ?? null}
        jobs={jobs}
        saving={saving}
        canUndo={(data?.history.length ?? 0) > 1}
        theme={theme}
        engine={ai ? (ai.providers.find((p) => p.id === ai.provider)?.kind === 'cli' ? ai.providers.find((p) => p.id === ai.provider)?.label ?? 'AI' : ai.model) : null}
        onAi={() => setAiOpen(true)}
        account={account}
        onSignOut={onSignOut}
        onHome={goHome}
        onOpen={openClip}
        onUndo={undo}
        render={
          editing && open && data
            ? rendering
              ? { state: 'rendering', pct: Math.round((run?.fraction ?? 0) * 100) }
              : data.render && data.render.spec_version === latest
                ? { state: 'fresh', download: fileUrl(data.render.output, true) }
                : { state: 'idle', onRender: startRender }
            : null
        }
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

      {view === 'review' ? (
        <Review items={reviews} role={role} onChanged={refreshReviews} setError={setError} onOpenClip={reviewer ? undefined : openClip} focus={reviewFocus} />
      ) : view === 'record' ? (
        <Record
          items={reviews}
          role={role}
          onOpen={(id, status) => {
            setReviewFocus({ id, status, n: Date.now() })
            setView('review')
          }}
        />
      ) : open ? (
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
            online={!!account}
            admin={isAdmin}
            review={reviewItem}
            onSendForReview={(message) => sendForReview(message)}
            onRenderAndSend={renderAndSend}
            onNoteFixed={noteFixed}
          />
        ) : (
          <div className="home">
            <span className="muted">Opening clip…</span>
          </div>
        )
      ) : screen === 'new' ? (
        <NewClip busy={jobBusy} online={!!account} onCut={(a) => startJob('cut', a)} onFind={(a) => startJob('find', a)} onLong={(a) => startJob('long', a)} />
      ) : (
        <Home
          jobs={jobs}
          loadError={loadError}
          run={run}
          onOpen={openClip}
          onNew={() => setScreen('new')}
          onFind={(a) => startJob('find', a)}
          onDismissRun={() => setRun(null)}
          onDismissJob={(jobId) => invoke('studio_job_dismiss', { jobId }).then(refreshJobs).catch((e) => setError(String(e.message ?? e)))}
          onRetry={refreshJobs}
        />
      )}
    </div>
  )
}

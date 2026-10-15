import { useCallback, useEffect, useRef, useState } from 'react'
import { listen } from './backend'
import { api } from './api'
import type { JobResults, JobSummary, PipelineEvent, SetupState } from './types'
import Onboarding from './components/Onboarding'
import Studio from './components/Studio'
import Review from './components/Review'
import Loop from './components/Loop'
import RangePicker from './components/RangePicker'
import Chat from './components/Chat'
import { AUTH_REQUIRED, login, onStreamOpen } from './backend'
import './styles.css'

type View = 'boot' | 'login' | 'onboarding' | 'studio' | 'review' | 'loop' | 'range' | 'chat'

function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState('')
  const [bad, setBad] = useState(false)
  const submit = async () => {
    if (!token.trim()) return
    if (await login(token.trim())) onDone()
    else setBad(true)
  }
  return (
    <div className="onboarding">
      <div className="grain" />
      <section className="ob-step">
        <p className="ob-kicker">tetclipper</p>
        <h2 className="ob-h2">Access token</h2>
        <p className="ob-body">This deployment is private. Paste the token you set when deploying it.</p>
        <div className="ob-key-row">
          <input
            type="password"
            autoFocus
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
          <button className="btn-primary" onClick={submit} disabled={!token.trim()}>
            Enter
          </button>
        </div>
        {bad && <p className="ig-message mono">That token was not accepted.</p>}
      </section>
    </div>
  )
}

export default function App() {
  const [view, setView] = useState<View>('boot')
  const [setup, setSetup] = useState<SetupState | null>(null)
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [activeJob, setActiveJob] = useState<string | null>(null)
  // The range picker's job, and whether review should open on the newest clip.
  const [rangeJob, setRangeJob] = useState<string | null>(null)
  const [focusLast, setFocusLast] = useState(false)
  const [chatJob, setChatJob] = useState<{ id: string; title: string | null } | null>(null)
  const [results, setResults] = useState<JobResults | null>(null)
  const [stages, setStages] = useState<Record<string, { fraction: number; message: string }>>({})
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  // A job paused for the Claude Code brain (llm "claude"): see scoring/brain.py.
  const [awaiting, setAwaiting] = useState<{ jobId: string; count: number; purpose: string } | null>(null)
  const unlistenRef = useRef<(() => void) | null>(null)
  const runningRef = useRef(false)
  const startedAt = useRef(0)
  runningRef.current = running
  const activeJobRef = useRef<string | null>(null)
  activeJobRef.current = activeJob

  const refreshJobs = useCallback(() => {
    api.listJobs().then(setJobs).catch(() => setJobs([]))
  }, [])

  const boot = useCallback(() => {
    api
      .setupState()
      .then((s) => {
        setSetup(s)
        setView(s.onboarded ? 'studio' : 'onboarding')
        refreshJobs()
      })
      .catch((err) => {
        if (err === AUTH_REQUIRED) setView('login')
      })
  }, [refreshJobs])

  useEffect(boot, [boot])

  // Instagram loop: opportunistic sync on launch + hourly while open
  // (decision #12 — no background process, the app's own uptime is the
  // schedule). Fire-and-forget; the Loop screen re-reads on entry.
  useEffect(() => {
    const kick = () => {
      api
        .igStatus()
        .then((s) => (s.connected ? api.igSync() : null))
        .catch(() => null)
    }
    kick()
    const timer = window.setInterval(kick, 60 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    let disposed = false
    listen<PipelineEvent>('pipeline-event', ({ payload }) => {
      if (payload.event === 'job' && payload.job_id) {
        setActiveJob(payload.job_id)
        setResults(null)
      } else if (payload.event === 'progress' && payload.stage) {
        setStages((prev) => ({
          ...prev,
          [payload.stage!]: {
            fraction: payload.fraction ?? -1,
            message: payload.message ?? ''
          }
        }))
      } else if (payload.event === 'result') {
        setRunning(false)
        refreshJobs()
        if (payload.ok && activeJobRef.current) {
          setFocusLast(payload.manual === true)
          api.jobResults(activeJobRef.current).then((r) => {
            setResults(r)
            setView('review')
          })
        } else if (payload.awaiting === 'brain' && payload.job_id) {
          setAwaiting({
            jobId: payload.job_id,
            count: Number(payload.pending ?? 0),
            purpose: String(payload.purpose ?? '')
          })
        } else if (!payload.ok) {
          setRunError(String(payload.error ?? 'Pipeline failed'))
        }
      } else if (payload.event === 'exited') {
        setRunning(false)
        setRunError('The pipeline exited unexpectedly. Resume the job to continue from its last checkpoint.')
      }
    }).then((un) => {
      if (disposed) un()
      else unlistenRef.current = un
    })
    return () => {
      disposed = true
      unlistenRef.current?.()
    }
  }, [refreshJobs])

  // The "result" event can be lost (dropped connection, a cloud container
  // restarted mid-run). While a run is showing, ask the server whether
  // anything is actually still running: on every stream (re)connect and
  // every 30 s. Nothing alive → stop showing WORKING and say so.
  useEffect(() => {
    const check = () => {
      if (!runningRef.current || Date.now() - startedAt.current < 8000) return
      api
        .pipelineActive()
        .then(({ running: alive }) => {
          if (alive > 0 || !runningRef.current) return
          setRunning(false)
          refreshJobs()
          setRunError(
            'Nothing is running on the server any more (it may have restarted). ' +
              'The session list shows how far it got; resume it to continue from the last checkpoint.'
          )
        })
        .catch(() => null) // desktop shell / offline: keep waiting for events
    }
    const stop = onStreamOpen(check)
    const timer = window.setInterval(check, 30_000)
    return () => {
      stop()
      window.clearInterval(timer)
    }
  }, [refreshJobs])

  useEffect(() => {
    if (running) startedAt.current = Date.now()
  }, [running])

  // A run that fails to start (bad source, server error): put the studio
  // back to idle and show why.
  const failStart = useCallback((err: unknown) => {
    setRunning(false)
    setRunError(String(err))
  }, [])

  const startRun = useCallback(
    async (source: string, llm: string, captions: string, language?: string) => {
      setRunning(true)
      setRunError(null)
      setAwaiting(null)
      setStages({})
      setResults(null)
      setActiveJob(null)
      await api.runJob(source, llm, captions, language).catch(failStart)
    },
    [failStart]
  )

  const openJob = useCallback(async (jobId: string) => {
    const r = await api.jobResults(jobId)
    setActiveJob(jobId)
    setResults(r)
    if (r.render?.outputs?.length) setView('review')
  }, [])

  if (view === 'boot') return <div className="boot" />

  if (view === 'login') return <Login onDone={boot} />

  if (view === 'onboarding' && setup) {
    return (
      <Onboarding
        onDone={() => {
          api.markOnboarded()
          setSetup({ ...setup, onboarded: true })
          setView('studio')
        }}
      />
    )
  }

  if (view === 'loop') {
    return <Loop onBack={() => setView('studio')} />
  }

  if (view === 'chat' && chatJob) {
    return (
      <Chat
        key={chatJob.id}
        jobId={chatJob.id}
        title={chatJob.title}
        onBack={() => setView(results?.job_id === chatJob.id ? 'review' : 'studio')}
        onOpenNewest={() =>
          api.jobResults(chatJob.id).then((r) => {
            setActiveJob(chatJob.id)
            setResults(r)
            setFocusLast(true)
            setView('review')
          })
        }
      />
    )
  }

  if (view === 'range' && rangeJob) {
    return (
      <RangePicker
        key={rangeJob}
        jobId={rangeJob}
        onBack={() => setView(results?.job_id === rangeJob ? 'review' : 'studio')}
        onCut={() => {
          setActiveJob(rangeJob)
          setRunning(true)
        }}
      />
    )
  }

  if (view === 'review' && results) {
    return (
      <Review
        key={`${results.job_id}-${results.render?.outputs?.length ?? 0}`}
        results={results}
        initialSelected={focusLast ? Math.max(0, (results.render?.outputs?.length ?? 1) - 1) : 0}
        onPickRange={() => {
          setRangeJob(results.job_id)
          setView('range')
        }}
        onChat={() => {
          setChatJob({ id: results.job_id, title: results.ingest?.title ?? null })
          setView('chat')
        }}
        onBack={() => {
          setView('studio')
          refreshJobs()
        }}
        onRestyle={(captions, camera) => {
          setRunning(true)
          setRunError(null)
          setStages({})
          setActiveJob(results.job_id)
          setView('studio')
          api.resumeJob(results.job_id, undefined, captions, camera).catch(failStart)
        }}
      />
    )
  }

  return (
    <Studio
      jobs={jobs}
      running={running}
      stages={stages}
      error={runError}
      awaiting={awaiting}
      onRun={startRun}
      onOpenLoop={() => setView('loop')}
      onOpenJob={openJob}
      onPickRange={(id) => {
        setRangeJob(id)
        setView('range')
      }}
      onChat={(id, title) => {
        setChatJob({ id, title })
        setView('chat')
      }}
      onCut={(source, start, end, captions, language) => {
        setRunning(true)
        setRunError(null)
        setAwaiting(null)
        setStages({})
        setResults(null)
        setActiveJob(null)
        api.cutRange(source, start, end, captions, language).catch(failStart)
      }}
      onPush={(source, llm, captions) => {
        setRunning(true)
        setRunError(null)
        setAwaiting(null)
        setStages({})
        setResults(null)
        setActiveJob(null)
        api.pushJob(source, llm, captions).catch(failStart)
      }}
      onPull={(id) => {
        setRunning(true)
        setRunError(null)
        setAwaiting(null)
        setStages({})
        setActiveJob(id)
        api.pullJob(id).catch(failStart)
      }}
      onResume={(id, llm) => {
        setRunning(true)
        setRunError(null)
        setAwaiting(null)
        setStages({})
        setActiveJob(id)
        api.resumeJob(id, llm).catch(failStart)
      }}
    />
  )
}

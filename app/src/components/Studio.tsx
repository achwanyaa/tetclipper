import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { onFileDrop, openDialog, openUrl } from '../backend'
import { VIDEO_EXTENSIONS, isVideoPath, pickVideo } from '../files'
import { parseTime } from './RangePicker'
import type { JobSummary, RemoteJobs, UpdateNotice } from '../types'
import KeyModal from './KeyModal'

const BRAINS: [string, string][] = [
  ['claude', 'claude code'],
  ['gemini', 'my Gemini key'],
  ['ollama', 'ollama']
]

const STAGE_ORDER = [
  'download', 'upload', 'pull', 'ingest', 'asr', 'diarize', 'events', 'candidates', 'score', 'camera', 'render'
]

// Only shown when a run actually does them (push / pull / hybrid).
const OPTIONAL_STAGES = new Set(['download', 'upload', 'pull'])

const STAGE_LABELS: Record<string, string> = {
  download: 'DOWNLOAD',
  upload: 'UPLOAD',
  pull: 'PULL',
  ingest: 'INGEST',
  asr: 'TRANSCRIBE',
  diarize: 'SPEAKERS',
  events: 'LISTEN',
  candidates: 'SCAN',
  score: 'JUDGE',
  camera: 'DIRECT',
  render: 'RENDER'
}

const CAPTION_PRESETS = ['classic', 'beast', 'hormozi', 'minimal', 'karaoke-pop']

interface Props {
  jobs: JobSummary[]
  running: boolean
  stages: Record<string, { fraction: number; message: string }>
  error: string | null
  awaiting: { jobId: string; count: number; purpose: string } | null
  onRun: (source: string, llm: string, captions: string, language?: string) => void
  onOpenLoop: () => void
  onOpenJob: (id: string) => void
  onResume: (id: string, llm?: string) => void
  onPickRange: (id: string) => void
  onPull: (id: string) => void
  onChat: (id: string, title: string | null) => void
  onPush: (source: string, llm: string, captions: string) => void
  onCut: (source: string, start: number, end: number, captions: string, language?: string) => void
}

export default function Studio({
  jobs, running, stages, error, awaiting, onRun, onOpenLoop, onOpenJob, onResume, onPickRange, onPull, onChat, onPush, onCut
}: Props) {
  // Range mode: when both are filled, only that part of the video is
  // fetched and cut (fast, runs here); empty = the full find-the-moments run.
  const [fromText, setFromText] = useState('')
  // Speech language: auto-detect misreads short slices of mixed English /
  // Swahili, so English is the default; remembered between visits.
  const [language, setLanguage] = useState<string>(() => {
    try {
      return localStorage.getItem('tetclipper.language') ?? 'en'
    } catch {
      return 'en'
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('tetclipper.language', language)
    } catch {
      /* private window: just don't remember */
    }
  }, [language])
  const [toText, setToText] = useState('')
  // Where a new run goes: here, or the hosted GPU (downloaded here first,
  // because YouTube blocks cloud IPs). Only offered when a cloud is set up.
  const [runOn, setRunOn] = useState<'local' | 'cloud'>('local')
  // Hosted (GPU) jobs that analyse in the cloud and render on this machine.
  const [cloud, setCloud] = useState<RemoteJobs | null>(null)
  useEffect(() => {
    if (running) return
    api.remoteJobs().then(setCloud).catch(() => setCloud(null))
  }, [running, jobs])
  const [source, setSource] = useState('')
  const [llm, setLlm] = useState('claude')
  const [captions, setCaptions] = useState('classic')
  const [showKey, setShowKey] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  // A newer build exists (one GET on launch; offline this stays null).
  const [update, setUpdate] = useState<UpdateNotice | null>(null)
  useEffect(() => {
    api
      .checkUpdate()
      .then((u) => setUpdate(u.update_available ? u : null))
      .catch(() => {})
  }, [])
  const pickedBrain = useRef(false)
  // The drag-drop listener is registered once; it reads this instead of
  // re-subscribing (and missing a drop) every time a run starts or ends.
  const runningRef = useRef(running)
  runningRef.current = running

  const chooseFile = useCallback(async () => {
    try {
      const picked = await openDialog({
        multiple: false,
        directory: false,
        filters: [{ name: 'Video', extensions: VIDEO_EXTENSIONS }],
        onProgress: (f) => setNotice(`Uploading… ${Math.round(f * 100)}%`)
      })
      if (typeof picked === 'string') {
        setSource(picked)
        setNotice(null)
      }
    } catch (err) {
      setNotice(`Couldn't open the file picker: ${String(err)}`)
    }
  }, [])

  // Desktop: Tauri hands over the dropped file's path. Browser: the file is
  // uploaded first and the server path comes back (see backend.onFileDrop).
  useEffect(() => {
    let unlisten: (() => void) | undefined
    let disposed = false
    onFileDrop((drag) => {
      if (drag.type === 'uploading') {
        setDragging(false)
        setNotice(`Uploading ${drag.name}… ${Math.round(drag.fraction * 100)}%`)
      } else if (drag.type === 'enter' || drag.type === 'over') {
        if (!runningRef.current) setDragging(true)
      } else if (drag.type === 'leave') {
        setDragging(false)
      } else if (drag.type === 'drop') {
        setDragging(false)
        if (runningRef.current) return
        const video = pickVideo(drag.paths)
        if (video) {
          setSource(video)
          setNotice(null)
        } else {
          setNotice("That isn't a video file. Drop an MP4, MOV, MKV or WEBM.")
        }
      }
    }, isVideoPath)
      .then((stop) => {
        if (disposed) stop()
        else unlisten = stop
      })
      .catch(() => {})
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [])

  const rangeFrom = fromText.trim() ? parseTime(fromText) : null
  const rangeTo = toText.trim() ? parseTime(toText) : null
  const rangeMode = fromText.trim() !== '' || toText.trim() !== ''
  const rangeError = !rangeMode
    ? null
    : source.trim() === ''
      ? "Paste the video's YouTube link (or choose a file) above first."
      : rangeFrom == null || rangeTo == null
      ? 'Fill both times, like 12:30 and 13:15.'
      : rangeTo - rangeFrom < 3
        ? 'The end must be at least 3 s after the start.'
        : rangeTo - rangeFrom > 600
          ? 'A range can be at most 10 minutes.'
          : null
  const canRun =
    !running && source.trim() !== '' && (!rangeMode || rangeError == null)
  const go = () => {
    if (!canRun) return
    if (rangeMode && rangeFrom != null && rangeTo != null) onCut(source.trim(), rangeFrom, rangeTo, captions, language)
    else if (runOn === 'cloud') onPush(source.trim(), llm, captions)
    else onRun(source.trim(), llm, captions, language)
  }

  return (
    <div className="studio">
      <div className="grain" />
      {update && (
        <section className="notice-banner update-banner">
          <span className="led led-half" />
          <div>
            <strong>tetclipper {update.latest} is out.</strong> You have {update.current}.
            <div className="notice-actions">
              <button className="btn-secondary" onClick={() => openUrl(update.url)}>
                Download
              </button>
              <button className="btn-ghost" onClick={() => setUpdate(null)}>
                Later
              </button>
            </div>
          </div>
        </section>
      )}
      {showKey && (
        <KeyModal
          onClose={() => {
            setShowKey(false)
          }}
        />
      )}
      <aside className="rail">
        <header className="rail-brand">
          <span className="rail-logo">tetclipper</span>
          <span className="rail-sub">the clipper that shows its work</span>
        </header>
        <div className="rail-jobs">
          <p className="rail-label">SESSIONS</p>
          {jobs.length === 0 && <p className="rail-empty">nothing yet</p>}
          {jobs.map((job) => (
            <div className="rail-row" key={job.id}>
              <button
                className={`rail-job ${job.rendered ? '' : 'partial'}`}
                onClick={() => (job.rendered ? onOpenJob(job.id) : onResume(job.id, llm))}
                disabled={running || job.pull_only}
                title={
                  job.pull_only
                    ? 'Analysed on the GPU. Render it on your PC: tetclipper → CLOUD · GPU → pull & render.'
                    : job.rendered
                      ? 'open results'
                      : 'resume from checkpoint'
                }
              >
                <span className={`led ${job.rendered || job.pull_only ? 'led-on' : 'led-half'}`} />
                <span className="rail-job-title">{job.title ?? job.id}</span>
                <span className={`rail-job-hint ${job.pull_only ? 'always' : ''}`}>
                  {job.rendered ? 'open' : job.pull_only ? 'ready · pull on PC' : 'resume'}
                </span>
              </button>
              {job.ingested && (
                <button
                  className="rail-range"
                  title="chat with Claude about this video"
                  onClick={() => onChat(job.id, job.title)}
                  disabled={running}
                >
                  ✦
                </button>
              )}
              {job.ingested && (
                <button
                  className="rail-range"
                  title="pick a range by hand"
                  onClick={() => onPickRange(job.id)}
                  disabled={running}
                >
                  ✂
                </button>
              )}
            </div>
          ))}
        </div>
        {cloud?.configured && (
          <div className="rail-jobs rail-cloud">
            <p className="rail-label">CLOUD · GPU</p>
            {cloud.error && <p className="rail-empty">{cloud.error}</p>}
            {!cloud.error && cloud.jobs.length === 0 && <p className="rail-empty">nothing yet</p>}
            {cloud.jobs
              .filter((job) => !job.local)
              .map((job) => (
                <button
                  key={job.id}
                  className="rail-job partial"
                  onClick={() => onPull(job.id)}
                  disabled={running || !job.ingested}
                  title="download the analysed job and render it on this machine"
                >
                  <span className="led led-half" />
                  <span className="rail-job-title">{job.title ?? job.id}</span>
                  <span className="rail-job-hint">pull &amp; render</span>
                </button>
              ))}
          </div>
        )}
        <footer className="rail-foot">
          <button className="btn-ghost" onClick={() => setShowKey(true)}>
            ◈ brain &amp; keys
          </button>
          <button className="btn-ghost" onClick={onOpenLoop}>
            ⟳ instagram loop
          </button>
        </footer>
      </aside>

      <main className="stage-area">
        {dragging && (
          <div className="drop-overlay" aria-hidden="true">
            <span className="drop-overlay-text">DROP A VIDEO TO LOAD IT</span>
          </div>
        )}
        <section className="input-block">
          <h1 className="input-heading">
            FEED IT<span className="amber"> AN HOUR.</span>
          </h1>
          <div className="input-row">
            <input
              value={source}
              onChange={(e) => {
                setSource(e.target.value)
                setNotice(null)
              }}
              onKeyDown={(e) => e.key === 'Enter' && go()}
              placeholder="Paste a YouTube URL, or drop a video here"
              disabled={running}
            />
            <button className="btn-secondary" onClick={chooseFile} disabled={running}>
              CHOOSE FILE
            </button>
            <button
              className="btn-primary"
              onClick={go}
              disabled={!canRun}
            >
              {running ? 'WORKING' : rangeMode ? 'CUT RANGE' : 'CUT IT'}
            </button>
          </div>
          <div className="range-row">
            <span className="opt-label">range</span>
            <input
              className="mono"
              value={fromText}
              onChange={(e) => setFromText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && go()}
              placeholder="from 12:30"
              disabled={running}
            />
            <input
              className="mono"
              value={toText}
              onChange={(e) => setToText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && go()}
              placeholder="to 13:15"
              disabled={running}
            />
            <span className="range-hint mono">
              {rangeError ??
                (rangeMode && rangeFrom != null && rangeTo != null
                  ? `only this ${Math.round(rangeTo - rangeFrom)} s is downloaded and cut, on this PC` +
                    (rangeTo - rangeFrom > 180 ? ' · over 3 min: fine for TikTok, too long for Shorts/Reels' : '') +
                    (language === 'auto' ? ' · speech is on auto: short slices often get misheard, pick english or swahili' : '')
                  : 'optional: leave empty to let it find the best moments in the whole video')}
            </span>
          </div>
          {notice && <p className="input-notice mono">{notice}</p>}
          <div className="run-options">
            <div className="opt-group">
              <span className="opt-label">brain</span>
              {BRAINS.map(([mode, label]) => (
                <button
                  key={mode}
                  className={`opt ${llm === mode ? 'opt-on' : ''}`}
                  onClick={() => {
                    pickedBrain.current = true
                    setLlm(mode)
                  }}
                  disabled={running}
                >
                  {label}
                </button>
              ))}
            </div>
            {cloud?.configured && (
              <div className="opt-group">
                <span className="opt-label">run on</span>
                {(['local', 'cloud'] as const).map((where) => (
                  <button
                    key={where}
                    className={`opt ${runOn === where ? 'opt-on' : ''}`}
                    onClick={() => setRunOn(where)}
                    disabled={running}
                    title={where === 'cloud' ? 'downloads here, then the hosted GPU analyses it; pull & render when done' : 'everything on this PC'}
                  >
                    {where === 'local' ? 'this PC' : 'cloud GPU'}
                  </button>
                ))}
              </div>
            )}
            <div className="opt-group">
              <span className="opt-label">speech</span>
              {([['en', 'english'], ['sw', 'swahili'], ['auto', 'auto']] as const).map(([code, label]) => (
                <button
                  key={code}
                  className={`opt ${language === code ? 'opt-on' : ''}`}
                  onClick={() => setLanguage(code)}
                  disabled={running}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="opt-group">
              <span className="opt-label">captions</span>
              {CAPTION_PRESETS.map((preset) => (
                <button
                  key={preset}
                  className={`opt ${captions === preset ? 'opt-on' : ''}`}
                  onClick={() => setCaptions(preset)}
                  disabled={running}
                >
                  {preset}
                </button>
              ))}
            </div>
          </div>
        </section>

        {(running || Object.keys(stages).length > 0) && (
          <section className="deck">
            {STAGE_ORDER.filter((s) => stages[s] || (running && !OPTIONAL_STAGES.has(s))).map((name, i) => {
              const st = stages[name]
              const state = !st ? 'idle' : st.fraction >= 1 ? 'done' : 'live'
              return (
                <div className={`deck-row ${state}`} key={name} style={{ animationDelay: `${i * 40}ms` }}>
                  <span className="deck-name mono">{STAGE_LABELS[name] ?? name.toUpperCase()}</span>
                  <div className="deck-bar">
                    <div
                      className={`deck-fill ${st && st.fraction < 0 ? 'indeterminate' : ''}`}
                      style={
                        !st ? { width: 0 } : st.fraction >= 0 ? { width: `${Math.min(100, st.fraction * 100)}%` } : undefined
                      }
                    />
                  </div>
                  <span className="deck-msg">{st?.message ?? ''}</span>
                </div>
              )
            })}
          </section>
        )}

        {awaiting && !running && (
          <section className="notice-banner brain-wait">
            <span className="led led-half" />
            <div>
              <strong>Waiting for Claude Code.</strong> {awaiting.count}{' '}
              {awaiting.purpose === 'music-brief' ? 'music briefs' : 'moments'} to judge. In your
              Claude Code session, run:
              <pre className="mono brain-cmd">/score-clips {awaiting.jobId}</pre>
              <div className="notice-actions">
                <button
                  className="btn-secondary"
                  onClick={() => navigator.clipboard.writeText(`/score-clips ${awaiting.jobId}`)}
                >
                  Copy command
                </button>
                <button className="btn-primary" onClick={() => onResume(awaiting.jobId, 'claude')}>
                  Resume job
                </button>
              </div>
            </div>
          </section>
        )}

        {error && (
          <section className="error-block">
            <span className="led led-err" />
            {error}
          </section>
        )}
      </main>
    </div>
  )
}

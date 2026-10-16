import { useEffect, useState } from 'react'
import { CAPTION_STYLES, PRESETS } from '@tetclipper/composition'
import { fmt, invoke, parseClock, type JobSummary } from '../api'
import type { Run } from '../App'

export interface FindArgs {
  source: string
  start?: number
  end?: number
  top: number
  captions?: string
  language?: string
  cloud?: boolean
}

interface Props {
  jobs: JobSummary[]
  open: { jobId: string; clip: number } | null
  run: Run | null
  onOpen: (jobId: string, clip: number) => void
  onCut: (args: { source: string; start: number; end: number; captions: string; language: string; cloud: boolean }) => void
  onFind: (args: FindArgs) => void
  onDismissRun: () => void
}

export function Sidebar({ jobs, open, run, onOpen, onCut, onFind, onDismissRun }: Props) {
  const [source, setSource] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [style, setStyle] = useState('hormozi')
  const [language, setLanguage] = useState('en')
  const [cloudOk, setCloudOk] = useState(false)
  const [cloud, setCloud] = useState(true)
  const [mode, setMode] = useState<'range' | 'find'>('range')
  const [top, setTop] = useState(5)

  useEffect(() => {
    invoke<{ cloud: boolean }>('studio_info')
      .then((i) => setCloudOk(i.cloud))
      .catch(() => setCloudOk(false))
  }, [])

  const start = parseClock(from)
  const end = parseClock(to)
  const length = end - start
  const rangeGiven = from.trim() !== '' || to.trim() !== ''
  const valid =
    mode === 'range'
      ? source.trim() && Number.isFinite(start) && Number.isFinite(end) && length >= 3 && length <= 600
      : source.trim() && (!rangeGiven || (Number.isFinite(start) && Number.isFinite(end) && length >= 60))
  const busy = (run?.kind === 'cut' || run?.kind === 'find') && !run.error

  return (
    <aside className="sidebar">
      <div className="brand">
        tetclipper <span>studio</span>
      </div>

      <form
        className="newclip"
        onSubmit={(e) => {
          e.preventDefault()
          if (!valid || busy) return
          if (mode === 'range') onCut({ source: source.trim(), start, end, captions: style, language, cloud: cloudOk && cloud })
          else onFind({ source: source.trim(), ...(rangeGiven ? { start, end } : {}), top, captions: style, language, cloud: cloudOk && cloud })
        }}
      >
        <div className="mode">
          <button type="button" className={mode === 'range' ? 'active' : ''} onClick={() => setMode('range')}>
            Exact range
          </button>
          <button type="button" className={mode === 'find' ? 'active' : ''} onClick={() => setMode('find')} title="Claude finds the best moments for you">
            Find moments
          </button>
        </div>
        <input placeholder="YouTube link" value={source} onChange={(e) => setSource(e.target.value)} />
        <div className="row">
          <input placeholder={mode === 'range' ? 'from 12:30' : 'from (optional)'} value={from} onChange={(e) => setFrom(e.target.value)} />
          <input placeholder={mode === 'range' ? 'to 13:15' : 'to (optional)'} value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        {mode === 'find' && (
          <select value={top} onChange={(e) => setTop(+e.target.value)} title="how many clips to make">
            {[3, 5, 8, 12].map((n) => (
              <option key={n} value={n}>
                Best {n} moments
              </option>
            ))}
          </select>
        )}
        <div className="row">
          <select value={style} onChange={(e) => setStyle(e.target.value)} title="caption style">
            {CAPTION_STYLES.map((s) => (
              <option key={s} value={s}>
                {PRESETS[s].label}
              </option>
            ))}
          </select>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} title="speech language">
            <option value="en">English</option>
            <option value="sw">Swahili</option>
            <option value="auto">auto</option>
          </select>
        </div>
        <select value={cloudOk && cloud ? 'cloud' : 'local'} onChange={(e) => setCloud(e.target.value === 'cloud')} disabled={!cloudOk} title="where transcription + camera run">
          <option value="cloud">Analyse on cloud GPU</option>
          <option value="local">Analyse on this PC</option>
        </select>
        <button className="primary" disabled={!valid || busy}>
          {busy ? 'Working…' : mode === 'find' ? 'Find moments' : Number.isFinite(length) && length > 0 ? `Cut ${fmt(length)}` : 'Cut'}
        </button>
        {from && to && !valid && <small className="hint">{mode === 'range' ? 'Range must be 3 s – 10 min.' : 'Search at least a minute.'}</small>}
        {mode === 'find' && !rangeGiven && <small className="muted">No range = the whole video (long download).</small>}
      </form>

      {(run?.kind === 'cut' || run?.kind === 'find') && (
        <div className={`run ${run.error ? 'failed' : ''}`}>
          <div className="bar">
            <div style={{ width: `${Math.round(run.fraction * 100)}%` }} />
          </div>
          <small>{run.error ?? run.message}</small>
          {run.error && (
            <button className="link" onClick={onDismissRun}>
              dismiss
            </button>
          )}
        </div>
      )}

      <div className="jobs">
        {jobs.map((job) => (
          <div key={job.id} className="job">
            <div className="job-title" title={job.id}>
              {job.title}
            </div>
            {job.section && (
              <div className="job-range">
                {fmt(job.section[0])} – {fmt(job.section[1])}
              </div>
            )}
            {job.clips.length === 0 && <div className="job-range muted">no clip yet</div>}
            <button
              className="link small"
              disabled={busy}
              onClick={() => onFind({ source: job.id, top: 5 })}
              title="Claude finds the best moments in this slice (new job, reuses the analysis)"
            >
              ✦ find moments here
            </button>
            {job.clips.map((c) => (
              <button
                key={c.clip}
                title={c.summary ?? undefined}
                className={`clip ${open?.jobId === job.id && open.clip === c.clip ? 'active' : ''}`}
                onClick={() => onOpen(job.id, c.clip)}
              >
                clip {c.clip + 1}
                {c.score != null && <span className="score" title="judge score, 0-100">{Math.round(c.score)}</span>}
                <span>{c.style ? PRESETS[c.style as keyof typeof PRESETS]?.label ?? c.style : ''}</span>
                {c.rendered && <span className="dot" title="rendered" />}
              </button>
            ))}
          </div>
        ))}
      </div>
    </aside>
  )
}

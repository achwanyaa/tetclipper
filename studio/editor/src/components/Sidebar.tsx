import { useEffect, useState } from 'react'
import { CAPTION_STYLES, PRESETS } from '@tetclipper/composition'
import { fmt, invoke, parseClock, type JobSummary } from '../api'
import type { Run } from '../App'

interface Props {
  jobs: JobSummary[]
  open: { jobId: string; clip: number } | null
  run: Run | null
  onOpen: (jobId: string, clip: number) => void
  onCut: (args: { source: string; start: number; end: number; captions: string; language: string; cloud: boolean }) => void
  onDismissRun: () => void
}

export function Sidebar({ jobs, open, run, onOpen, onCut, onDismissRun }: Props) {
  const [source, setSource] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [style, setStyle] = useState('hormozi')
  const [language, setLanguage] = useState('en')
  const [cloudOk, setCloudOk] = useState(false)
  const [cloud, setCloud] = useState(true)

  useEffect(() => {
    invoke<{ cloud: boolean }>('studio_info')
      .then((i) => setCloudOk(i.cloud))
      .catch(() => setCloudOk(false))
  }, [])

  const start = parseClock(from)
  const end = parseClock(to)
  const length = end - start
  const valid = source.trim() && Number.isFinite(start) && Number.isFinite(end) && length >= 3 && length <= 600
  const busy = run?.kind === 'cut' && !run.error

  return (
    <aside className="sidebar">
      <div className="brand">
        tetclipper <span>studio</span>
      </div>

      <form
        className="newclip"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid && !busy) onCut({ source: source.trim(), start, end, captions: style, language, cloud: cloudOk && cloud })
        }}
      >
        <label>New clip</label>
        <input placeholder="YouTube link" value={source} onChange={(e) => setSource(e.target.value)} />
        <div className="row">
          <input placeholder="from 12:30" value={from} onChange={(e) => setFrom(e.target.value)} />
          <input placeholder="to 13:15" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
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
          {busy ? 'Working…' : Number.isFinite(length) && length > 0 ? `Cut ${fmt(length)}` : 'Cut'}
        </button>
        {from && to && !valid && <small className="hint">Range must be 3 s – 10 min.</small>}
      </form>

      {run?.kind === 'cut' && (
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
            {job.clips.map((c) => (
              <button
                key={c.clip}
                className={`clip ${open?.jobId === job.id && open.clip === c.clip ? 'active' : ''}`}
                onClick={() => onOpen(job.id, c.clip)}
              >
                clip {c.clip + 1}
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

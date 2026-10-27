import { useEffect, useState } from 'react'
import { CAPTION_STYLES, PRESETS } from '@tetclipper/composition'
import { fmt, invoke, parseClock } from '../api'
import { STILL } from './Home'

export interface FindArgs {
  source: string
  start?: number
  end?: number
  top: number
  captions?: string
  language?: string
  cloud?: boolean
}

export interface CutArgs {
  source: string
  start: number
  end: number
  captions: string
  language: string
  cloud: boolean
}

interface Props {
  busy: boolean
  onCut: (args: CutArgs) => void
  onFind: (args: FindArgs) => void
}

const LANGUAGES: [string, string][] = [
  ['en', 'English'],
  ['sw', 'Swahili'],
  ['auto', 'Auto']
]

/** Step 1 · Video: pick the source and the range (or ask Claude to find moments). */
export function NewClip({ busy, onCut, onFind }: Props) {
  const [source, setSource] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [style, setStyle] = useState('hormozi')
  const [allStyles, setAllStyles] = useState(false)
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
  const rangeOk = Number.isFinite(start) && Number.isFinite(end)
  const valid =
    mode === 'range'
      ? !!source.trim() && rangeOk && length >= 3 && length <= 600
      : !!source.trim() && (!rangeGiven || (rangeOk && length >= 60))
  const useCloud = cloudOk && cloud

  const submit = () => {
    if (!valid || busy) return
    if (mode === 'range') onCut({ source: source.trim(), start, end, captions: style, language, cloud: useCloud })
    else onFind({ source: source.trim(), ...(rangeGiven ? { start, end } : {}), top, captions: style, language, cloud: useCloud })
  }

  const strip = allStyles ? CAPTION_STYLES : [style, ...CAPTION_STYLES.filter((s) => s !== style)].slice(0, 5)

  return (
    <div className="make">
      <div className="make-main">
        <div className="card source-card">
          <div className="ph" />
          <input
            autoFocus
            placeholder="Paste a YouTube link or a video file path"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
        </div>
        <div className="make-stage">
          <div className="frame">
            {mode === 'range' && rangeOk && length > 0 ? (
              <>
                <b>
                  {fmt(start)} – {fmt(end)}
                </b>
                <span>{fmt(length)} long. Only this part is downloaded and analysed.</span>
              </>
            ) : mode === 'find' ? (
              <>
                <b>Find the best moments</b>
                <span>Claude reads the transcript and picks the {top} strongest moments{rangeGiven && rangeOk ? ` between ${fmt(start)} and ${fmt(end)}` : ''}.</span>
              </>
            ) : (
              <>
                <b>Pick a video and a range</b>
                <span>Paste a link above, then set the start and end on the right.</span>
              </>
            )}
            <span className="mono">16:9 source → 9:16 clip</span>
          </div>
        </div>
      </div>

      <aside className="make-side">
        <div className="body">
          <h2>Make a clip</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button className={`mode-card ${mode === 'range' ? 'on' : ''}`} onClick={() => setMode('range')}>
              Exact range<span>You pick the start and end.</span>
            </button>
            <button className={`mode-card ${mode === 'find' ? 'on' : ''}`} onClick={() => setMode('find')}>
              Find moments<span>Claude finds the best parts and scores them.</span>
            </button>
          </div>

          <div className="field">
            <div className="range-grid">
              <label className="field">
                <span className="label">From{mode === 'find' ? ' (optional)' : ''}</span>
                <input placeholder="12:30" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label className="field">
                <span className="label">To{mode === 'find' ? ' (optional)' : ''}</span>
                <input placeholder="13:15" value={to} onChange={(e) => setTo(e.target.value)} />
              </label>
            </div>
            {from && to && !valid && source.trim() && (
              <span className="small hint">{mode === 'range' ? 'The range must be 3 s – 10 min.' : 'Search at least a minute.'}</span>
            )}
            {mode === 'find' && !rangeGiven && <span className="small muted">No range means the whole video (a long download).</span>}
          </div>

          {mode === 'find' && (
            <div className="field">
              <span className="label">How many</span>
              <div className="seg">
                {[3, 5, 8, 12].map((n) => (
                  <button key={n} className={top === n ? 'on' : ''} onClick={() => setTop(n)}>
                    Best {n}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="field">
            <span className="label">Caption style</span>
            <div className={`style-strip ${allStyles ? 'all' : ''}`}>
              {strip.map((s) => (
                <button key={s} className={s === style ? 'on' : ''} title={PRESETS[s as keyof typeof PRESETS].blurb} onClick={() => setStyle(s)}>
                  <img src={STILL(s)} alt={PRESETS[s as keyof typeof PRESETS].label} />
                  {allStyles && <span className="lbl">{PRESETS[s as keyof typeof PRESETS].label}</span>}
                </button>
              ))}
            </div>
            <span className="small muted">
              {PRESETS[style as keyof typeof PRESETS].label} · {PRESETS[style as keyof typeof PRESETS].blurb}{' '}
              <button className="link small" onClick={() => setAllStyles((a) => !a)}>
                {allStyles ? 'fewer' : `all ${CAPTION_STYLES.length}`}
              </button>
            </span>
          </div>

          <div className="field">
            <span className="label">Speech language</span>
            <div className="seg">
              {LANGUAGES.map(([code, label]) => (
                <button key={code} className={language === code ? 'on' : ''} onClick={() => setLanguage(code)}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {cloudOk && (
            <div className="field">
              <span className="label">Analyse on</span>
              <div className="seg">
                <button className={cloud ? 'on' : ''} onClick={() => setCloud(true)}>
                  Cloud GPU
                </button>
                <button className={!cloud ? 'on' : ''} onClick={() => setCloud(false)}>
                  This PC
                </button>
              </div>
            </div>
          )}
        </div>
        <div className="make-foot">
          <button className="primary lg" disabled={!valid || busy} onClick={submit}>
            {busy ? 'Working…' : mode === 'find' ? `Find ${top} moments` : rangeOk && length > 0 ? `Cut ${fmt(length).replace(/\.0$/, '')} clip` : 'Cut clip'}
          </button>
          <span className="small muted" style={{ textAlign: 'center' }}>
            {busy ? 'Another job is running. It shows on All clips.' : 'Takes about 1–3 minutes. You can leave this page.'}
          </span>
        </div>
      </aside>
    </div>
  )
}

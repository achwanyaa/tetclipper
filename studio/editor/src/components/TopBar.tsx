import { useState } from 'react'
import type { JobSummary } from '../api'
import { STILL, clipName } from './Home'

export type Step = 'Video' | 'Edit' | 'Render' | 'Share'
const STEPS: Step[] = ['Video', 'Edit', 'Render', 'Share']

interface Props {
  step: Step | null
  open: { jobId: string; clip: number } | null
  title: string | null
  style: string | null
  jobs: JobSummary[]
  saving: boolean
  canUndo: boolean
  theme: { toggle: () => void }
  engine: string | null
  onAi: () => void
  account: { email: string; admin: boolean } | null
  onSignOut?: () => void
  onHome: () => void
  onOpen: (jobId: string, clip: number) => void
  onUndo: () => void
}

export function TopBar({ step, open, title, style, jobs, saving, canUndo, theme, engine, onAi, account, onSignOut, onHome, onOpen, onUndo }: Props) {
  const [picker, setPicker] = useState(false)
  const [menu, setMenu] = useState(false)
  const job = open ? jobs.find((j) => j.id === open.jobId) : undefined
  const at = step ? STEPS.indexOf(step) : -1

  return (
    <header className="topbar">
      <button className="logo" onClick={onHome} title="All clips">
        tetclipper
      </button>

      {open && title ? (
        <button className="clip-picker" onClick={() => setPicker((p) => !p)}>
          <img src={STILL(style ?? 'hormozi')} alt="" />
          <span className="name">
            {title} · {job ? clipName(job.clips.find((c) => c.clip === open.clip) ?? { clip: open.clip, score: null }) : `clip ${open.clip + 1}`}
          </span>
          <span className="caret">▼</span>
        </button>
      ) : step === 'Video' ? (
        <button className="tonal" onClick={onHome}>
          ← All clips
        </button>
      ) : null}

      {step ? (
        <nav className="steps" aria-label="Progress">
          {STEPS.map((s, i) => (
            <span key={s} style={{ display: 'contents' }}>
              {i > 0 && <span className="step-line" />}
              <span className={`step ${i < at ? 'done' : i === at ? 'now' : ''}`}>
                <i>{i < at ? '✓' : i + 1}</i>
                <b>{s}</b>
              </span>
            </span>
          ))}
        </nav>
      ) : (
        <div className="spacer" />
      )}

      {open && <span className="saved">{saving ? 'Saving…' : 'Saved'}</span>}
      {open && (
        <button onClick={onUndo} disabled={!canUndo} title="Undo the last change (yours or Claude's)">
          ↶ Undo
        </button>
      )}
      {engine && (
        <button className="engine-btn" title="AI model for the chat (admin)" onClick={onAi}>
          ✦ {engine}
        </button>
      )}
      <button className="icon" title={`Switch to ${document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'} theme`} onClick={theme.toggle}>
        ◐
      </button>
      {account && (
        <button className="avatar" title={account.email} onClick={() => setMenu((m) => !m)}>
          {account.email[0]?.toUpperCase() ?? '?'}
        </button>
      )}

      {menu && account && (
        <>
          <div className="backdrop" onClick={() => setMenu(false)} />
          <div className="menu" style={{ right: 16, width: 300 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 16 }}>
              <span className="avatar" style={{ width: 40, height: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {account.email[0]?.toUpperCase()}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis' }}>{account.email}</div>
                <div className="small muted">{account.admin ? 'Admin' : 'Editor'}</div>
              </div>
            </div>
            <button
              style={{ width: '100%', justifyContent: 'flex-start', border: 'none', borderTop: '1px solid var(--ln)', borderRadius: 0, height: 46, padding: '0 16px', color: 'var(--mu)' }}
              onClick={() => {
                setMenu(false)
                onSignOut?.()
              }}
            >
              Log out
            </button>
          </div>
        </>
      )}

      {picker && open && (
        <>
          <div className="backdrop" onClick={() => setPicker(false)} />
          <div className="menu" style={{ left: 120, minWidth: 300 }}>
            <div className="menu-list">
              <button
                onClick={() => {
                  setPicker(false)
                  onHome()
                }}
              >
                ← All clips
              </button>
              {job && <div className="menu-head">{job.title}</div>}
              {job?.clips.map((c) => (
                <button
                  key={c.clip}
                  className={c.clip === open.clip ? 'on' : ''}
                  onClick={() => {
                    setPicker(false)
                    onOpen(job.id, c.clip)
                  }}
                >
                  {clipName(c)}
                  {c.score != null && <span className="tag">Score {Math.round(c.score)}</span>}
                  <span className="spacer" />
                  {c.rendered && <span className="dot ok" title="rendered" />}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </header>
  )
}

import { useEffect, useState } from 'react'
import { api } from '../api'

/**
 * Three beats: what this is → pick the brain (Claude Code preselected, your
 * own Gemini key, or local Ollama) → go. The optional Instagram feedback
 * module gets its own guided flow later (Settings → Connect Instagram), so
 * first-run stays under a minute.
 */

interface Props {
  onDone: () => void
}

export default function Onboarding({ onDone }: Props) {
  const [step, setStep] = useState(0)
  const [key, setKey] = useState('')
  const [saved, setSaved] = useState(false)
  const [ollama, setOllama] = useState<{ running: boolean; models: string[] } | null>(null)
  const [brain, setBrain] = useState<'claude' | 'gemini' | 'ollama'>('claude')

  useEffect(() => {
    api.checkOllama().then(setOllama).catch(() => setOllama({ running: false, models: [] }))
  }, [])

  async function saveKey() {
    if (!key.trim()) return
    await api.saveGeminiKey(key)
    setSaved(true)
  }

  return (
    <div className="onboarding">
      <div className="grain" />
      {step === 0 && (
        <section className="ob-step" key="s0">
          <p className="ob-kicker">tetclipper</p>
          <h1 className="ob-title">
            THE CLIPPER
            <br />
            THAT SHOWS
            <br />
            ITS WORK<span className="amber">.</span>
          </h1>
          <p className="ob-body">
            Long video in, vertical clips out. Speech, laughter, speakers, and camera
            moves are all computed <em>on this machine</em>. Moments are judged by
            your own Claude Code session — no API key — and every score comes with
            the full audit trail of how it was made.
          </p>
          <button className="btn-primary" onClick={() => setStep(1)}>
            Set it up
          </button>
        </section>
      )}
      {step === 1 && (
        <section className="ob-step" key="s1">
          <p className="ob-kicker">01 / the scoring brain</p>
          <h2 className="ob-h2">Pick how moments get judged</h2>
          <div className="ob-cards">
            <div
              className={`ob-card ${brain === 'claude' ? '' : 'dim'}`}
              onClick={() => setBrain('claude')}
            >
              <h3>Claude Code <span className="chip chip-amber">preselected</span></h3>
              <p>
                No key, no per-call cost: runs on your Claude plan. When a job reaches
                JUDGE it pauses and hands its moments to Claude Code — run{' '}
                <code>/score-clips</code> in your Claude Code session and the job carries on.
              </p>
            </div>
            <div
              className={`ob-card ${brain === 'gemini' ? '' : 'dim'} ${saved ? 'done' : ''}`}
              onClick={() => setBrain('gemini')}
            >
              <h3>Your own Gemini key</h3>
              <p>
                Prefer your own Google key? Paste it here (aistudio.google.com);
                tetclipper then talks to Google directly.
              </p>
              <div className="ob-key-row">
                <input
                  type="password"
                  placeholder="AIza…"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && saveKey()}
                />
                <button className="btn-secondary" onClick={saveKey} disabled={!key.trim()}>
                  {saved ? 'Saved ✓' : 'Save'}
                </button>
              </div>
            </div>
            <div
              className={`ob-card ${ollama?.running && brain === 'ollama' ? '' : 'dim'}`}
              onClick={() => setBrain('ollama')}
            >
              <h3>
                Ollama <span className={`led ${ollama?.running ? 'led-on' : 'led-off'}`} />
              </h3>
              <p>
                {ollama === null
                  ? 'Checking…'
                  : ollama.running
                    ? `Running locally (${ollama.models.filter((m) => !m.includes('embed')).slice(0, 2).join(', ') || 'no chat models'}). Zero cost, fully offline — scores are labeled "local estimate" because small models judge humor less reliably.`
                    : 'Not detected. Install ollama.com and pull a model (e.g. llama3.1:8b) to run fully offline.'}
              </p>
            </div>
          </div>
          <p className="ob-fine">
            You can switch per-run. Everything else — transcription, laughter
            detection, speaker tracking, rendering — is local either way.
          </p>
          <button className="btn-primary" onClick={() => setStep(2)}>
            Continue
          </button>
        </section>
      )}
      {step === 2 && (
        <section className="ob-step" key="s2">
          <p className="ob-kicker">02 / one honest warning</p>
          <h2 className="ob-h2">First run downloads the models</h2>
          <p className="ob-body">
            About <span className="mono">2.5 GB</span> of open speech and audio models,
            fetched once into <span className="mono">~/.tetclipper</span>. An hour-long
            podcast then takes a while on-device — the progress bar never lies to you,
            and every stage checkpoints, so you can quit and resume anytime.
          </p>
          <button className="btn-primary" onClick={onDone}>
            Open the studio
          </button>
        </section>
      )}
    </div>
  )
}

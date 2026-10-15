import { useEffect, useState } from 'react'
import { invoke } from '../backend'
import { api } from '../api'
import type { TelegramStatus } from '../types'

/** Post-onboarding brain + key management: your own Gemini key (optional;
 * the default brain is Claude Code), Pexels, audio sources, Telegram. */

interface Props {
  onClose: () => void
}

function PexelsField() {
  const [key, setKey] = useState('')
  const [saved, setSaved] = useState(false)
  return (
    <div className="ig-form">
      <input
        placeholder="Pexels API key (free — pexels.com/api)"
        type="password"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        className="mono"
      />
      <button
        className="btn-secondary"
        disabled={!key.trim()}
        onClick={async () => {
          await invoke('save_pexels_key', { key })
          setSaved(true)
        }}
      >
        {saved ? 'saved ✓' : 'save'}
      </button>
    </div>
  )
}

function FreesoundField() {
  const [key, setKey] = useState('')
  const [saved, setSaved] = useState(false)
  return (
    <div className="ig-form">
      <input
        placeholder="Freesound API key (free — freesound.org/apiv2/apply)"
        type="password"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        className="mono"
      />
      <button
        className="btn-secondary"
        disabled={!key.trim()}
        onClick={async () => {
          await invoke('save_freesound_key', { key })
          setSaved(true)
        }}
      >
        {saved ? 'saved ✓' : 'save'}
      </button>
    </div>
  )
}

function JamendoField() {
  const [key, setKey] = useState('')
  const [saved, setSaved] = useState(false)
  return (
    <div className="ig-form">
      <input
        placeholder="Jamendo client id (free — devportal.jamendo.com)"
        type="password"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        className="mono"
      />
      <button
        className="btn-secondary"
        disabled={!key.trim()}
        onClick={async () => {
          await invoke('save_jamendo_key', { key })
          setSaved(true)
        }}
      >
        {saved ? 'saved ✓' : 'save'}
      </button>
    </div>
  )
}

function TelegramSection() {
  const [status, setStatus] = useState<TelegramStatus | null>(null)
  const [token, setToken] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.telegramStatus().then(setStatus).catch(() => null)
  }, [])

  const run = async (fn: () => Promise<TelegramStatus>) => {
    setBusy(true)
    setNote(null)
    try {
      setStatus(await fn())
    } catch (err) {
      setNote(String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <p className="ig-intro">
        Rendered clips can go straight to a Telegram chat through a bot you own
        (make one with @BotFather).{' '}
        {status?.chat_id ? (
          <strong>Linked to {status.chat_name ?? status.chat_id} ✓</strong>
        ) : status?.has_token ? (
          <strong>Token saved — now link a chat.</strong>
        ) : null}
      </p>
      <div className="ig-form">
        <input
          placeholder={status?.has_token ? 'replace bot token…' : '123456:ABC… (from @BotFather)'}
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mono"
        />
        <button
          className="btn-secondary"
          disabled={!token.trim() || busy}
          onClick={() => run(() => api.telegramSaveToken(token)).then(() => setToken(''))}
        >
          save
        </button>
      </div>
      {status?.has_token && (
        <div className="ig-form" style={{ marginTop: 10 }}>
          <span className="ig-intro" style={{ flex: 1 }}>
            Send <span className="mono">/start</span> to{' '}
            <strong>@{status.bot_username ?? 'your bot'}</strong> in Telegram, then:
          </span>
          <button className="btn-primary" disabled={busy} onClick={() => run(api.telegramLink)}>
            {busy ? 'LINKING…' : status.chat_id ? 'RE-LINK CHAT' : 'LINK CHAT'}
          </button>
        </div>
      )}
      {note && <p className="ig-message mono">{note}</p>}
    </>
  )
}

export default function KeyModal({ onClose }: Props) {
  const [key, setKey] = useState('')
  const [hasKey, setHasKey] = useState<boolean | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    invoke<{ has_gemini_key: boolean }>('get_setup_state').then((s) =>
      setHasKey(s.has_gemini_key)
    )
  }, [])

  async function save() {
    if (!key.trim()) return
    await invoke('save_gemini_key', { key })
    setSaved(true)
    setHasKey(true)
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <p className="audit-kicker">THE BRAIN</p>
          <button className="btn-ghost" onClick={onClose}>close ✕</button>
        </header>
        <p className="audit-label" style={{ marginTop: 22 }}>YOUR OWN GEMINI KEY</p>
        <p className="ig-intro">
          Prefer your own Google key? Gemini scores at the same quality; your key lives
          in <span className="mono">~/.tetclipper/secrets.json</span>, chmod 600, and
          never goes anywhere but Google.{' '}
          {hasKey && <strong>A key is currently saved{saved ? ' — updated ✓' : ''}.</strong>}
        </p>
        <div className="ig-form">
          <input
            placeholder="AIza… (aistudio.google.com → Get API key)"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && save()}
            className="mono"
          />
          <button className="btn-primary" onClick={save} disabled={!key.trim()}>
            {saved ? 'SAVED ✓' : 'SAVE KEY'}
          </button>
        </div>
        <p className="audit-label" style={{ marginTop: 22 }}>PEXELS (STOCK VISUALS)</p>
        <PexelsField />
        <p className="audit-label" style={{ marginTop: 22 }}>FREESOUND (SOUND EFFECTS)</p>
        <FreesoundField />
        <p className="audit-label" style={{ marginTop: 22 }}>JAMENDO (MUSIC)</p>
        <JamendoField />
        <p className="audit-label" style={{ marginTop: 22 }}>TELEGRAM (DELIVERY)</p>
        <TelegramSection />
        <p className="ig-message mono">
          Applies to new runs; a job mid-flight keeps the brain it started with.
        </p>
      </div>
    </div>
  )
}

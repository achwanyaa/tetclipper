import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { listen } from '../backend'
import type { ChatMessage, PipelineEvent } from '../types'

interface Props {
  jobId: string
  title: string | null
  onBack: () => void
  /** A cut landed while chatting: open it in review. */
  onOpenNewest: () => void
}

const EXAMPLES = [
  'cut 12:30 to 13:15 with beast captions',
  'find where they talk about faith, about 45 seconds',
  'make a 30s clip of the strongest moment, hormozi captions, pan camera'
]

/** Chat with Claude Code (the user's own plan) about one video. */
export default function Chat({ jobId, title, onBack, onOpenNewest }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [live, setLive] = useState<{ kind: 'text' | 'tool'; text: string }[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [available, setAvailable] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newClip, setNewClip] = useState(false)
  const outputsBefore = useRef<number | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const load = () =>
    api.chatHistory(jobId).then((h) => {
      setMessages(h.messages)
      setAvailable(h.available)
    })

  useEffect(() => {
    load().catch((e) => setError(String(e)))
    api
      .jobResults(jobId)
      .then((r) => (outputsBefore.current = r.render?.outputs?.length ?? 0))
      .catch(() => null)
  }, [jobId])

  useEffect(() => {
    let un: (() => void) | undefined
    listen<PipelineEvent>('pipeline-event', ({ payload }) => {
      if (payload.event !== 'chat' || payload.job_id !== jobId) return
      if (payload.kind === 'text' || payload.kind === 'tool') {
        setLive((prev) => [...prev, { kind: payload.kind as 'text' | 'tool', text: String(payload.text ?? '') }])
      } else if (payload.kind === 'done') {
        setBusy(false)
        setLive([])
        load()
        // Did that turn produce a new clip?
        api
          .jobResults(jobId)
          .then((r) => {
            const n = r.render?.outputs?.length ?? 0
            if (outputsBefore.current != null && n > outputsBefore.current) setNewClip(true)
            outputsBefore.current = n
          })
          .catch(() => null)
      }
    }).then((stop) => (un = stop))
    return () => un?.()
  }, [jobId])

  useEffect(() => bottom.current?.scrollIntoView({ behavior: 'smooth' }), [messages, live])

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || busy) return
    setError(null)
    setNewClip(false)
    setBusy(true)
    setDraft('')
    setMessages((prev) => [...prev, { role: 'user', text: message, ts: Date.now() / 1000 }])
    try {
      await api.chatSend(jobId, message)
    } catch (e) {
      setBusy(false)
      setError(String(e))
    }
  }

  return (
    <div className="chat">
      <div className="grain" />
      <header className="review-head">
        <button className="btn-ghost" onClick={onBack}>
          ← back
        </button>
        <div className="review-title-block">
          <h1 className="review-title">{title ?? jobId}</h1>
          <p className="review-sub mono">chat with Claude Code · runs on your Claude plan</p>
        </div>
        <button
          className="btn-ghost review-range"
          onClick={() => api.chatReset(jobId).then(load)}
          disabled={busy || messages.length === 0}
          title="forget this conversation"
        >
          new chat
        </button>
      </header>

      <div className="chat-log">
        {!available && (
          <p className="chat-note mono">
            Chat needs the Claude Code CLI signed in on this machine. Open the local app
            (tetclipper serve on your PC) to chat.
          </p>
        )}
        {messages.length === 0 && available && (
          <div className="chat-empty">
            <p className="chat-note">
              Tell Claude what to cut: minutes, length, caption style (classic, beast, hormozi,
              minimal, karaoke-pop), camera (cut, pan, locked). It reads the transcript and makes the clip.
            </p>
            <div className="chat-examples">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="opt" onClick={() => send(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-${m.role}`}>
            {m.text}
          </div>
        ))}
        {live.map((m, i) =>
          m.kind === 'tool' ? (
            <div key={`l${i}`} className="chat-tool mono">
              → {m.text}
            </div>
          ) : (
            <div key={`l${i}`} className="chat-msg chat-assistant">
              {m.text}
            </div>
          )
        )}
        {busy && <div className="chat-tool mono chat-working">Claude is working…</div>}
        {newClip && (
          <button className="btn-primary chat-open" onClick={onOpenNewest}>
            ▶ OPEN THE NEW CLIP
          </button>
        )}
        {error && <p className="ig-message mono">{error}</p>}
        <div ref={bottom} />
      </div>

      <div className="chat-input">
        <textarea
          value={draft}
          placeholder="e.g. cut 10:23 to 12:02, hormozi captions, pan camera"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(draft)
            }
          }}
          disabled={!available}
          rows={2}
        />
        <button className="btn-primary" onClick={() => send(draft)} disabled={busy || !draft.trim() || !available}>
          {busy ? 'WORKING' : 'SEND'}
        </button>
      </div>
    </div>
  )
}

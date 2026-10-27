import { useEffect, useRef, useState } from 'react'
import { fmt, invoke, onEvent, type ChatMessage, type ClipData } from '../api'
import type { EditorState } from '../App'

const CHIPS = ['Remove the dead air', 'Make the captions bigger', 'Add a title card for the first 3 seconds', 'Fix the Swahili captions', 'Edit out stutters']

interface Props {
  data: ClipData
  editor: EditorState
  canUndo: boolean
  onUndo: () => void
}

/** Claude as a command bar under the timeline: the latest reply, the input and
 *  quick asks. The whole conversation lives in the History drawer. */
export function ClaudeBar({ data, editor, canUndo, onUndo }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>(data.chat.messages)
  const [busy, setBusy] = useState(data.chat.busy)
  const [live, setLive] = useState('')
  const [notes, setNotes] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [withContext, setWithContext] = useState(true)
  const [history, setHistory] = useState(false)

  useEffect(
    () =>
      onEvent((ev) => {
        if (ev.event !== 'studio-chat' || ev.job_id !== data.jobId || ev.clip !== data.clip) return
        if (ev.kind === 'delta') setLive((t) => t + (ev.text ?? ''))
        else if (ev.kind === 'text') {
          setMessages((m) => [...m, { role: 'assistant', text: ev.text ?? '' }])
          setLive('')
        } else if (ev.kind === 'tool') setNotes((n) => [...n.slice(-3), ev.text ?? ''])
        else if (ev.kind === 'done') {
          // API providers report the model and what the turn cost.
          if (ev.model)
            setMessages((m) => {
              const i = m.map((x) => x.role).lastIndexOf('assistant')
              return i < 0 ? m : m.map((x, k) => (k === i ? { ...x, model: ev.model, cost: ev.cost ?? null } : x))
            })
          if (ev.error) setMessages((m) => [...m, { role: 'error', text: ev.error ?? '' }])
          setBusy(false)
          setLive('')
          setNotes([])
        }
      }),
    [data.jobId, data.clip]
  )

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || busy) return
    setMessages((m) => [...m, { role: 'user', text: message }])
    setInput('')
    setBusy(true)
    try {
      await invoke('studio_chat_send', {
        jobId: data.jobId,
        clip: data.clip,
        message,
        context: withContext ? { playhead: editor.playhead, selection: editor.selection } : null
      })
    } catch (e) {
      setMessages((m) => [...m, { role: 'error', text: String((e as Error).message ?? e) }])
      setBusy(false)
    }
  }

  // Older desktop servers don't report the engine: they only run Claude Code.
  const engine = data.chat.engine ?? { provider: 'claude-code', model: '', label: 'Claude Code', ready: true }
  const last = [...messages].reverse().find((m) => m.role !== 'user')
  const ctxLabel = editor.selection ? `words ${editor.selection[0]}–${editor.selection[1]}` : editor.playhead !== null ? `at ${fmt(editor.playhead)}` : 'at start'
  const status = busy ? live.trim() || notes[notes.length - 1] || 'Claude is editing…' : last?.text ?? 'Ask Claude to change anything. It edits this clip and the preview updates live.'

  return (
    <div className="card claude-bar">
      <div className="last">
        <span className="avatar-c">C</span>
        <span className={`text ${!busy && !last ? 'mu' : ''}`} style={last?.role === 'error' && !busy ? { color: 'var(--dg)' } : undefined} title={status}>
          {status}
        </span>
        {busy && (
          <span className="typing" aria-label="Claude is working">
            <span />
            <span />
            <span />
          </span>
        )}
        <span className="who" title="The AI model the admin chose">
          {last?.model ?? (data.chat.available ? engine.label : 'not set up')}
          {!busy && last?.cost != null ? ` · $${last.cost < 0.01 ? last.cost.toFixed(4) : last.cost.toFixed(3)}` : ''}
        </span>
        {!busy && last?.role === 'assistant' && canUndo && (
          <button className="link" onClick={onUndo}>
            Undo
          </button>
        )}
        <button className="link muted" onClick={() => setHistory(true)}>
          History{messages.length ? ` (${messages.length})` : ''}
        </button>
      </div>

      {!data.chat.available && (
        <span className="warn">
          {data.chat.notice ??
            (engine.provider === 'claude-code'
              ? "Claude Code isn't installed on this machine. Install it and run `claude` once to sign in, or pick an API model under ✦ AI model."
              : `No API key is set for ${engine.label}. The admin can add one under ✦ AI model.`)}
        </span>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        <input type="text" placeholder={busy ? 'Claude is editing…' : 'Ask Claude to change anything… “make the captions bigger”'} value={input} onChange={(e) => setInput(e.target.value)} />
        <button type="button" className={`ctx ${withContext ? 'on' : ''}`} onClick={() => setWithContext((w) => !w)} title="Tell Claude where the playhead is and which words are selected">
          {withContext ? ctxLabel : 'no context'}
        </button>
        <button className="primary" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>

      {!busy && (
        <div className="chips">
          {CHIPS.map((c) => (
            <button key={c} className="chip-btn" onClick={() => send(c)}>
              {c}
            </button>
          ))}
        </div>
      )}

      {history && (
        <History
          messages={messages}
          live={live}
          notes={notes}
          busy={busy}
          onClose={() => setHistory(false)}
          onReset={async () => {
            await invoke('studio_chat_reset', { jobId: data.jobId, clip: data.clip })
            setMessages([])
          }}
        />
      )}
    </div>
  )
}

interface HistoryProps {
  messages: ChatMessage[]
  live: string
  notes: string[]
  busy: boolean
  onClose: () => void
  onReset: () => void
}

function History({ messages, live, notes, busy, onClose, onReset }: HistoryProps) {
  const [scripts, setScripts] = useState(false)
  const log = useRef<HTMLDivElement>(null)

  useEffect(() => {
    invoke<{ allow_scripts: boolean }>('studio_settings').then((s) => setScripts(s.allow_scripts)).catch(() => undefined)
  }, [])
  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight })
  }, [messages, live, notes])

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <header>
          <b>Claude · this clip</b>
          <button className="link muted" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="row small muted">
          <label className="toggle" title="Let Claude write and run Python/Node scripts on this PC (in the clip's scripts/ folder). It can then run any code your user account can, so only turn it on if you're comfortable with that.">
            <input
              type="checkbox"
              checked={scripts}
              onChange={async (e) => {
                const on = e.target.checked
                setScripts(on)
                try {
                  await invoke('studio_settings', { allow_scripts: on })
                } catch {
                  setScripts(!on)
                }
              }}
            />
            Let Claude run scripts
          </label>
          <span className="spacer" />
          <button className="sm" disabled={busy || messages.length === 0} onClick={onReset}>
            New chat
          </button>
        </div>
        <div className="log" ref={log} style={{ overflowY: 'auto' }}>
          {messages.length === 0 && !busy && <p className="muted small">No messages yet. Ask from the bar under the timeline.</p>}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              {m.text}
            </div>
          ))}
          {live && <div className="msg assistant streaming">{live}</div>}
          {busy && (
            <div className="notes">
              {notes.map((n, i) => (
                <div key={i}>{n}</div>
              ))}
              <span className="typing">
                <span />
                <span />
                <span />
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

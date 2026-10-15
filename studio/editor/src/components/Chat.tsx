import { useEffect, useRef, useState } from 'react'
import { fmt, invoke, onEvent, type ChatMessage, type ClipData } from '../api'
import type { EditorState } from '../App'

const EXAMPLES = [
  'Use sermon captions and put them a bit higher',
  'Cut the first sentence and any long pauses',
  'Add a title card for the first 3 seconds with the main point',
  'Fix any misheard words in the captions'
]

/** Chat with Claude Code about the open clip. Edits land in spec.json and
 *  show up in the preview while Claude is still talking. */
export function Chat({ data, editor }: { data: ClipData; editor: EditorState }) {
  const [messages, setMessages] = useState<ChatMessage[]>(data.chat.messages)
  const [busy, setBusy] = useState(data.chat.busy)
  const [live, setLive] = useState('') // streaming assistant text
  const [notes, setNotes] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [withContext, setWithContext] = useState(true)
  const log = useRef<HTMLDivElement>(null)

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
          if (ev.error) setMessages((m) => [...m, { role: 'error', text: ev.error ?? '' }])
          setBusy(false)
          setLive('')
          setNotes([])
        }
      }),
    [data.jobId, data.clip]
  )

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight })
  }, [messages, live, notes])

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

  const ctxLabel = [
    editor.playhead !== null && `at ${fmt(editor.playhead)}`,
    editor.selection && `words #${editor.selection[0]}–${editor.selection[1]}`
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <aside className="chat">
      <header>
        <span>Claude Code</span>
        <button
          className="link small"
          disabled={busy}
          onClick={async () => {
            await invoke('studio_chat_reset', { jobId: data.jobId, clip: data.clip })
            setMessages([])
          }}
        >
          new chat
        </button>
      </header>
      {!data.chat.available && <div className="banner error">Claude Code CLI not found on this machine. Install it and run `claude` once to log in.</div>}
      <div className="log" ref={log}>
        {messages.length === 0 && !busy && (
          <div className="examples">
            <p className="muted small">Tell Claude how you want this clip. It edits the spec and the preview updates live.</p>
            {EXAMPLES.map((ex) => (
              <button key={ex} onClick={() => send(ex)}>
                {ex}
              </button>
            ))}
          </div>
        )}
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
            <div className="typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        <textarea
          placeholder={busy ? 'Claude is editing…' : 'Describe the edit…'}
          value={input}
          rows={3}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
        />
        <div className="send-row">
          <label className="toggle small" title="Tell Claude where the playhead is and which words are selected">
            <input type="checkbox" checked={withContext} onChange={(e) => setWithContext(e.target.checked)} />
            {ctxLabel ? `include ${ctxLabel}` : 'include playhead'}
          </label>
          <button className="primary" disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
      </form>
    </aside>
  )
}

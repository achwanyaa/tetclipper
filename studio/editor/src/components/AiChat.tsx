import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { fmt, invoke } from '../api'
import type { EditorState } from '../App'
import type { Chat } from '../chat'

const CHIPS = ['Remove the dead air', 'Make the captions bigger', 'Add a title card for the first 3 seconds', 'Fix the Swahili captions', 'Edit out stutters']

interface Props {
  chat: Chat
  editor: EditorState
  lastChangeByAi: boolean // the newest saved version came from the AI: its Undo is safe to offer
  onUndo: () => void
}

const money = (c: number) => `$${c < 0.01 ? c.toFixed(4) : c.toFixed(3)}`

/** The AI tab: the whole conversation, each reply in full, and the composer. */
export function AiChat({ chat, editor, lastChangeByAi, onUndo }: Props) {
  const { messages, busy, live, notes } = chat
  const [input, setInput] = useState('')
  const [withContext, setWithContext] = useState(true)
  const [menu, setMenu] = useState(false)
  const [scripts, setScripts] = useState(false)
  const log = useRef<HTMLDivElement>(null)
  const pinned = useRef(true) // stay at the newest message unless the user scrolled up

  useEffect(() => {
    invoke<{ allow_scripts: boolean }>('studio_settings').then((s) => setScripts(s.allow_scripts)).catch(() => undefined)
  }, [])
  useLayoutEffect(() => {
    const el = log.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [messages, live, notes, busy])

  const send = (text: string) => {
    if (!text.trim() || busy) return
    pinned.current = true
    chat.send(text, withContext)
    setInput('')
  }

  const lastAi = messages.map((m) => m.role).lastIndexOf('assistant')
  const lastMessage = messages.length - 1
  const ctxLabel = editor.selection ? `words ${editor.selection[0]}–${editor.selection[1]}` : editor.playhead !== null ? `at ${fmt(editor.playhead)}` : 'at start'

  return (
    <div className="ai-chat">
      <div className="ai-chat-head">
        <span className="panel-title">AI editor</span>
        <span className="spacer" />
        <button className="sm" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
          Options
        </button>
      </div>
      {menu && (
        <div className="ai-options">
          <label
            className="toggle"
            title="Let the AI write and run Python/Node scripts on the server (in the clip's scripts/ folder). It can then run any code your account can, so only turn it on if you're comfortable with that."
          >
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
            Let the AI run scripts
          </label>
          <button
            className="sm"
            disabled={busy || messages.length === 0}
            onClick={async () => {
              await chat.reset()
              setMenu(false)
            }}
          >
            New chat
          </button>
        </div>
      )}

      <div
        className="ai-log"
        ref={log}
        aria-live="polite"
        onScroll={(e) => {
          const el = e.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
      >
        {messages.length === 0 && !busy && (
          <p className="muted small ai-empty">Ask AI to change anything in this clip. It edits the clip and the preview updates as it works.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="msg-text">{m.text}</div>
            {m.role === 'assistant' && (m.cost != null || (i === lastAi && i === lastMessage && !busy && lastChangeByAi)) && (
              <div className="msg-meta">
                {m.cost != null && <span className="mono">{money(m.cost)}</span>}
                {i === lastAi && i === lastMessage && !busy && lastChangeByAi && (
                  <button className="link small" onClick={onUndo}>
                    Undo this change
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        {live && (
          <div className="msg assistant streaming">
            <div className="msg-text">{live}</div>
          </div>
        )}
        {busy && (
          <div className="notes">
            {notes.map((n, i) => (
              <div key={i}>{n}</div>
            ))}
            <span className="typing" aria-label="AI is working">
              <span />
              <span />
              <span />
            </span>
          </div>
        )}
      </div>

      {!chat.available && <p className="warn small">{chat.notice ?? 'The AI chat is not set up yet. The admin can choose a model under ✦ AI model.'}</p>}

      {!busy && (
        <div className="chips ai-chips">
          {CHIPS.map((c) => (
            <button key={c} className="chip-btn" onClick={() => send(c)}>
              {c}
            </button>
          ))}
        </div>
      )}

      <form
        className="ai-compose"
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        <label className="sr-only" htmlFor="ai-input">
          Ask AI to change anything
        </label>
        <textarea
          id="ai-input"
          rows={2}
          placeholder={busy ? 'AI is editing…' : 'Ask AI to change anything… “make the captions bigger”'}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send(input)
            }
          }}
        />
        <div className="row">
          <button
            type="button"
            className={`ctx ${withContext ? 'on' : ''}`}
            onClick={() => setWithContext((w) => !w)}
            title="Tell the AI where the playhead is and which words are selected"
            aria-pressed={withContext}
          >
            {withContext ? ctxLabel : 'no context'}
          </button>
          <span className="spacer" />
          <button className="primary" disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
      </form>
    </div>
  )
}

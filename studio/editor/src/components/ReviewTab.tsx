import { useState } from 'react'
import { STATUS_LABEL, fmt, when, type ReviewItem } from '../api'

interface Props {
  item: ReviewItem
  fresh: boolean // the render matches the latest edit
  sentLatest: boolean // ...and that render is the one with the team
  rendering: boolean
  onJump: (seconds: number) => void // a time in the rendered video = output time
  onFixed: (noteId: string, fixed: boolean) => void
  onSend: (message: string | null) => Promise<void> | void
  onRenderAndSend: (message: string | null) => void
}

/** What the team said about this clip, inside the editor. */
export function ReviewTab({ item, fresh, sentLatest, rendering, onJump, onFixed, onSend, onRenderAndSend }: Props) {
  const [message, setMessage] = useState('')
  const decided = [...item.events].reverse().find((e) => e.kind === 'needs_work' || e.kind === 'good')
  const notes = item.notes.filter((n) => n.version === item.version)
  const open = notes.filter((n) => !n.fixed).length

  if (item.status === 'to_review') {
    return (
      <div className="review-tab">
        <span className="status-pill to_review">{STATUS_LABEL.to_review}</span>
        <div className="panel-title">With the communication team</div>
        <p className="muted">Version {item.version} was sent {when(item.versions[item.versions.length - 1]?.sentAt)}. You’ll see their notes here if it needs work.</p>
        {!sentLatest && <p className="note wn">You’ve changed the clip since you sent it. Render and send it again so they review the new version.</p>}
        {!sentLatest && <SendBox message={message} setMessage={setMessage} fresh={fresh} rendering={rendering} onSend={onSend} onRenderAndSend={onRenderAndSend} />}
      </div>
    )
  }
  if (item.status === 'good') {
    return (
      <div className="review-tab">
        <span className="status-pill good">{STATUS_LABEL.good}</span>
        <div className="panel-title">Approved</div>
        <p className="muted">
          {decided ? `${decided.by.name} marked version ${item.version} good ${when(decided.at)}.` : `Version ${item.version} is good.`} The team downloads it from Review and posts it.
        </p>
        {!sentLatest && (
          <>
            <p className="note wn">You’ve changed the clip since it was approved. Send the new version only if the team should see it again.</p>
            <SendBox message={message} setMessage={setMessage} fresh={fresh} rendering={rendering} onSend={onSend} onRenderAndSend={onRenderAndSend} />
          </>
        )}
      </div>
    )
  }
  return (
    <div className="review-tab">
      <span className="status-pill needs_work">{STATUS_LABEL.needs_work}</span>
      <div className="panel-title">Needs work</div>
      <p className="muted small">{decided ? `${decided.by.name} reviewed version ${item.version} ${when(decided.at)}` : `Version ${item.version}`}</p>
      <div className="review-tab-notes">
        {notes.map((n) => (
          <div key={n.id} className={`review-tab-note ${n.fixed ? 'fixed' : ''}`}>
            {n.time === null ? (
              <span className="mono small muted">Whole video</span>
            ) : (
              <button className="link small mono" onClick={() => onJump(n.time ?? 0)}>
                {fmt(n.time)} · jump there
              </button>
            )}
            <p>{n.text}</p>
            <label className="toggle">
              <input type="checkbox" checked={n.fixed} onChange={(e) => onFixed(n.id, e.target.checked)} />I fixed this
            </label>
          </div>
        ))}
      </div>
      <p className="muted small">{open > 0 ? `${open} still to fix. Timed notes also show as marks on the timeline.` : 'All ticked off.'}</p>
      {sentLatest ? (
        <p className="note plain">You haven’t changed the clip since version {item.version} was sent back. Make the fixes, then render and send it again.</p>
      ) : (
        <SendBox message={message} setMessage={setMessage} fresh={fresh} rendering={rendering} onSend={onSend} onRenderAndSend={onRenderAndSend} again />
      )}
    </div>
  )
}

function SendBox({
  message,
  setMessage,
  fresh,
  rendering,
  onSend,
  onRenderAndSend,
  again = false
}: {
  message: string
  setMessage: (m: string) => void
  fresh: boolean
  rendering: boolean
  onSend: (m: string | null) => Promise<void> | void
  onRenderAndSend: (m: string | null) => void
  again?: boolean
}) {
  const [sending, setSending] = useState(false)
  const text = message.trim() || null
  return (
    <div className="field send-box">
      <label className="label" htmlFor="review-message">
        Message to the team (optional)
      </label>
      <textarea id="review-message" rows={2} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="What you changed" />
      {rendering ? (
        <button className="primary lg" disabled>
          Rendering…
        </button>
      ) : fresh ? (
        <button
          className="primary lg"
          disabled={sending}
          onClick={async () => {
            setSending(true)
            try {
              await onSend(text)
            } finally {
              setSending(false)
            }
          }}
        >
          {sending ? 'Sending…' : `Send for review${again ? ' again' : ''}`}
        </button>
      ) : (
        <button className="primary lg" onClick={() => onRenderAndSend(text)}>
          Render and send for review{again ? ' again' : ''}
        </button>
      )}
    </div>
  )
}

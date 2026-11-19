import { useEffect, useRef, useState } from 'react'
import { STATUS_LABEL, fmt, invoke, reviewFileUrl, when, type ReviewItem, type ReviewStatus, type ReviewSummary, type Role } from '../api'

interface Props {
  items: ReviewSummary[] | null
  role: Role
  onChanged: () => void // re-read the list
  setError: (e: string | null) => void
  onOpenClip?: (jobId: string, clip: number) => void // editors: back to their own clip
  focus?: { id: string; status: ReviewStatus; n: number } | null // opened from the record
}

const TABS: ReviewStatus[] = ['to_review', 'needs_work', 'good']
const length = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

interface Draft {
  time: number | null
  text: string
}

/** The communication team's queue: tabs by status, the chosen video beside
 *  the list with Good / Needs work and Download. Editors see their own. */
export function Review({ items, role, onChanged, setError, onOpenClip, focus }: Props) {
  const reviewer = role === 'admin' || role === 'reviewer'
  const [tab, setTab] = useState<ReviewStatus>(reviewer ? 'to_review' : 'needs_work')
  const [picked, setPicked] = useState<string | null>(null)
  const [item, setItem] = useState<ReviewItem | null>(null)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const video = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    if (!focus) return
    setTab(focus.status)
    setPicked(focus.id)
  }, [focus])
  const [videoTime, setVideoTime] = useState(0)

  const list = (items ?? []).filter((i) => i.status === tab)
  const counts = Object.fromEntries(TABS.map((t) => [t, (items ?? []).filter((i) => i.status === t).length])) as Record<ReviewStatus, number>
  const chosen = list.find((i) => i.id === picked) ?? list[0] ?? null

  // Load the full item (notes, history) for the chosen video.
  const chosenKey = chosen ? `${chosen.id}/${chosen.version}/${chosen.status}` : null
  useEffect(() => {
    setItem(null)
    setDrafts([])
    setText('')
    if (!chosen) return
    let live = true
    invoke<ReviewItem>('review_get', { id: chosen.id })
      .then((i) => live && setItem(i))
      .catch((e) => live && setError(String((e as Error).message ?? e)))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chosenKey])

  const addNote = (atTime: boolean) => {
    const t = text.trim()
    if (!t) return
    const time = atTime && video.current ? Math.round(video.current.currentTime * 10) / 10 : null
    setDrafts((d) => [...d, { time, text: t }])
    setText('')
  }

  const decide = async (decision: 'good' | 'needs_work') => {
    if (!item) return
    const pending = text.trim() ? [...drafts, { time: video.current ? Math.round(video.current.currentTime * 10) / 10 : null, text: text.trim() }] : drafts
    setBusy(true)
    try {
      const next = await invoke<ReviewItem>('review_decide', { id: item.id, decision, version: item.version, notes: decision === 'needs_work' ? pending : [] })
      setItem(next)
      setDrafts([])
      setText('')
      onChanged()
    } catch (e) {
      setError(String((e as Error).message ?? e))
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  const canDecide = reviewer && item?.status === 'to_review'
  const pendingNotes = drafts.length + (text.trim() ? 1 : 0)
  const versionNotes = item ? item.notes.filter((n) => n.version === item.version) : []
  const olderNotes = item ? item.notes.filter((n) => n.version !== item.version) : []

  return (
    <div className="review">
      <main className="review-list">
        <div className="review-head">
          <h1>{reviewer ? 'Videos to review' : 'Your videos in review'}</h1>
          <button className="sm" onClick={onChanged}>
            Refresh
          </button>
        </div>
        <div className="review-tabs" role="tablist" aria-label="Status">
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={t === tab}
              className={t === tab ? 'on' : ''}
              onClick={() => {
                setTab(t)
                setPicked(null)
              }}
            >
              {STATUS_LABEL[t]} · {counts[t]}
            </button>
          ))}
        </div>
        {items === null ? (
          <p className="muted">Loading…</p>
        ) : list.length === 0 ? (
          <div className="card empty-card">
            <b>{tab === 'to_review' ? 'Nothing waiting.' : tab === 'needs_work' ? 'Nothing sent back.' : 'No approved videos yet.'}</b>
            <span className="muted">
              {tab === 'to_review'
                ? reviewer
                  ? 'A video shows up here as soon as an editor sends it for review.'
                  : 'Render a clip, then press “Send for review”.'
                : ''}
            </span>
          </div>
        ) : (
          <div className="review-rows">
            {list.map((i) => (
              <button key={i.id} className={`review-row ${chosen?.id === i.id ? 'on' : ''}`} onClick={() => setPicked(i.id)}>
                <img className={i.format} src={reviewFileUrl(i.id, { thumb: true, v: i.version })} alt="" loading="lazy" />
                <span className="review-row-text">
                  <b>{i.title}</b>
                  <span className="muted small">
                    Edited by {i.owner.name} · {length(i.seconds)} · {when(i.sentAt)}
                  </span>
                  <span className="small">
                    {i.version > 1 ? `Sent again${i.message ? `: “${i.message}”` : ''}` : i.message ? `“${i.message}”` : i.status === 'needs_work' ? `${i.openNotes} note${i.openNotes === 1 ? '' : 's'} to fix` : 'First review'}
                  </span>
                </span>
                <span className="tag mono">v{i.version}</span>
              </button>
            ))}
          </div>
        )}
      </main>

      {chosen && (
        <aside className="review-side" aria-label="The chosen video">
          <div className="review-video">
            <video key={`${chosen.id}/${chosen.version}`} ref={video} className={chosen.format} src={reviewFileUrl(chosen.id, { v: chosen.version })} controls preload="metadata" playsInline onTimeUpdate={(e) => setVideoTime(e.currentTarget.currentTime)} onSeeked={(e) => setVideoTime(e.currentTarget.currentTime)} />
            <div className="review-meta">
              <span className={`status-pill ${chosen.status}`}>{STATUS_LABEL[chosen.status]}</span>
              <b className="review-title">{chosen.title}</b>
              <span className="muted small">
                Edited by {chosen.owner.name}
                <br />
                Version {chosen.version} · sent {when(chosen.sentAt)}
                <br />
                {length(chosen.seconds)} · {chosen.format === 'landscape' ? 'wide' : 'vertical'}
                {chosen.reviewer && chosen.status !== 'to_review' && (
                  <>
                    <br />
                    {STATUS_LABEL[chosen.status]} by {chosen.reviewer.name}
                  </>
                )}
              </span>
              {reviewer && (
                <a className={`btn ${chosen.status === 'good' ? 'primary' : ''}`} href={reviewFileUrl(chosen.id, { download: true })} onClick={() => window.setTimeout(onChanged, 1500)}>
                  Download video
                </a>
              )}
              {!reviewer && onOpenClip && (
                <button onClick={() => onOpenClip(chosen.jobId, chosen.clip)}>Open in the editor</button>
              )}
            </div>
          </div>

          {chosen.message && (
            <div className="note plain">
              <b>Message from {chosen.owner.name}</b>
              {chosen.message}
            </div>
          )}

          {versionNotes.length > 0 && <NoteList title={`Notes on version ${item?.version}`} notes={versionNotes} />}

          {canDecide && (
            <div className="review-decide">
              <div className="field">
                <label className="label" htmlFor="review-note">
                  Note for the editor (needed only when it needs work)
                </label>
                <textarea
                  id="review-note"
                  rows={3}
                  value={text}
                  placeholder="Pause the video where the problem is, then write here."
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      addNote(true)
                    }
                  }}
                />
                <div className="row">
                  <button className="sm" disabled={!text.trim()} onClick={() => addNote(true)}>
                    Add note at {fmt(videoTime)}
                  </button>
                  <button className="sm" disabled={!text.trim()} onClick={() => addNote(false)}>
                    Note about the whole video
                  </button>
                </div>
              </div>
              {drafts.length > 0 && (
                <ul className="draft-notes">
                  {drafts.map((d, k) => (
                    <li key={k}>
                      <span className="mono note-time">{d.time === null ? 'whole video' : fmt(d.time)}</span>
                      <span className="spacer-text">{d.text}</span>
                      <button className="link small" aria-label={`Remove the note “${d.text}”`} onClick={() => setDrafts((all) => all.filter((_, j) => j !== k))}>
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="decide-buttons">
                <button className="lg needs-work" disabled={busy || pendingNotes === 0} onClick={() => decide('needs_work')} title={pendingNotes === 0 ? 'Add a note first' : undefined}>
                  Needs work{pendingNotes ? ` · send ${pendingNotes} note${pendingNotes === 1 ? '' : 's'}` : ''}
                </button>
                <button className="lg good" disabled={busy} onClick={() => decide('good')}>
                  Good
                </button>
              </div>
              <p className="muted small">Good moves it to the Good tab, ready to download and post. Needs work sends it back to {chosen.owner.name} with your notes.</p>
            </div>
          )}

          {olderNotes.length > 0 && <NoteList title="Earlier notes" notes={olderNotes} muted />}
        </aside>
      )}
    </div>
  )
}

function NoteList({ title, notes, muted = false }: { title: string; notes: ReviewItem['notes']; muted?: boolean }) {
  return (
    <div className={`review-notes ${muted ? 'muted-notes' : ''}`}>
      <span className="label">{title}</span>
      {notes.map((n) => (
        <div key={n.id} className="review-note">
          <span className="mono note-time">{n.time === null ? 'whole video' : fmt(n.time)}</span>
          <span>
            {n.text}
            <span className="muted small">
              {' '}
              — {n.by.name}, {when(n.at)}
              {n.fixed ? ' · fixed' : ''}
            </span>
          </span>
        </div>
      ))}
    </div>
  )
}

import { useMemo, useState } from 'react'
import { STATUS_LABEL, when, type ReviewStatus, type ReviewSummary, type Role } from '../api'

interface Props {
  items: ReviewSummary[] | null
  role: Role
  onOpen: (id: string, status: ReviewStatus) => void // show it on the Review screen
}

type Period = 'week' | 'month' | 'all'
const DAY = 86400000

/** Who edited what: a card per editor and a table of every video sent for
 *  review, filled in from what people already do (send, review, download). */
export function Record({ items, role, onOpen }: Props) {
  const [editor, setEditor] = useState('all')
  const [status, setStatus] = useState<'all' | ReviewStatus>('all')
  const [period, setPeriod] = useState<Period>('week')

  const since = period === 'week' ? Date.now() - 7 * DAY : period === 'month' ? Date.now() - 30 * DAY : 0
  const inPeriod = (i: ReviewSummary) => new Date(i.updated || i.sentAt).getTime() >= since
  const all = items ?? []
  const editors = useMemo(() => [...new Map(all.map((i) => [i.owner.id, i.owner.name])).entries()].sort((a, b) => a[1].localeCompare(b[1])), [all])
  const rows = all.filter((i) => inPeriod(i) && (editor === 'all' || i.owner.id === editor) && (status === 'all' || i.status === status))

  const cards = editors.map(([id, name]) => {
    const mine = all.filter((i) => i.owner.id === id && inPeriod(i))
    return { id, name, count: mine.length, goodFirst: mine.filter((i) => i.goodFirstTime).length, sentBack: mine.filter((i) => i.sentBack > 0).length }
  })
  const periodWord = period === 'week' ? 'this week' : period === 'month' ? 'in the last 30 days' : 'in total'

  return (
    <div className="record">
      <div className="record-head">
        <h1>{role === 'editor' ? 'Your videos' : 'Who edited what'}</h1>
        <span className="spacer" />
        {role !== 'editor' && (
          <label className="filter">
            Editor
            <select value={editor} onChange={(e) => setEditor(e.target.value)}>
              <option value="all">Everyone</option>
              {editors.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="filter">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            <option value="all">All</option>
            <option value="to_review">To review</option>
            <option value="needs_work">Needs work</option>
            <option value="good">Good</option>
          </select>
        </label>
        <label className="filter">
          When
          <select value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
            <option value="week">This week</option>
            <option value="month">Last 30 days</option>
            <option value="all">All time</option>
          </select>
        </label>
      </div>

      {cards.length > 0 && (
        <div className="record-cards">
          {cards.map((c) => (
            <div key={c.id} className="card record-card">
              <b>{c.name}</b>
              <span className="record-count">
                {c.count} <span className="muted">video{c.count === 1 ? '' : 's'} {periodWord}</span>
              </span>
              <span className="muted small">
                {c.goodFirst} good first time · {c.sentBack} sent back
              </span>
            </div>
          ))}
        </div>
      )}

      {items === null ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="card empty-card">
          <b>Nothing here yet.</b>
          <span className="muted">Videos show up once an editor sends them for review.</span>
        </div>
      ) : (
        <div className="card record-table">
          <table>
            <thead>
              <tr>
                <th scope="col">Video</th>
                <th scope="col">Edited by</th>
                <th scope="col">Reviewed by</th>
                <th scope="col">Status</th>
                <th scope="col">Times sent back</th>
                <th scope="col">Last change</th>
                <th scope="col">Downloaded</th>
                <th scope="col">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id}>
                  <th scope="row">
                    {i.title} <span className="muted small mono">v{i.version}</span>
                  </th>
                  <td>{i.owner.name}</td>
                  <td className="muted">{i.reviewer?.name ?? 'Not yet'}</td>
                  <td>
                    <span className={`status-pill ${i.status}`}>{STATUS_LABEL[i.status]}</span>
                  </td>
                  <td className="mono">{i.sentBack}</td>
                  <td className="muted">{when(i.updated)}</td>
                  <td className="muted">{i.lastDownload ? `${i.lastDownload.by.name} · ${when(i.lastDownload.at)}` : 'No'}</td>
                  <td>
                    <button className="link" onClick={() => onOpen(i.id, i.status)}>
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

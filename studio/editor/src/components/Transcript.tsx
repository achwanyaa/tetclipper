import { useMemo, useState } from 'react'
import type { Word } from '@tetclipper/composition'
import { fmt } from '../api'
import type { PanelProps } from './Canvas'

/** Phrases like transcript.md: break at sentence ends, pauses and speaker changes. */
function phrases(words: Word[]): number[][] {
  const out: number[][] = []
  let cur: number[] = []
  words.forEach((w, i) => {
    cur.push(i)
    const next = words[i + 1]
    if (!next || cur.length >= 14 || /[.!?]$/.test(w.text) || next.start - w.end > 0.6 || next.speaker !== w.speaker) {
      out.push(cur)
      cur = []
    }
  })
  return out
}

/** Caption words: click to seek, double-click to fix, shift-click to select a span. */
export function Transcript({ spec, editor, setEditor, update, seek }: PanelProps) {
  const words = spec.words ?? []
  const cuts = spec.cuts ?? []
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [anchor, setAnchor] = useState<number | null>(null)
  const groups = useMemo(() => phrases(words), [words])
  const sel = editor.selection
  const inRange = (w: Word) => w.end > spec.source.start && w.start < spec.source.end
  const inCut = (w: Word) => cuts.some((c) => (w.start + w.end) / 2 >= c.start && (w.start + w.end) / 2 < c.end)

  const setWords = (next: Word[], reason: string) => update({ ...spec, words: next }, reason)
  const select = (range: [number, number] | null) => setEditor((s) => ({ ...s, selection: range }))

  const commit = () => {
    if (editing === null) return
    const text = draft.trim()
    const next = words.map((w, i) => (i === editing ? { ...w, text: text || w.text, hidden: text ? w.hidden : true } : w))
    setWords(next, `fix word "${words[editing].text}" → "${text}"`)
    setEditing(null)
  }

  const applyToSelection = (fn: (w: Word) => Word, reason: string) => {
    if (!sel) return
    setWords(words.map((w, i) => (i >= sel[0] && i <= sel[1] ? fn(w) : w)), reason)
  }

  const cutSelection = () => {
    if (!sel) return
    const a = words[sel[0]]
    const b = words[sel[1]]
    const prevEnd = words[sel[0] - 1]?.end ?? a.start
    const nextStart = words[sel[1] + 1]?.start ?? b.end
    // cut from the gap before the first word to the gap after the last
    const start = +((prevEnd + a.start) / 2).toFixed(3)
    const end = +((b.end + nextStart) / 2).toFixed(3)
    update({ ...spec, cuts: [...cuts, { start, end }] }, `cut ${fmt(start)}–${fmt(end)}`)
    select(null)
  }

  const removeCutAt = (w: Word) => {
    const mid = (w.start + w.end) / 2
    update({ ...spec, cuts: cuts.filter((c) => !(mid >= c.start && mid < c.end)) }, 'restore cut')
  }

  return (
    <div className="transcript">
      <div className="transcript-actions">
        {sel ? (
          <>
            <span className="muted small">
              words #{sel[0]}–{sel[1]} · {fmt(words[sel[0]].start)}–{fmt(words[sel[1]].end)}
            </span>
            <button onClick={cutSelection}>✂ Cut out</button>
            <button onClick={() => applyToSelection((w) => ({ ...w, hidden: !w.hidden }), 'toggle hidden')}>Hide/show</button>
            <button onClick={() => applyToSelection((w) => ({ ...w, emphasis: !w.emphasis }), 'toggle emphasis')}>Emphasis</button>
            <button className="link" onClick={() => select(null)}>
              clear
            </button>
          </>
        ) : (
          <span className="muted small">Click a word to jump · double-click to fix it · shift-click to select a span (then cut, hide, or ask Claude)</span>
        )}
      </div>
      <div className="phrases">
        {groups.map((g) => {
          if (!g.some((i) => inRange(words[i]))) return null
          const first = words[g[0]]
          return (
            <p key={g[0]} className={inCut(first) ? 'cut' : ''}>
              <span className="ts" onClick={() => seek(first.start)}>
                {fmt(first.start)}
              </span>
              {g.map((i) => {
                const w = words[i]
                if (!inRange(w)) return null
                const active = editor.playhead !== null && editor.playhead >= w.start && editor.playhead < w.end + 0.05
                const selected = sel && i >= sel[0] && i <= sel[1]
                if (editing === i) {
                  return (
                    <input
                      key={i}
                      className="word-edit"
                      autoFocus
                      value={draft}
                      size={Math.max(3, draft.length)}
                      onChange={(e) => setDraft(e.target.value)}
                      onBlur={commit}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commit()
                        if (e.key === 'Escape') setEditing(null)
                      }}
                    />
                  )
                }
                return (
                  <span
                    key={i}
                    className={['w', active && 'active', selected && 'selected', w.hidden && 'hidden', w.emphasis && 'emph', inCut(w) && 'incut']
                      .filter(Boolean)
                      .join(' ')}
                    title={`${fmt(w.start)} · #${i}${inCut(w) ? ' · cut (click ✂ to restore)' : ''}`}
                    onClick={(e) => {
                      if (e.shiftKey && anchor !== null) {
                        select([Math.min(anchor, i), Math.max(anchor, i)])
                      } else {
                        setAnchor(i)
                        select(null)
                        seek(w.start)
                      }
                    }}
                    onDoubleClick={() => {
                      setEditing(i)
                      setDraft(w.text)
                    }}
                  >
                    {w.text}
                  </span>
                )
              })}
              {inCut(first) && (
                <button className="link small" onClick={() => removeCutAt(first)} title="restore this cut">
                  ✂ restore
                </button>
              )}
            </p>
          )
        })}
      </div>
    </div>
  )
}

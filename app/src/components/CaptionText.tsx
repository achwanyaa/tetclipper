import { useMemo, useState } from 'react'

/**
 * The clip's caption words, editable. Each fix is keyed by the word's source
 * start time (same key as the pipeline's `word_key`), so timing, karaoke
 * highlighting and emphasis stay; "" hides the word. Claude's proofreading
 * writes into the same map, so its fixes are reviewed and undone the same way.
 * Changes apply on RE-RENDER CLIP.
 */

interface Word { word: string; start: number; end: number }

export const wordKey = (start: number) => start.toFixed(3)

interface Props {
  words: Word[] // the clip's words, in order
  edits: Record<string, string>
  onChange: (next: Record<string, string>) => void
  onProofread: () => void
  proofreading: boolean
  note: string | null
}

/** On-screen-ish lines: break at sentence punctuation, a pause, or 8 words. */
function toLines(words: Word[]): Word[][] {
  const lines: Word[][] = []
  let cur: Word[] = []
  words.forEach((w, i) => {
    cur.push(w)
    const next = words[i + 1]
    if (!next || cur.length >= 8 || /[.!?]$/.test(w.word) || next.start - w.end > 0.6) {
      lines.push(cur)
      cur = []
    }
  })
  return lines
}

function fmt(t: number): string {
  return `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`
}

export default function CaptionText({ words, edits, onChange, onProofread, proofreading, note }: Props) {
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const lines = useMemo(() => toLines(words), [words])
  const count = Object.keys(edits).length

  const commit = (key: string, original: string) => {
    const text = draft.trim()
    const next = { ...edits }
    if (text === original.trim()) delete next[key]
    else next[key] = text // "" = hide
    onChange(next)
    setEditing(null)
  }

  const revert = (key: string) => {
    const next = { ...edits }
    delete next[key]
    onChange(next)
  }

  return (
    <div className="captext">
      <div className="captext-head">
        <span className="opt-label">caption text</span>
        <span className="captext-hint mono">
          click a word to fix it · empty hides it · {count} fix{count === 1 ? '' : 'es'}
        </span>
        <button className="btn-secondary" onClick={onProofread} disabled={proofreading}>
          {proofreading ? 'CLAUDE IS READING…' : '✦ PROOFREAD WITH CLAUDE'}
        </button>
        {count > 0 && (
          <button className="btn-ghost" onClick={() => onChange({})} disabled={proofreading}>
            undo all
          </button>
        )}
      </div>
      {note && <p className="captext-note mono">{note}</p>}
      <div className="captext-lines">
        {lines.map((line, li) => (
          <p key={li} className="captext-line">
            <span className="captext-time mono">{fmt(line[0].start)}</span>
            {line.map((w) => {
              const key = wordKey(w.start)
              const fixed = key in edits
              const text = fixed ? edits[key] : w.word
              if (editing === key) {
                return (
                  <input
                    key={key}
                    className="captext-input mono"
                    autoFocus
                    value={draft}
                    size={Math.max(4, draft.length + 1)}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => commit(key, w.word)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commit(key, w.word)
                      if (e.key === 'Escape') setEditing(null)
                    }}
                  />
                )
              }
              return (
                <span
                  key={key}
                  className={`captext-word ${fixed ? (text ? 'fixed' : 'hidden') : ''}`}
                  title={fixed ? `was "${w.word}" · right-click to undo` : 'click to fix'}
                  onClick={() => {
                    setEditing(key)
                    setDraft(text)
                  }}
                  onContextMenu={(e) => {
                    if (!fixed) return
                    e.preventDefault()
                    revert(key)
                  }}
                >
                  {fixed && !text ? w.word : text}{' '}
                </span>
              )
            })}
          </p>
        ))}
      </div>
    </div>
  )
}

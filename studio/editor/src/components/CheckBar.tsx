import { useEffect, useState } from 'react'
import { fmt, invoke, onEvent } from '../api'
import { retext } from '../retext'
import type { PanelProps } from './Canvas'
import { WordList } from './WordList'

/** Caption spans the speech model may have misheard (mixed English/Swahili/
 *  Sheng): listen, then keep it, take the Swahili reading, or type the fix. */
export function CheckBar({ data, spec, update, seek, setError }: PanelProps) {
  const words = spec.words ?? []
  const doubts = (spec.doubts ?? []).filter((d) => d.to < words.length)
  const [at, setAt] = useState(0)
  const [typed, setTyped] = useState('')
  const [checking, setChecking] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const d = doubts.length ? doubts[at % doubts.length] : null
  const spanText = d ? words.slice(d.from, d.to + 1).filter((w) => !w.hidden).map((w) => w.text).join(' ') : ''

  useEffect(() => setTyped(''), [at, doubts.length])
  useEffect(
    () =>
      onEvent((ev) => {
        if (checking && (ev.event === 'exited' || (ev.event === 'result' && ('doubts' in ev || !ev.ok)))) {
          setChecking(false)
          if (ev.event === 'result' && !ev.ok) setError(ev.error ?? 'caption check failed')
        }
      }),
    [checking, setError]
  )

  const resolve = (text: string | null, reason: string) => {
    if (!d) return
    const rest = (spec.doubts ?? []).filter((x) => x !== d)
    const nextWords = text === null ? words : [...words.slice(0, d.from), ...retext(words.slice(d.from, d.to + 1), text), ...words.slice(d.to + 1)]
    update({ ...spec, words: nextWords, doubts: rest }, reason)
  }

  return (
    <div className="checkbar">
      <div className="row">
        {d ? (
          <>
            <span className="badge">{doubts.length} to check</span>
            <button className="link" onClick={() => seek(words[d.from].start)} title="play from here">
              ▶ {fmt(words[d.from].start)}
            </button>
            <span className="heard">“{spanText}”</span>
            <span className="muted small">{d.reason}</span>
          </>
        ) : (
          <span className="muted small">No captions flagged.</span>
        )}
        <div className="spacer" />
        <button
          disabled={checking}
          onClick={async () => {
            setChecking(true)
            try {
              await invoke('studio_doubts', { jobId: data.jobId, clip: data.clip })
            } catch (e) {
              setChecking(false)
              setError(String((e as Error).message ?? e))
            }
          }}
          title="Find words the speech model may have misheard, and re-listen to them in Swahili"
        >
          {checking ? 'Checking…' : 'Re-check captions'}
        </button>
        <button onClick={() => setListOpen(true)} title="Words and fixes the app has learned">
          Word list
        </button>
      </div>
      {d && (
        <div className="row choices">
          {d.alt && (
            <button className="primary" onClick={() => resolve(d.alt!, `use Swahili reading "${d.alt}"`)}>
              Use “{d.alt}”
            </button>
          )}
          <input
            placeholder="or type what was said…"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && typed.trim() && resolve(typed.trim(), `fix "${spanText}" → "${typed.trim()}"`)}
          />
          <button disabled={!typed.trim()} onClick={() => resolve(typed.trim(), `fix "${spanText}" → "${typed.trim()}"`)}>
            Fix
          </button>
          <button onClick={() => resolve(null, 'caption is right')}>It’s right</button>
          {doubts.length > 1 && <button className="link" onClick={() => setAt((i) => i + 1)}>next ▸</button>}
        </div>
      )}
      {listOpen && <WordList onClose={() => setListOpen(false)} setError={setError} />}
    </div>
  )
}

import { Fragment, useEffect, useState } from 'react'
import { BEHIND_EFFECTS, type EffectInput as Effect } from '@tetclipper/composition'
import { fmt, invoke, onEvent } from '../api'
import type { PanelProps } from './Canvas'

type Kind = Effect['type']

/** Every effect, grouped, with a short description and defaults at time `at`. */
const CATALOG: { group: string; items: { type: Kind; label: string; hint: string; make: (at: number) => Effect }[] }[] = [
  {
    group: 'Graphics',
    items: [
      { type: 'checklist', label: 'Checklist', hint: 'points tick in one by one', make: (at) => ({ type: 'checklist', at, duration: 6, title: 'Three things', items: ['First point', 'Second point', 'Third point'] }) },
      { type: 'headline-wall', label: 'Headline wall', hint: 'headlines or verses stack up', make: (at) => ({ type: 'headline-wall', at, duration: 5, look: 'scripture', headlines: ['First line', 'Second line', 'Third line'] }) },
      { type: 'chart', label: 'Chart', hint: 'bars or a line grow', make: (at) => ({ type: 'chart', at, duration: 5, kind: 'bar', title: 'Title', labels: ['A', 'B', 'C'], values: [30, 60, 90] }) },
      { type: 'glass-text', label: 'Glass type', hint: 'frosted-glass key phrase', make: (at) => ({ type: 'glass-text', at, duration: 4, text: 'Key phrase', subtitle: '' }) },
      { type: 'hook', label: 'Title card', hint: 'yellow hook card at the top', make: (at) => ({ type: 'hook', at, duration: 3, text: 'Hook text', background: '#FFD700', color: '#000000' }) },
      { type: 'emoji', label: 'Emoji', hint: 'emoji pops in', make: (at) => ({ type: 'emoji', at, duration: 1.6, emoji: '🔥', x: 0.5, y: 0.3, size: 180 }) }
    ]
  },
  {
    group: 'Camera',
    items: [
      { type: 'punch-in', label: 'Punch-in', hint: 'smooth zoom in and out', make: (at) => ({ type: 'punch-in', at, duration: 2.1, amount: 1.12 }) },
      { type: 'digital-zoom', label: 'Digital zoom', hint: 'hard zoom with a glitch hit', make: (at) => ({ type: 'digital-zoom', at, duration: 1.5, amount: 1.35 }) },
      { type: 'vertigo', label: 'Vertigo', hint: 'dolly zoom (best with cutout)', make: (at) => ({ type: 'vertigo', at, duration: 3, amount: 1.3 }) },
      { type: 'pull-back', label: 'Pull-back reveal', hint: 'tight, then pulls back', make: (at) => ({ type: 'pull-back', at, duration: 3, from: 2, to: 0.85 }) },
      { type: 'zoom-through', label: 'Zoom-through cut', hint: 'transition — put it on a cut', make: (at) => ({ type: 'zoom-through', at, duration: 0.8 }) },
      { type: 'shake', label: 'Shake', hint: 'short camera shake', make: (at) => ({ type: 'shake', at, duration: 0.5, intensity: 12 }) },
      { type: 'flash', label: 'Flash', hint: 'white flash', make: (at) => ({ type: 'flash', at, duration: 0.35 }) }
    ]
  },
  {
    group: 'Styles',
    items: [
      { type: 'phone', label: 'Phone mockup', hint: 'video shrinks into a phone', make: (at) => ({ type: 'phone', at, duration: 4, tilt: -6, background: '#111111' }) },
      { type: 'ui-cards', label: 'UI world', hint: 'app cards float in 3D', make: (at) => ({ type: 'ui-cards', at, duration: 5, cards: [{ kind: 'verse', title: 'Verse', text: 'text' }, { kind: 'like', title: '12K likes' }] }) },
      { type: 'paper-text', label: 'Paper cut', hint: 'stop-motion paper words', make: (at) => ({ type: 'paper-text', at, duration: 4, text: 'Worthy is the Lamb' }) },
      { type: 'doodle', label: 'Doodle', hint: 'hand-drawn shape that wiggles', make: (at) => ({ type: 'doodle', at, duration: 3, shape: 'circle', x: 0.5, y: 0.33, size: 420 }) },
      { type: 'orbit', label: 'Orbit', hint: 'words circle the head', make: (at) => ({ type: 'orbit', at, duration: 4, items: ['🔥', 'WORD', '🙏'], x: 0.5, y: 0.3 }) }
    ]
  },
  {
    group: 'Behind the speaker',
    items: [
      { type: 'wall-text', label: 'Couch wall', hint: 'big text behind the speaker', make: (at) => ({ type: 'wall-text', at, duration: 4, text: 'Worthy' }) },
      { type: 'frame-break', label: 'Frame break', hint: 'speaker steps out of a frame', make: (at) => ({ type: 'frame-break', at, duration: 4 }) },
      { type: 'background', label: 'Green screen', hint: 'swap the background', make: (at) => ({ type: 'background', at, duration: 4, mode: 'color', color: '#13294B' }) },
      { type: 'cover', label: 'Cover story', hint: 'magazine cover', make: (at) => ({ type: 'cover', at, duration: 4, title: 'WORTHY', lines: ['First cover line', 'Second cover line'] }) }
    ]
  }
]

const LABEL = Object.fromEntries(CATALOG.flatMap((g) => g.items.map((i) => [i.type, i.label]))) as Record<string, string>
LABEL.image = 'Image'
const BEHIND = new Set<string>(BEHIND_EFFECTS)

/** Editable fields of one effect: strings, numbers, colours, lists. */
function Fields({ effect, onChange }: { effect: Effect; onChange: (e: Effect) => void }) {
  const rec = effect as unknown as Record<string, unknown>
  const set = (k: string, v: unknown) => onChange({ ...rec, [k]: v } as unknown as Effect)
  return (
    <div className="fx-fields">
      {Object.entries(rec).map(([k, v]) => {
        if (k === 'type' || k === 'at') return null
        if (k === 'cards' && Array.isArray(v)) {
          const text = (v as { kind?: string; title: string; text?: string }[]).map((c) => [c.kind ?? 'notification', c.title, c.text ?? ''].join(' | ')).join('\n')
          return (
            <label key={k} className="wide">
              cards <span>kind | title | text — one per line (kind: notification, like, comment, verse)</span>
              <textarea
                rows={3}
                defaultValue={text}
                onBlur={(e) =>
                  set(k, e.target.value.split('\n').filter((l) => l.trim()).map((l) => {
                    const [kind, title, more] = l.split('|').map((s) => s.trim())
                    return { kind: ['notification', 'like', 'comment', 'verse'].includes(kind) ? kind : 'notification', title: title || kind, ...(more ? { text: more } : {}) }
                  }))
                }
              />
            </label>
          )
        }
        if (Array.isArray(v)) {
          const numeric = v.every((x) => typeof x === 'number')
          return (
            <label key={k} className="wide">
              {k} <span>{numeric ? 'comma-separated numbers' : 'one per line'}</span>
              <textarea
                rows={Math.min(5, Math.max(2, v.length))}
                defaultValue={numeric ? v.join(', ') : v.join('\n')}
                onBlur={(e) => set(k, numeric ? e.target.value.split(',').map((x) => Number(x.trim())).filter((x) => Number.isFinite(x)) : e.target.value.split('\n').map((x) => x.trim()).filter(Boolean))}
              />
            </label>
          )
        }
        if (typeof v === 'number') {
          return (
            <label key={k}>
              {k}
              <input type="number" step="0.05" defaultValue={v} onBlur={(e) => Number.isFinite(+e.target.value) && set(k, +e.target.value)} />
            </label>
          )
        }
        if (typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v)) {
          return (
            <label key={k}>
              {k}
              <input type="color" defaultValue={v} onBlur={(e) => set(k, e.target.value)} />
            </label>
          )
        }
        if (typeof v === 'string') {
          return (
            <label key={k} className={v.length > 20 ? 'wide' : ''}>
              {k}
              <input defaultValue={v} onBlur={(e) => set(k, e.target.value)} />
            </label>
          )
        }
        return null
      })}
    </div>
  )
}

/** Timed effects: pick one to add at the playhead, then edit or delete it. */
export function EffectsPanel({ data, spec, editor, update, seek, setError }: PanelProps) {
  const effects = spec.effects ?? []
  const [open, setOpen] = useState<number | null>(null)
  const [cutting, setCutting] = useState(false)
  const at = +(editor.playhead ?? spec.source.start).toFixed(2)
  const sorted = effects.map((e, i) => ({ e, i })).sort((a, b) => a.e.at - b.e.at)
  const punches = effects.filter((e) => e.type === 'punch-in').length
  const needsCutout = !spec.matte && effects.some((e) => BEHIND.has(e.type))

  useEffect(
    () =>
      onEvent((ev) => {
        if (cutting && (ev.event === 'exited' || (ev.event === 'result' && ('matte' in ev || !ev.ok)))) {
          setCutting(false)
          if (ev.event === 'result' && !ev.ok) setError(ev.error ?? 'cutout failed')
        }
      }),
    [cutting, setError]
  )

  const add = (e: Effect) => {
    update({ ...spec, effects: [...effects, e] }, `add ${LABEL[e.type] ?? e.type}`)
    setOpen(effects.length)
  }
  const replace = (i: number, e: Effect) => update({ ...spec, effects: effects.map((x, j) => (j === i ? e : x)) }, `edit ${LABEL[e.type] ?? e.type}`)
  const remove = (i: number) => {
    update({ ...spec, effects: effects.filter((_, j) => j !== i) }, `remove ${LABEL[effects[i].type] ?? effects[i].type}`)
    setOpen(null)
  }

  return (
    <div className="effects-panel">
      {needsCutout && (
        <div className="banner cutout">
          Behind-the-speaker effects need the speaker cut out (about 1–2 min on the cloud GPU). Until then they draw in front.
          <button
            className="primary"
            disabled={cutting}
            onClick={async () => {
              setCutting(true)
              try {
                await invoke('studio_matte', { jobId: data.jobId, clip: data.clip })
              } catch (e) {
                setCutting(false)
                setError(String((e as Error).message ?? e))
              }
            }}
          >
            {cutting ? 'Cutting out…' : 'Cut out speaker'}
          </button>
        </div>
      )}
      <div className="fx-catalog">
        <span className="muted small">Add at {fmt(at)}:</span>
        {CATALOG.map((g) => (
          <div key={g.group} className="fx-group">
            <strong>{g.group}</strong>
            {g.items.map((item) => (
              <button key={item.type} title={item.hint} onClick={() => add(item.make(at))}>
                {item.label}
              </button>
            ))}
          </div>
        ))}
      </div>
      <table className="effects">
        <tbody>
          {sorted.map(({ e, i }) => (
            <Fragment key={i}>
              <tr className={open === i ? 'open' : ''}>
                <td>
                  <button className="link" onClick={() => seek(e.at)}>
                    {fmt(e.at)}
                  </button>
                </td>
                <td>
                  {LABEL[e.type] ?? e.type}
                  {BEHIND.has(e.type) && !spec.matte && <span className="muted small"> · needs cutout</span>}
                </td>
                <td className="muted">{e.duration.toFixed(1)} s</td>
                <td>
                  <button className="link" onClick={() => setOpen(open === i ? null : i)}>
                    {open === i ? 'close' : 'edit'}
                  </button>
                  <button className="link" onClick={() => remove(i)} title="delete">
                    ✕
                  </button>
                </td>
              </tr>
              {open === i && (
                <tr>
                  <td colSpan={4}>
                    <Fields key={JSON.stringify(e)} effect={e} onChange={(next) => replace(i, next)} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td className="muted">No effects yet. Pick one above (added at the playhead), or ask Claude.</td>
            </tr>
          )}
        </tbody>
      </table>
      {punches > 0 && (
        <button className="link" onClick={() => update({ ...spec, effects: effects.filter((e) => e.type !== 'punch-in') }, 'remove all punch-ins')}>
          remove all {punches} punch-ins
        </button>
      )}
    </div>
  )
}

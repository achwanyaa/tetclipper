import { useState } from 'react'
import type { EffectInput as Effect } from '@tetclipper/composition'
import { fmt } from '../api'
import type { PanelProps } from './Canvas'

const LABEL: Record<Effect['type'], string> = {
  'punch-in': 'Punch-in',
  shake: 'Shake',
  flash: 'Flash',
  emoji: 'Emoji',
  hook: 'Title card',
  image: 'Image'
}

function describe(e: Effect): string {
  switch (e.type) {
    case 'punch-in':
      return `${(e.amount ?? 1.12).toFixed(2)}×`
    case 'emoji':
      return e.emoji
    case 'hook':
      return `“${e.text}”`
    case 'image':
      return e.layout ?? 'top'
    default:
      return ''
  }
}

/** Timed effects: list, jump, delete, and add at the playhead. */
export function EffectsPanel({ spec, editor, update, seek }: PanelProps) {
  const effects = spec.effects ?? []
  const [hook, setHook] = useState('')
  const [emoji, setEmoji] = useState('🔥')
  const at = editor.playhead ?? spec.source.start
  const sorted = effects.map((e, i) => ({ e, i })).sort((a, b) => a.e.at - b.e.at)
  const punches = effects.filter((e) => e.type === 'punch-in').length

  const add = (e: Effect, reason: string) => update({ ...spec, effects: [...effects, e] }, reason)
  const remove = (i: number) => update({ ...spec, effects: effects.filter((_, j) => j !== i) }, `remove ${effects[i].type}`)

  return (
    <div className="effects-panel">
      <div className="add-row">
        <span className="muted small">At {fmt(at)}:</span>
        <button onClick={() => add({ type: 'punch-in', at, duration: 2.1, amount: 1.12 }, 'add punch-in')}>+ Punch-in</button>
        <button onClick={() => add({ type: 'flash', at, duration: 0.35 }, 'add flash')}>+ Flash</button>
        <button onClick={() => add({ type: 'shake', at, duration: 0.5, intensity: 12 }, 'add shake')}>+ Shake</button>
        <input className="emoji-input" value={emoji} onChange={(e) => setEmoji(e.target.value)} maxLength={4} />
        <button onClick={() => add({ type: 'emoji', at, duration: 1.6, emoji, x: 0.5, y: 0.3, size: 180 }, 'add emoji')}>+ Emoji</button>
        <input placeholder="title card text" value={hook} onChange={(e) => setHook(e.target.value)} />
        <button
          disabled={!hook.trim()}
          onClick={() => {
            add({ type: 'hook', at, duration: 3, text: hook.trim(), background: '#FFD700', color: '#000000' }, 'add title card')
            setHook('')
          }}
        >
          + Title card
        </button>
        {punches > 0 && (
          <button className="link" onClick={() => update({ ...spec, effects: effects.filter((e) => e.type !== 'punch-in') }, 'remove all punch-ins')}>
            remove all {punches} punch-ins
          </button>
        )}
      </div>
      <table className="effects">
        <tbody>
          {sorted.map(({ e, i }) => (
            <tr key={i}>
              <td>
                <button className="link" onClick={() => seek(e.at)}>
                  {fmt(e.at)}
                </button>
              </td>
              <td>{LABEL[e.type]}</td>
              <td className="muted">{describe(e)}</td>
              <td className="muted">{e.duration.toFixed(1)} s</td>
              <td>
                <button className="link" onClick={() => remove(i)} title="delete">
                  ✕
                </button>
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td className="muted">No effects. Add one at the playhead, or ask Claude.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

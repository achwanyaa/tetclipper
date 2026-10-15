import { fmt } from '../api'
import type { PanelProps } from './Canvas'

/** Clip range (source seconds) and the list of cuts. */
export function TrimPanel({ spec, editor, update, seek }: PanelProps) {
  const { start, end } = spec.source
  const cuts = spec.cuts ?? []
  const words = spec.words ?? []
  const first = words[0]?.start ?? start
  const last = words[words.length - 1]?.end ?? end
  const setRange = (a: number, b: number, reason: string) => {
    if (b - a < 1) return
    update({ ...spec, source: { ...spec.source, start: +a.toFixed(3), end: +b.toFixed(3) } }, reason)
  }
  const nudge = (which: 'start' | 'end', by: number) =>
    which === 'start' ? setRange(Math.max(0, start + by), end, 'trim start') : setRange(start, end + by, 'trim end')

  return (
    <div className="trim-panel">
      <div className="trim-row">
        <span>Start</span>
        <button className="link" onClick={() => seek(start)}>
          {fmt(start)}
        </button>
        <button onClick={() => nudge('start', -1)}>−1s</button>
        <button onClick={() => nudge('start', -0.2)}>−0.2</button>
        <button onClick={() => nudge('start', 0.2)}>+0.2</button>
        <button onClick={() => nudge('start', 1)}>+1s</button>
        <button disabled={editor.playhead === null} onClick={() => editor.playhead !== null && setRange(editor.playhead, end, 'start at playhead')}>
          set to playhead
        </button>
      </div>
      <div className="trim-row">
        <span>End</span>
        <button className="link" onClick={() => seek(Math.max(start, end - 3))}>
          {fmt(end)}
        </button>
        <button onClick={() => nudge('end', -1)}>−1s</button>
        <button onClick={() => nudge('end', -0.2)}>−0.2</button>
        <button onClick={() => nudge('end', 0.2)}>+0.2</button>
        <button onClick={() => nudge('end', 1)}>+1s</button>
        <button disabled={editor.playhead === null} onClick={() => editor.playhead !== null && setRange(start, editor.playhead, 'end at playhead')}>
          set to playhead
        </button>
      </div>
      <p className="muted small">
        Length {fmt(end - start - cuts.reduce((s, c) => s + Math.max(0, Math.min(c.end, end) - Math.max(c.start, start)), 0))} after cuts · speech
        available {fmt(first)}–{fmt(last)} in the downloaded slice.
      </p>
      {cuts.length > 0 && (
        <table className="effects">
          <tbody>
            {cuts.map((c, i) => (
              <tr key={i}>
                <td>
                  <button className="link" onClick={() => seek(Math.max(start, c.start - 1.5))}>
                    ✂ {fmt(c.start)} – {fmt(c.end)}
                  </button>
                </td>
                <td className="muted">{(c.end - c.start).toFixed(1)} s</td>
                <td>
                  <button className="link" onClick={() => update({ ...spec, cuts: cuts.filter((_, j) => j !== i) }, 'restore cut')}>
                    restore
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

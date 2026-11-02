import { Fragment, useEffect, useState } from 'react'
import { FPS, TRANSITIONS, frameAtSource, type ClipSpecInput, type TransitionType } from '@tetclipper/composition'
import { fmt, invoke } from '../api'
import type { PanelProps } from './Canvas'
import { TRANSITION_LABELS, TransitionPicker } from './TransitionPicker'

/** Clip range (source seconds) and the list of cuts. */
export function TrimPanel({ data, spec, editor, update, seek, setError, timeline, previewFrame }: PanelProps) {
  const { start, end } = spec.source
  const cuts = spec.cuts ?? []
  const words = spec.words ?? []
  const first = words[0]?.start ?? start
  const last = words[words.length - 1]?.end ?? end
  const setRange = (a: number, b: number, reason: string) => {
    if (b - a < 1) return
    update({ ...spec, source: { ...spec.source, start: +a.toFixed(3), end: +b.toFixed(3) } }, reason)
  }
  const [mode, setMode] = useState<'natural' | 'tight'>('natural')
  const [fillers, setFillers] = useState(false)
  const [preview, setPreview] = useState<{ cuts: number; saved: number; fillers: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  const [bulk, setBulk] = useState<TransitionType | ''>('fade')
  const [stutters, setStutters] = useState<{ found: number; saved: number; removals: { at: number; kind: string; text: string }[] } | null>(null)

  useEffect(() => {
    let live = true
    invoke<{ cuts: number; saved: number; fillers: number }>('studio_dead_air', { jobId: data.jobId, clip: data.clip, mode, fillers })
      .then((p) => live && setPreview(p))
      .catch(() => live && setPreview(null))
    return () => {
      live = false
    }
  }, [data.jobId, data.clip, mode, fillers, spec.cuts, spec.words])

  useEffect(() => {
    let live = true
    invoke<{ found: number; saved: number; removals: { at: number; kind: string; text: string }[] }>('studio_stutters', { jobId: data.jobId, clip: data.clip, fillers })
      .then((p) => live && setStutters(p))
      .catch(() => live && setStutters(null))
    return () => {
      live = false
    }
  }, [data.jobId, data.clip, fillers, spec.cuts, spec.words])

  const removeStutters = async () => {
    setBusy(true)
    try {
      const res = await invoke<{ spec?: ClipSpecInput }>('studio_stutters', { jobId: data.jobId, clip: data.clip, fillers, apply: true })
      if (res.spec) update(res.spec, 'remove stutters')
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const removeDeadAir = async () => {
    setBusy(true)
    try {
      const res = await invoke<{ spec?: ClipSpecInput }>('studio_dead_air', { jobId: data.jobId, clip: data.clip, mode, fillers, apply: true })
      if (res.spec) update(res.spec, `remove dead air (${mode})`)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const applyToLongCuts = () =>
    update(
      { ...spec, cuts: cuts.map((c) => (c.end - c.start >= 1 ? { ...c, transition: bulk ? { type: bulk, duration: 0.5 } : null } : c)) },
      bulk ? `transition on cuts: ${TRANSITION_LABELS[bulk]}` : 'hard cuts'
    )
  const previewCut = (end: number) => {
    const f = timeline && frameAtSource(timeline, end + 0.001, FPS)
    if (f !== null && f !== undefined) previewFrame(Math.max(0, f - FPS))
  }

  const nudge = (which: 'start' | 'end', by: number) =>
    which === 'start' ? setRange(Math.max(0, start + by), end, 'trim start') : setRange(start, end + by, 'trim end')

  return (
    <div className="trim-panel">
      <div className="trim-row dead-air">
        <span>Dead air</span>
        <select value={mode} onChange={(e) => setMode(e.target.value as 'natural' | 'tight')} title="natural keeps short sentence pauses; tight is snappier">
          <option value="natural">Natural</option>
          <option value="tight">Tight</option>
        </select>
        <label className="toggle small">
          <input type="checkbox" checked={fillers} onChange={(e) => setFillers(e.target.checked)} />
          also ums/uhs
        </label>
        <button className="primary" disabled={busy || !preview || (preview.cuts === 0 && preview.fillers === 0)} onClick={removeDeadAir}>
          {busy ? 'Cutting…' : 'Remove dead air'}
        </button>
        <span className="muted small">
          {preview ? (preview.cuts || preview.fillers ? `${preview.cuts} cuts · −${preview.saved.toFixed(1)} s${preview.fillers ? ` · ${preview.fillers} fillers` : ''}` : 'nothing to cut') : ''}
        </span>
      </div>
      <div className="trim-row dead-air">
        <span>Stutters</span>
        <button className="primary" disabled={busy || !stutters?.found} onClick={removeStutters} title="Repeated words, cut-off words and false starts (deliberate repetition is kept)">
          Remove stutters
        </button>
        <span className="muted small" title={stutters?.removals.map((r) => `${fmt(r.at)} ${r.kind}: ${r.text}`).join(String.fromCharCode(10))}>
          {stutters ? (stutters.found ? `${stutters.found} found · −${stutters.saved.toFixed(1)} s (hover to list)` : 'none found in the transcript') : ''}
        </span>
      </div>
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
        <>
          <div className="trim-row">
            <span>Effect</span>
            <select value={bulk} aria-label="Transition for longer cuts" onChange={(e) => setBulk(e.target.value as TransitionType | '')}>
              <option value="">Hard cut</option>
              {TRANSITIONS.map((t) => (
                <option key={t} value={t}>
                  {TRANSITION_LABELS[t]}
                </option>
              ))}
            </select>
            <button disabled={!cuts.some((c) => c.end - c.start >= 1)} onClick={applyToLongCuts}>
              Apply to cuts of 1 s or longer
            </button>
          </div>
          <table className="effects">
            <tbody>
              {cuts.map((c, i) => (
                <Fragment key={i}>
                  <tr>
                    <td>
                      <button className="link" onClick={() => seek(Math.max(start, c.start - 1.5))}>
                        ✂ {fmt(c.start)} – {fmt(c.end)}
                      </button>
                    </td>
                    <td className="muted">{(c.end - c.start).toFixed(1)} s</td>
                    <td>
                      <button className="link" aria-expanded={editing === i} onClick={() => setEditing(editing === i ? null : i)}>
                        {c.transition ? TRANSITION_LABELS[c.transition.type] : 'Hard cut'}
                      </button>
                    </td>
                    <td>
                      <button
                        className="link"
                        onClick={() => {
                          setEditing(null)
                          update({ ...spec, cuts: cuts.filter((_, j) => j !== i) }, 'restore cut')
                        }}
                      >
                        restore
                      </button>
                    </td>
                  </tr>
                  {editing === i && (
                    <tr>
                      <td colSpan={4}>
                        <TransitionPicker
                          value={c.transition}
                          onChange={(transition, reason) => update({ ...spec, cuts: cuts.map((x, j) => (j === i ? { ...x, transition } : x)) }, reason)}
                          onPreview={() => previewCut(c.end)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

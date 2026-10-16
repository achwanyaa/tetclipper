import { useEffect, useMemo, useRef, useState } from 'react'
import { Player, type PlayerRef } from '@remotion/player'
import {
  FPS,
  HEIGHT,
  VerticalClip,
  WIDTH,
  buildTimeline,
  clipSpecSchema,
  frameAtSource,
  sourceTimeAt,
  type ClipSpecInput
} from '@tetclipper/composition'
import { invoke, resolveForPlayer, type ClipData } from '../api'
import type { EditorState, Run } from '../App'
import { EffectsPanel } from './EffectsPanel'
import { IntroPanel } from './IntroPanel'
import { MusicPanel } from './MusicPanel'
import { StylePanel } from './StylePanel'
import { Transcript } from './Transcript'
import { TrimPanel } from './TrimPanel'

export interface PanelProps {
  data: ClipData
  spec: ClipSpecInput
  editor: EditorState
  setEditor: (fn: (s: EditorState) => EditorState) => void
  update: (next: ClipSpecInput, reason: string) => void
  seek: (sourceTime: number) => void
  setError: (e: string | null) => void
}

const TABS = ['Captions', 'Style', 'Intro', 'Music', 'Effects', 'Trim'] as const
type Tab = (typeof TABS)[number]

interface Props {
  data: ClipData
  spec: ClipSpecInput
  editor: EditorState
  setEditor: (s: EditorState | ((s: EditorState) => EditorState)) => void
  update: (next: ClipSpecInput, reason: string) => void
  undo: () => void
  run: Run | null
  onRender: () => void
  setError: (e: string | null) => void
}

export function Canvas({ data, spec, editor, setEditor, update, undo, run, onRender, setError }: Props) {
  const player = useRef<PlayerRef>(null)
  const [tab, setTab] = useState<Tab>('Captions')
  const [sending, setSending] = useState(false)

  const parsed = useMemo(() => {
    try {
      return clipSpecSchema.parse(spec)
    } catch {
      return null
    }
  }, [spec])
  const timeline = useMemo(() => (parsed ? buildTimeline(parsed, FPS) : null), [parsed])
  const inputProps = useMemo(() => resolveForPlayer(spec, data.jobDir), [spec, data.jobDir])

  // Track the playhead in source seconds (~8×/s is plenty for highlighting).
  useEffect(() => {
    const p = player.current
    if (!p || !timeline) return
    let last = 0
    const onFrame = (e: { detail: { frame: number } }) => {
      const now = performance.now()
      if (now - last < 120) return
      last = now
      const t = sourceTimeAt(timeline, e.detail.frame, FPS)
      setEditor((s) => ({ ...s, playhead: t }))
    }
    p.addEventListener('frameupdate', onFrame)
    p.addEventListener('seeked', onFrame)
    return () => {
      p.removeEventListener('frameupdate', onFrame)
      p.removeEventListener('seeked', onFrame)
    }
  }, [timeline, setEditor])

  const seek = (t: number) => {
    if (!timeline) return
    const f = frameAtSource(timeline, t, FPS)
    if (f !== null) player.current?.seekTo(f)
  }

  const rendering = run?.kind === 'render' && run.jobId === data.jobId && run.clip === data.clip
  const latestVersion = data.history[data.history.length - 1]?.version
  const renderFresh = data.render && data.render.spec_version === latestVersion
  const panel: PanelProps = { data, spec, editor, setEditor, update, seek, setError }

  return (
    <div className="canvas">
      <header className="toolbar">
        <div className="title" title={data.jobId}>
          {data.title} <span>· clip {data.clip + 1}</span>
        </div>
        <button onClick={undo} disabled={data.history.length < 2} title="Undo the last change (yours or Claude's)">
          ↶ Undo
        </button>
        <span className="muted small">v{latestVersion ?? 0}</span>
        <div className="spacer" />
        {data.render && (
          <>
            <a className="btn" href={`/files?path=${encodeURIComponent(data.render.output)}&download=1`}>
              ⬇ {renderFresh ? 'Download' : 'Download (older)'}
            </a>
            <button
              disabled={sending}
              onClick={async () => {
                setSending(true)
                try {
                  await invoke('studio_telegram', { jobId: data.jobId, clip: data.clip })
                } catch (e) {
                  setError(String((e as Error).message ?? e))
                } finally {
                  setSending(false)
                }
              }}
            >
              {sending ? 'Sending…' : '✈ Telegram'}
            </button>
          </>
        )}
        <button className="primary" onClick={onRender} disabled={rendering && !run?.error}>
          {rendering && !run?.error ? `Rendering ${Math.round((run?.fraction ?? 0) * 100)}%` : 'Render'}
        </button>
      </header>
      {rendering && run?.error && <div className="banner error">Render failed: {run.error}</div>}

      <div className="stage">
        {parsed && timeline ? (
          <Player
            ref={player}
            component={VerticalClip}
            inputProps={inputProps}
            durationInFrames={timeline.totalFrames}
            fps={FPS}
            compositionWidth={WIDTH}
            compositionHeight={HEIGHT}
            controls
            clickToPlay
            spaceKeyToPlayOrPause
            acknowledgeRemotionLicense
            style={{ height: '100%', aspectRatio: `${WIDTH} / ${HEIGHT}`, maxWidth: '100%' }}
          />
        ) : (
          <div className="banner error">This spec can't be previewed (invalid). Undo the last change.</div>
        )}
      </div>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>
      <section className="panel">
        {tab === 'Captions' && <Transcript {...panel} />}
        {tab === 'Style' && <StylePanel {...panel} />}
        {tab === 'Intro' && <IntroPanel {...panel} />}
        {tab === 'Music' && <MusicPanel {...panel} />}
        {tab === 'Effects' && <EffectsPanel {...panel} />}
        {tab === 'Trim' && <TrimPanel {...panel} />}
      </section>
    </div>
  )
}

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
import { ClaudeBar } from './ClaudeBar'
import { EffectsPanel } from './EffectsPanel'
import { IntroPanel } from './IntroPanel'
import { MusicPanel } from './MusicPanel'
import { StylePanel } from './StylePanel'
import { Timeline } from './Timeline'
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

const TABS = ['Captions', 'Look', 'Intro', 'Music', 'Effects', 'Trim'] as const
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

const clock = (frames: number) => {
  const s = frames / FPS
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
}

/** Edit step: big live preview, lane timeline and Claude bar on the left;
 *  the tool inspector with the render/share footer on the right. */
export function Canvas({ data, spec, editor, setEditor, update, undo, run, onRender, setError }: Props) {
  const player = useRef<PlayerRef>(null)
  const [tab, setTab] = useState<Tab>('Look')
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)

  const parsed = useMemo(() => {
    try {
      return clipSpecSchema.parse(spec)
    } catch {
      return null
    }
  }, [spec])
  const timeline = useMemo(() => (parsed ? buildTimeline(parsed, FPS) : null), [parsed])
  const inputProps = useMemo(() => resolveForPlayer(spec, data.jobDir), [spec, data.jobDir])

  // Track the playhead (~8×/s is plenty for highlighting) and play state.
  useEffect(() => {
    const p = player.current
    if (!p || !timeline) return
    let last = 0
    const onFrame = (e: { detail: { frame: number } }) => {
      const now = performance.now()
      if (now - last < 120) return
      last = now
      setFrame(e.detail.frame)
      setEditor((s) => ({ ...s, playhead: sourceTimeAt(timeline, e.detail.frame, FPS) }))
    }
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    p.addEventListener('frameupdate', onFrame)
    p.addEventListener('seeked', onFrame)
    p.addEventListener('play', onPlay)
    p.addEventListener('pause', onPause)
    p.addEventListener('ended', onPause)
    return () => {
      p.removeEventListener('frameupdate', onFrame)
      p.removeEventListener('seeked', onFrame)
      p.removeEventListener('play', onPlay)
      p.removeEventListener('pause', onPause)
      p.removeEventListener('ended', onPause)
    }
  }, [timeline, setEditor])

  // Space plays/pauses unless you're typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' || e.repeat) return
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, button, [contenteditable="true"]')) return
      e.preventDefault()
      player.current?.toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const seekFrame = (f: number) => {
    if (!timeline) return
    const clamped = Math.max(0, Math.min(timeline.totalFrames - 1, f))
    player.current?.seekTo(clamped)
    setFrame(clamped)
  }
  const seek = (t: number) => {
    if (!timeline) return
    const f = frameAtSource(timeline, t, FPS)
    if (f !== null) seekFrame(f)
  }

  const panel: PanelProps = { data, spec, editor, setEditor, update, seek, setError }
  const doubts = parsed?.doubts?.length ?? 0

  return (
    <div className="editor">
      <div className="editor-main">
        <div className="stage">
          {parsed && timeline ? (
            <>
              <div className="player">
                <Player
                  ref={player}
                  component={VerticalClip}
                  inputProps={inputProps}
                  durationInFrames={timeline.totalFrames}
                  fps={FPS}
                  compositionWidth={WIDTH}
                  compositionHeight={HEIGHT}
                  clickToPlay
                  acknowledgeRemotionLicense
                  style={{ width: '100%', height: '100%' }}
                />
              </div>
              <div className="controls-left">
                <button className="play" onClick={() => player.current?.toggle()} title={playing ? 'Pause (space)' : 'Play (space)'}>
                  {playing ? '❚❚' : '▶'}
                </button>
                <span className="time">
                  {clock(frame)} <span>/ {clock(timeline.totalFrames)}</span>
                </span>
              </div>
              <span className="live">Live preview · edits show instantly</span>
            </>
          ) : (
            <div className="invalid">This clip can't be previewed: the last change made it invalid. Undo it to get the preview back.</div>
          )}
        </div>

        {parsed && timeline && <Timeline timeline={timeline} spec={parsed} frame={frame} playhead={editor.playhead} seekFrame={seekFrame} seekSource={seek} />}

        <ClaudeBar data={data} editor={editor} canUndo={data.history.length > 1} onUndo={undo} />
      </div>

      <aside className="inspector">
        <nav className="insp-tabs">
          {TABS.map((t) => (
            <button key={t} className={t === tab ? 'on' : ''} onClick={() => setTab(t)}>
              {t}
              {t === 'Captions' && doubts > 0 && <span className="badge" title={`${doubts} doubtful captions`} />}
            </button>
          ))}
        </nav>
        <div className="insp-body">
          {doubts > 0 && tab !== 'Captions' && (
            <div className="doubt-nudge">
              <span>
                <b>
                  {doubts} caption {doubts === 1 ? 'spot' : 'spots'}
                </b>{' '}
                {doubts === 1 ? 'needs' : 'need'} a quick listen
              </span>
              <button onClick={() => setTab('Captions')}>Check now</button>
            </div>
          )}
          {tab === 'Captions' && <Transcript {...panel} />}
          {tab === 'Look' && <StylePanel {...panel} />}
          {tab === 'Intro' && <IntroPanel {...panel} />}
          {tab === 'Music' && <MusicPanel {...panel} />}
          {tab === 'Effects' && <EffectsPanel {...panel} />}
          {tab === 'Trim' && <TrimPanel {...panel} />}
        </div>
        <RenderFooter data={data} run={run} onRender={onRender} setError={setError} />
      </aside>
    </div>
  )
}

/** Render / share area at the foot of the inspector: rendering, failed,
 *  never rendered, up to date, or edited since the last render. */
function RenderFooter({ data, run, onRender, setError }: { data: ClipData; run: Run | null; onRender: () => void; setError: (e: string | null) => void }) {
  const [sending, setSending] = useState(false)
  const rendering = run?.kind === 'render' && run.jobId === data.jobId && run.clip === data.clip
  const latest = data.history[data.history.length - 1]?.version ?? 0
  const r = data.render
  const fresh = !!r && r.spec_version === latest
  const download = r ? `/files?path=${encodeURIComponent(r.output)}&download=1` : ''

  const telegram = (
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
      {sending ? 'Sending…' : 'Telegram'}
    </button>
  )

  if (rendering && !run?.error) {
    const pct = Math.round((run?.fraction ?? 0) * 100)
    return (
      <div className="insp-foot">
        <div className="status">
          <span className="dot ac" />
          Rendering v{latest} in the cloud · keep editing
        </div>
        <div className="render-bar">
          <div style={{ width: `${pct}%` }} />
          <span>
            Rendering <span className="mono">{pct}%</span>
          </span>
        </div>
        <span className="small muted" style={{ textAlign: 'center' }}>
          {run?.message || 'About a minute for a 2-minute clip'}
        </span>
      </div>
    )
  }

  return (
    <div className="insp-foot">
      {rendering && run?.error ? (
        <div className="status dg">
          <span className="dot dg" />
          Render failed: {run.error}. Your edits are safe.
        </div>
      ) : !r ? (
        <div className="status">
          <span className="dot" />
          Not rendered yet
        </div>
      ) : fresh ? (
        <div className="status">
          <span className="dot ok" />
          Rendered v{r.spec_version} · up to date
        </div>
      ) : (
        <div className="status">
          <span className="dot wn" />
          Edited since the last render{r.spec_version ? ` (v${r.spec_version})` : ''}
        </div>
      )}

      {r && fresh ? (
        <a className="btn primary big" href={download}>
          Download
        </a>
      ) : (
        <button className="primary big" onClick={onRender}>
          {rendering && run?.error ? 'Render again' : r ? 'Render new version' : 'Render'}
        </button>
      )}

      {r && (
        <div className="more">
          {!fresh && (
            <a className="btn" href={download}>
              Download older
            </a>
          )}
          {telegram}
        </div>
      )}
    </div>
  )
}

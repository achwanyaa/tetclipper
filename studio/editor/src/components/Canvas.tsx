import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Player, type PlayerRef } from '@remotion/player'
import {
  FPS,
  VerticalClip,
  buildTimeline,
  clipSpecSchema,
  frameAtSource,
  frameSize,
  sourceTimeAt,
  type ClipSpecInput,
  type Timeline as TL
} from '@tetclipper/composition'
import { fileUrl, invoke, resolveForPlayer, type ClipData } from '../api'
import type { EditorState, Run } from '../App'
import { stopPreview } from '../audioPreview'
import { useChat } from '../chat'
import { AiChat } from './AiChat'
import { EffectsPanel } from './EffectsPanel'
import { IntroPanel } from './IntroPanel'
import { MusicPanel } from './MusicPanel'
import { OverlayLayer } from './OverlayLayer'
import { OverlaysPanel } from './OverlaysPanel'
import { StylePanel } from './StylePanel'
import { Timeline, fxLabel, type PlayerControls } from './Timeline'
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
  timeline: TL | null
  previewFrame: (frame: number) => void // seek there and play
  pausePlayer: () => void
}

type Tab = 'AI' | 'Captions' | 'Look' | 'Intro & outro' | 'Music' | 'Effects' | 'Overlays' | 'Trim'

// Rail buttons: label, short label, icon path (24×24, stroked).
const TABS: { id: Tab; short: string; icon: string }[] = [
  { id: 'AI', short: 'AI', icon: 'M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z' },
  { id: 'Captions', short: 'Captions', icon: 'M4 6h16v12H4zM7 14h4M13 14h4M7 10h10' },
  { id: 'Look', short: 'Look', icon: 'M4 5h7v7H4zM13 5h7v7h-7zM4 14h7v5H4zM13 14h7v5h-7z' },
  { id: 'Intro & outro', short: 'Intro', icon: 'M4 5h16v14H4zM10 9l5 3-5 3z' },
  { id: 'Music', short: 'Music', icon: 'M9 18V6l10-2v12M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0zM19 16a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z' },
  { id: 'Effects', short: 'Effects', icon: 'M5 19L16 8M14 4v3M19 9h-3M18 5l-1.5 1.5M11 5l1 1M19 13l-1-1' },
  { id: 'Overlays', short: 'Overlays', icon: 'M4 8h12v12H4zM8 8V4h12v12h-4' },
  { id: 'Trim', short: 'Trim', icon: 'M8 7.5L20 18M8 16.5L20 6M8 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0z' }
]

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
  online?: boolean // hosted app: Telegram is linked per server, not per user, so it's hidden
  admin?: boolean
}

const clock = (frames: number) => {
  const s = frames / FPS
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
}

/** Edit step: every tool and the AI chat on the left, a big live preview, and
 *  the lane timeline along the bottom. */
export function Canvas({ data, spec, editor, setEditor, update, undo, run, onRender, setError, online = false, admin = false }: Props) {
  const player = useRef<PlayerRef>(null)
  const [tab, setTab] = useState<Tab>('AI')
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [selectedEffect, setSelectedEffect] = useState<number | null>(null)
  const [selectedOverlay, setSelectedOverlay] = useState<string | null>(null)
  const chat = useChat(data, editor)
  // A seek reports the same spot twice (ours, then the player's): render once.
  const setPlayhead = useCallback((t: number | null) => setEditor((s) => (s.playhead === t ? s : { ...s, playhead: t })), [setEditor])

  const parsed = useMemo(() => {
    try {
      return clipSpecSchema.parse(spec)
    } catch {
      return null
    }
  }, [spec])
  const timeline = useMemo(() => (parsed ? buildTimeline(parsed, FPS) : null), [parsed])
  const inputProps = useMemo(() => resolveForPlayer(spec, data.jobDir, data.preview), [spec, data.jobDir, data.preview])
  const size = parsed ? frameSize(parsed.format) : null

  // Something else removed the selected overlay or effect (undo, the AI).
  useEffect(() => {
    if (selectedOverlay && !parsed?.overlays.some((o) => o.id === selectedOverlay)) setSelectedOverlay(null)
    if (selectedEffect !== null && selectedEffect >= (parsed?.effects.length ?? 0)) setSelectedEffect(null)
  }, [parsed, selectedOverlay, selectedEffect])

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
      setPlayhead(sourceTimeAt(timeline, e.detail.frame, FPS))
    }
    const onSeeked = (e: { detail: { frame: number } }) => {
      last = performance.now()
      setFrame(e.detail.frame)
      setPlayhead(sourceTimeAt(timeline, e.detail.frame, FPS))
    }
    const onPlay = () => {
      stopPreview() // the clip and a track preview never play over each other
      setPlaying(true)
    }
    const onPause = () => setPlaying(false)
    p.addEventListener('frameupdate', onFrame)
    p.addEventListener('seeked', onSeeked)
    p.addEventListener('play', onPlay)
    p.addEventListener('pause', onPause)
    p.addEventListener('ended', onPause)
    return () => {
      p.removeEventListener('frameupdate', onFrame)
      p.removeEventListener('seeked', onSeeked)
      p.removeEventListener('play', onPlay)
      p.removeEventListener('pause', onPause)
      p.removeEventListener('ended', onPause)
    }
  }, [timeline, setPlayhead])

  // Space plays/pauses unless you're typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' || e.repeat) return
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, button, [contenteditable="true"], [role="slider"]')) return
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
    setPlayhead(sourceTimeAt(timeline, clamped, FPS))
  }
  const seek = (t: number) => {
    if (!timeline) return
    const f = frameAtSource(timeline, t, FPS)
    if (f !== null) seekFrame(f)
  }

  const previewFrame = (f: number) => {
    seekFrame(f)
    player.current?.play()
  }
  const pausePlayer = () => player.current?.pause()
  const controls: PlayerControls = {
    play: () => player.current?.play(),
    pause: () => player.current?.pause(),
    isPlaying: () => player.current?.isPlaying() ?? false
  }

  const openEffect = (index: number) => {
    setTab('Effects')
    setSelectedEffect(index)
    const e = parsed?.effects[index]
    if (e) seek(e.at)
  }
  const openOverlay = (id: string) => {
    setTab('Overlays')
    setSelectedOverlay(id)
  }
  const changeOverlay = (id: string, patch: Record<string, unknown>, reason: string) =>
    update({ ...spec, overlays: (spec.overlays ?? []).map((o) => (o.id === id ? { ...o, ...patch } : o)) }, reason)
  const timeOverlay = (id: string, from: number | null, to: number | null) => {
    setSelectedOverlay(id)
    setTab('Overlays')
    changeOverlay(id, { from, to }, 'overlay timing')
  }

  // Delete (or Backspace) removes what's highlighted: the selected overlay, or
  // the effect open in the Effects tab. Undo brings it back.
  const removeSelected = useRef<() => boolean>(() => false)
  removeSelected.current = () => {
    if (tab === 'Overlays' && selectedOverlay) {
      update({ ...spec, overlays: (spec.overlays ?? []).filter((o) => o.id !== selectedOverlay) }, 'remove overlay')
      setSelectedOverlay(null)
      return true
    }
    if (tab === 'Effects' && selectedEffect !== null && spec.effects?.[selectedEffect]) {
      update({ ...spec, effects: (spec.effects ?? []).filter((_, i) => i !== selectedEffect) }, `remove ${fxLabel(spec.effects[selectedEffect].type)}`)
      setSelectedEffect(null)
      return true
    }
    return false
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key !== 'Delete' && e.key !== 'Backspace') || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, [contenteditable="true"]')) return
      if (removeSelected.current()) e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const panel: PanelProps = { data, spec, editor, setEditor, update, seek, setError, timeline, previewFrame, pausePlayer }
  const doubts = parsed?.doubts?.length ?? 0
  const lastReason = data.history[data.history.length - 1]?.reason ?? ''
  const lastChangeByAi = /^ai\b/i.test(lastReason)

  return (
    <div className="editor">
      <aside className="side">
        <nav className="rail" aria-label="Tools">
          {TABS.map((t) => (
            <button key={t.id} className={t.id === tab ? 'on' : ''} aria-current={t.id === tab ? 'page' : undefined} onClick={() => setTab(t.id)} title={t.id}>
              <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d={t.icon} />
              </svg>
              <span>{t.short}</span>
              {t.id === 'Captions' && doubts > 0 && <i className="badge" title={`${doubts} doubtful captions`} />}
              {t.id === 'AI' && chat.busy && tab !== 'AI' && <i className="badge ac" title="AI is working" />}
            </button>
          ))}
        </nav>
        <div className="side-panel">
          <div className={`insp-body ${tab === 'AI' ? 'chat' : ''}`}>
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
            {tab === 'AI' && <AiChat chat={chat} editor={editor} lastChangeByAi={lastChangeByAi} onUndo={undo} />}
            {tab === 'Captions' && <Transcript {...panel} />}
            {tab === 'Look' && <StylePanel {...panel} />}
            {tab === 'Intro & outro' && <IntroPanel {...panel} />}
            {tab === 'Music' && <MusicPanel {...panel} />}
            {tab === 'Effects' && <EffectsPanel {...panel} open={selectedEffect} setOpen={setSelectedEffect} />}
            {tab === 'Overlays' && <OverlaysPanel {...panel} selected={selectedOverlay} setSelected={setSelectedOverlay} admin={admin} />}
            {tab === 'Trim' && <TrimPanel {...panel} />}
          </div>
          <RenderFooter data={data} run={run} onRender={onRender} setError={setError} online={online} />
        </div>
      </aside>

      <div className="editor-main">
        <div className="stage">
          {parsed && timeline && size ? (
            <div className={`player ${parsed.format}`}>
              <Player
                ref={player}
                component={VerticalClip}
                inputProps={inputProps}
                durationInFrames={timeline.totalFrames}
                fps={FPS}
                compositionWidth={size.width}
                compositionHeight={size.height}
                clickToPlay
                showPosterWhenBuffering
                renderPoster={() => <div className="player-buffering">Loading…</div>}
                acknowledgeRemotionLicense
                style={{ width: '100%', height: '100%', borderRadius: 12, overflow: 'hidden' }}
              />
              <OverlayLayer
                overlays={parsed.overlays}
                timeline={timeline}
                frame={frame}
                frameWidth={size.width}
                frameHeight={size.height}
                selected={selectedOverlay}
                onSelect={openOverlay}
                onChange={changeOverlay}
              />
            </div>
          ) : (
            <div className="invalid">This clip can't be previewed: the last change made it invalid. Undo it to get the preview back.</div>
          )}
        </div>
        {parsed && timeline && (
          <div className="stage-bar">
            <button className="play" onClick={() => player.current?.toggle()} aria-label={playing ? 'Pause' : 'Play'} title={playing ? 'Pause (space)' : 'Play (space)'}>
              {playing ? '❚❚' : '▶'}
            </button>
            <span className="time">
              {clock(frame)} <span>/ {clock(timeline.totalFrames)}</span>
            </span>
            <span className="spacer" />
            <span className="live">{data.previewing ? 'Preparing a faster preview…' : 'Live preview · edits show instantly'}</span>
          </div>
        )}
      </div>

      {parsed && timeline && (
        <Timeline
          timeline={timeline}
          spec={parsed}
          frame={frame}
          playing={playing}
          playhead={editor.playhead}
          seekFrame={seekFrame}
          seekSource={seek}
          player={controls}
          selectedEffect={tab === 'Effects' ? selectedEffect : null}
          onEffect={openEffect}
          selectedOverlay={selectedOverlay}
          onOverlay={openOverlay}
          onOverlayTime={timeOverlay}
        />
      )}
    </div>
  )
}

/** Render / share area at the foot of the left panel: rendering, failed,
 *  never rendered, up to date, or edited since the last render. */
function RenderFooter({ data, run, onRender, setError, online }: { data: ClipData; run: Run | null; onRender: () => void; setError: (e: string | null) => void; online: boolean }) {
  const [sending, setSending] = useState(false)
  const rendering = run?.kind === 'render' && run.jobId === data.jobId && run.clip === data.clip
  const latest = data.history[data.history.length - 1]?.version ?? 0
  const r = data.render
  const fresh = !!r && r.spec_version === latest
  const download = r ? fileUrl(r.output, true) : ''

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

      {r && (!fresh || !online) && (
        <div className="more">
          {!fresh && (
            <a className="btn" href={download}>
              Download older
            </a>
          )}
          {!online && telegram}
        </div>
      )}
    </div>
  )
}

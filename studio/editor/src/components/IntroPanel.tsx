import { useState } from 'react'
import { FPS } from '@tetclipper/composition'
import { invoke, mediaUrl, upload } from '../api'
import type { PanelProps } from './Canvas'
import { TransitionPicker } from './TransitionPicker'

const MAX_IMAGE = 5
const MAX_VIDEO = 30

function BookendCard({ side, data, spec, update, setError, timeline, previewFrame }: PanelProps & { side: 'intro' | 'outro' }) {
  const item = spec[side] ?? null
  const label = side === 'intro' ? 'Intro' : 'Outro'
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [mediaLength, setMediaLength] = useState<number | null>(null)
  const isVideo = item?.kind === 'video'
  const set = (patch: Record<string, unknown>, reason: string) => item && update({ ...spec, [side]: { ...item, ...patch } }, reason)

  const attach = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    try {
      const path = await upload(file)
      const res = await invoke<{ src: string; kind: string; duration?: number; hasAudio?: boolean }>('studio_attach', { jobId: data.jobId, clip: data.clip, path })
      if (res.kind !== 'image' && res.kind !== 'video') throw new Error('Use an image or a video.')
      const video = res.kind === 'video'
      setMediaLength(video && res.duration ? res.duration : null)
      update(
        {
          ...spec,
          [side]: {
            src: res.src,
            kind: res.kind,
            fit: item?.fit ?? 'cover',
            duration: video ? Math.max(0.5, Math.min(MAX_VIDEO, res.duration || 5)) : Math.min(MAX_IMAGE, isVideo ? 2 : item?.duration ?? 2),
            volume: video && res.hasAudio === false ? 0 : 1,
            transition: item?.transition ?? null
          }
        },
        `${side} ${res.kind}`
      )
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const preview = () => {
    if (!timeline) return
    previewFrame(Math.max(0, (side === 'intro' ? timeline.introFrames : timeline.outroStart) - FPS))
  }

  const url = item ? mediaUrl(data.jobDir, item.src) : ''
  const maxLength = isVideo ? Math.min(MAX_VIDEO, mediaLength ?? MAX_VIDEO) : MAX_IMAGE

  return (
    <section className="bookend-card">
      <div className="row">
        <b>{label}</b>
        <span className="spacer" />
        {item && (
          <button className="link" onClick={() => update({ ...spec, [side]: null }, `remove ${side}`)}>
            remove
          </button>
        )}
      </div>
      <div className="intro-panel">
        <label
          className={`drop ${over ? 'over' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            attach(e.dataTransfer.files[0])
          }}
        >
          {busy ? (
            <span>Uploading…</span>
          ) : item ? (
            isVideo ? (
              <video src={url} muted playsInline preload="metadata" onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setMediaLength(e.currentTarget.duration)} />
            ) : (
              <img src={url} alt={side} />
            )
          ) : (
            <span>Drop a flyer or short video, or click to choose</span>
          )}
          <input type="file" accept="image/*,video/*" hidden onChange={(e) => attach(e.target.files?.[0])} />
        </label>
        {item && (
          <div className="controls">
            <label>
              On screen <span>{(item.duration ?? 2).toFixed(1)} s</span>
              <input type="range" min={0.5} max={maxLength} step={0.1} value={Math.min(item.duration ?? 2, maxLength)} onChange={(e) => set({ duration: +e.target.value }, `${side} length`)} />
            </label>
            {isVideo && (
              <label>
                Its sound <span>{Math.round((item.volume ?? 1) * 100)}%</span>
                <input type="range" min={0} max={1} step={0.01} value={item.volume ?? 1} onChange={(e) => set({ volume: +e.target.value }, `${side} volume`)} />
              </label>
            )}
            <div className="row">
              <label className="toggle">
                <input type="radio" name={`${side}-fit`} checked={(item.fit ?? 'cover') === 'cover'} onChange={() => set({ fit: 'cover' }, `${side} fill`)} />
                Fill frame
              </label>
              <label className="toggle">
                <input type="radio" name={`${side}-fit`} checked={item.fit === 'contain'} onChange={() => set({ fit: 'contain' }, `${side} fit`)} />
                Fit (blurred edges)
              </label>
            </div>
          </div>
        )}
      </div>
      {item && (
        <div className="field">
          <span className="label">{side === 'intro' ? 'Into the video' : 'Out of the video'}</span>
          <TransitionPicker value={item.transition} onChange={(transition, reason) => set({ transition }, `${side} ${reason}`)} onPreview={preview} />
        </div>
      )}
    </section>
  )
}

/** Full-screen flyers or short videos before and after the clip. */
export function IntroPanel(props: PanelProps) {
  return (
    <div className="bookends-panel">
      <BookendCard {...props} side="intro" />
      <BookendCard {...props} side="outro" />
    </div>
  )
}

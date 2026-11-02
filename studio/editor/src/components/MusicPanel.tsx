import { useEffect, useState } from 'react'
import { FPS } from '@tetclipper/composition'
import { fileUrl, invoke, mediaUrl, onEvent, upload } from '../api'
import { playPreview, stopPreview, useAudioPreview } from '../audioPreview'
import type { PanelProps } from './Canvas'
import { MusicRange } from './MusicRange'

interface Track {
  id: string
  path: string
  name: string
  duration: number
  bpm: number | null
  tags: string[]
  licence: string | null
}

const fileName = (src: string) => src.split('/').pop() ?? src

const seconds = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

/** Music bed: pick from the local library (hear it first) or upload a track;
 *  the part of it to use, volume, ducking, fades. */
export function MusicPanel({ data, spec, update, setError, timeline, pausePlayer }: PanelProps) {
  const music = spec.music ?? null
  const [tracks, setTracks] = useState<Track[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [keys, setKeys] = useState<{ jamendo: boolean; freesound: boolean } | null>(null)
  const [key, setKey] = useState('')
  const preview = useAudioPreview()

  useEffect(() => {
    invoke<{ has_jamendo_key: boolean; has_freesound_key: boolean }>('audio_keys_status')
      .then((k) => setKeys({ jamendo: k.has_jamendo_key, freesound: k.has_freesound_key }))
      .catch(() => setKeys(null))
  }, [])

  const loadLibrary = () =>
    invoke<{ ok: boolean; items: Track[] }>('audio_list', { kind: 'music' })
      .then((r) => setTracks(r.items ?? []))
      .catch(() => setTracks([]))

  useEffect(() => {
    loadLibrary()
    return onEvent((ev) => {
      if (busy === 'pack' && (ev.event === 'result' || ev.event === 'exited')) {
        setBusy(null)
        loadLibrary()
      }
    })
  }, [busy])

  const use = async (path: string, label: string) => {
    setBusy(label)
    try {
      const { src } = await invoke<{ src: string }>('studio_attach', { jobId: data.jobId, clip: data.clip, path })
      update({ ...spec, music: { volume: 0.25, duck: 0.35, fadeIn: 1, fadeOut: 1.5, loop: true, ...music, src, offset: 0, end: null } }, `music: ${label}`)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => stopPreview, []) // leaving the tab ends any preview

  const set = (patch: Record<string, unknown>, reason: string) => music && update({ ...spec, music: { ...music, ...patch } }, reason)

  return (
    <div className="music-panel">
      {music ? (
        <div className="controls">
          <div className="row">
            <strong>♪ {fileName(music.src)}</strong>
            <button className="link" onClick={() => update({ ...spec, music: null }, 'remove music')}>
              remove
            </button>
          </div>
          <MusicRange
            url={mediaUrl(data.jobDir, music.src)}
            start={music.offset ?? 0}
            end={music.end ?? null}
            clipSeconds={(timeline?.totalFrames ?? 0) / FPS}
            loop={music.loop ?? true}
            beforePlay={pausePlayer}
            onChange={(offset, end, reason) => set({ offset, end }, reason)}
          />
          <label>
            Volume <span>{Math.round((music.volume ?? 0.25) * 100)}%</span>
            <input type="range" min={0} max={1} step={0.01} value={music.volume ?? 0.25} onChange={(e) => set({ volume: +e.target.value }, 'music volume')} />
          </label>
          <label>
            Under speech <span>{Math.round((music.duck ?? 0.35) * 100)}% of that</span>
            <input type="range" min={0} max={1} step={0.01} value={music.duck ?? 0.35} onChange={(e) => set({ duck: +e.target.value }, 'music ducking')} />
          </label>
          <div className="row">
            <label>
              Fade in <span>{(music.fadeIn ?? 1).toFixed(1)} s</span>
              <input type="range" min={0} max={5} step={0.1} value={music.fadeIn ?? 1} onChange={(e) => set({ fadeIn: +e.target.value }, 'music fade in')} />
            </label>
            <label>
              Fade out <span>{(music.fadeOut ?? 1.5).toFixed(1)} s</span>
              <input type="range" min={0} max={5} step={0.1} value={music.fadeOut ?? 1.5} onChange={(e) => set({ fadeOut: +e.target.value }, 'music fade out')} />
            </label>
            <label className="toggle">
              <input type="checkbox" checked={music.loop ?? true} onChange={(e) => set({ loop: e.target.checked }, 'music loop')} />
              Loop
            </label>
          </div>
        </div>
      ) : (
        <p className="muted small">No music. Pick a track below, upload one, or ask AI.</p>
      )}

      <div className="row music-actions">
        <label className="btn">
          {busy === 'upload' ? 'Uploading…' : '⬆ Upload a track'}
          <input
            type="file"
            accept="audio/*"
            hidden
            onChange={async (e) => {
              const file = e.target.files?.[0]
              if (!file) return
              setBusy('upload')
              try {
                await use(await upload(file), file.name)
              } catch (err) {
                setError(String((err as Error).message ?? err))
                setBusy(null)
              }
            }}
          />
        </label>
        {tracks.length === 0 && keys && !keys.jamendo && !keys.freesound && (
          <>
            <input placeholder="free Jamendo client id" value={key} onChange={(e) => setKey(e.target.value)} />
            <button
              disabled={!key.trim()}
              onClick={async () => {
                try {
                  await invoke('save_jamendo_key', { key: key.trim() })
                  setKeys({ ...keys, jamendo: true })
                } catch (e) {
                  setError(String((e as Error).message ?? e))
                }
              }}
            >
              Save key
            </button>
            <a className="small" href="https://devportal.jamendo.com/" target="_blank" rel="noreferrer">
              get one (free)
            </a>
          </>
        )}
        {tracks.length === 0 && (!keys || keys.jamendo || keys.freesound) && (
          <button
            disabled={busy === 'pack'}
            onClick={async () => {
              setBusy('pack')
              try {
                await invoke('run_audio_bootstrap')
              } catch (e) {
                setError(String((e as Error).message ?? e))
                setBusy(null)
              }
            }}
          >
            {busy === 'pack' ? 'Fetching free tracks…' : 'Get a free (CC0) starter pack'}
          </button>
        )}
      </div>

      {tracks.length > 0 && (
        <ul className="track-list">
          {tracks.map((t) => {
            const url = fileUrl(t.path)
            const playing = preview.playing && preview.url === url
            return (
              <li key={t.id} className={playing ? 'playing' : ''}>
                <button
                  className="round-play"
                  aria-label={playing ? `Pause ${t.name}` : `Play ${t.name}`}
                  onClick={() => {
                    if (playing) return stopPreview()
                    pausePlayer()
                    playPreview(url)
                  }}
                >
                  {playing ? '❚❚' : '▶'}
                </button>
                <div className="track-text">
                  <b>{t.name}</b>
                  <span className="muted small">{[seconds(t.duration), t.bpm ? `${Math.round(t.bpm)} bpm` : '', ...t.tags.slice(0, 2)].filter(Boolean).join(' · ')}</span>
                  {playing && t.duration > 0 && (
                    <span className="track-progress">
                      <i style={{ width: `${Math.min(100, (preview.time / t.duration) * 100)}%` }} />
                    </span>
                  )}
                </div>
                <button className="sm" disabled={!!busy} onClick={() => use(t.path, t.name)}>
                  Use
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

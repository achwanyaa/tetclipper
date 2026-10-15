import { useState } from 'react'
import { invoke, mediaUrl, upload } from '../api'
import type { PanelProps } from './Canvas'

/** The full-screen still shown before the clip. */
export function IntroPanel({ data, spec, update, setError }: PanelProps) {
  const intro = spec.intro ?? null
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)

  const attach = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    try {
      const path = await upload(file)
      const { src } = await invoke<{ src: string }>('studio_attach', { jobId: data.jobId, clip: data.clip, path })
      update({ ...spec, intro: { duration: intro?.duration ?? 2, fit: intro?.fit ?? 'cover', src } }, 'intro photo')
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  return (
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
        {intro ? <img src={mediaUrl(data.jobDir, intro.src)} alt="intro" /> : <span>{busy ? 'Uploading…' : 'Drop a photo here or click to choose'}</span>}
        <input type="file" accept="image/*" hidden onChange={(e) => attach(e.target.files?.[0])} />
      </label>
      {intro && (
        <div className="controls">
          <label>
            Duration <span>{intro.duration?.toFixed(1)} s</span>
            <input type="range" min={0.5} max={5} step={0.1} value={intro.duration ?? 2} onChange={(e) => update({ ...spec, intro: { ...intro, duration: +e.target.value } }, 'intro duration')} />
          </label>
          <div className="row">
            <label className="toggle">
              <input type="radio" checked={(intro.fit ?? 'cover') === 'cover'} onChange={() => update({ ...spec, intro: { ...intro, fit: 'cover' } }, 'intro fill')} />
              Fill frame
            </label>
            <label className="toggle">
              <input type="radio" checked={intro.fit === 'contain'} onChange={() => update({ ...spec, intro: { ...intro, fit: 'contain' } }, 'intro fit')} />
              Fit (blurred edges)
            </label>
            <button className="link" onClick={() => update({ ...spec, intro: null }, 'remove intro')}>
              remove
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

import { PRESETS } from '@tetclipper/composition'
import { fmt, type JobSummary } from '../api'
import type { Run } from '../App'
import type { FindArgs } from './NewClip'

export const STILL = (s: string) => `${import.meta.env.BASE_URL}styles/${s}.png`

/** Found moments are "moment N"; clips cut from an exact range are "clip N". */
export const clipName = (c: { clip: number; score: number | null }) => `${c.score != null ? 'moment' : 'clip'} ${c.clip + 1}`

interface Props {
  jobs: JobSummary[]
  loadError: string | null
  run: Run | null
  onOpen: (jobId: string, clip: number) => void
  onNew: () => void
  onFind: (args: FindArgs) => void
  onDismissRun: () => void
  onDismissJob: (jobId: string) => void
  onRetry: () => void
}

/** Until the download finishes the job has no title yet, only its id. */
const displayTitle = (job: JobSummary) => (job.title && job.title !== job.id ? job.title : 'New video')

function RunCard({ title, fraction, message, error, onDismiss }: { title: string; fraction: number; message: string; error: string | null; onDismiss: () => void }) {
  return (
    <div className={`card run-card ${error ? 'failed' : ''}`}>
      <div className="top">
        <b>{title}</b>
        {error ? (
          <button className="link small muted" onClick={onDismiss}>
            Dismiss
          </button>
        ) : (
          <span className="small muted mono">{Math.round(fraction * 100)}%</span>
        )}
      </div>
      <div className="progress">
        <div style={{ width: `${Math.round((error ? 1 : fraction) * 100)}%`, background: error ? 'var(--dg)' : undefined }} />
      </div>
      <span style={{ fontSize: 13 }}>{error ? <b style={{ color: 'var(--dg)' }}>{error}</b> : message}</span>
      {!error && <span className="small muted">You can close this tab. It keeps going on the server.</span>}
    </div>
  )
}

/** All clips: running jobs on top, then every clip grouped by the video it came from. */
export function Home({ jobs, loadError, run, onOpen, onNew, onFind, onDismissRun, onDismissJob, onRetry }: Props) {
  const clipCount = jobs.reduce((n, j) => n + j.clips.length, 0)
  const videos = new Set(jobs.filter((j) => j.clips.length).map((j) => j.title)).size
  // Running and failed jobs as the server sees them; the local card only covers
  // the moment before the server has the job, and renders (not jobs).
  const serverRuns = jobs.filter((j) => j.progress && (j.progress.state === 'running' || j.progress.state === 'failed'))
  const showLocal = !!run && (run.kind === 'render' || !jobs.some((j) => j.id === run.jobId || j.progress?.state === 'running'))
  const busy = (!!run && !run.error) || serverRuns.some((j) => j.progress?.state === 'running')

  return (
    <div className="home">
      <div className="home-head">
        <div className="spacer" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <h1>Your clips</h1>
          <span className="muted">
            {clipCount} {clipCount === 1 ? 'clip' : 'clips'} from {videos} {videos === 1 ? 'video' : 'videos'}
          </span>
        </div>
        <button className="primary lg" onClick={onNew}>
          + New clip
        </button>
      </div>

      {(serverRuns.length > 0 || showLocal) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <span className="section-title">In progress</span>
          <div className="runs">
            {serverRuns.map((job) => (
              <RunCard
                key={job.id}
                title={`${job.progress!.label ?? 'Working'} · ${displayTitle(job)}`}
                fraction={job.progress!.fraction}
                message={job.progress!.message}
                error={job.progress!.state === 'failed' ? job.progress!.error || 'The job failed.' : null}
                onDismiss={() => onDismissJob(job.id)}
              />
            ))}
            {showLocal && run && (
              <RunCard
                title={run.kind === 'find' ? 'Finding moments' : run.kind === 'cut' ? 'Cutting a clip' : `Rendering clip ${(run.clip ?? 0) + 1}`}
                fraction={run.fraction}
                message={run.message}
                error={run.error ?? null}
                onDismiss={onDismissRun}
              />
            )}
          </div>
        </div>
      )}

      {loadError && (
        <div className="note dg" style={{ maxWidth: 560 }}>
          <b>Couldn't load your clips</b>
          <span>The tetclipper server didn't answer ({loadError}).</span>
          <div>
            <button className="sm" style={{ background: 'var(--sf)' }} onClick={onRetry}>
              Try again
            </button>
          </div>
        </div>
      )}

      {!loadError && jobs.length === 0 && !run && (
        <div className="card empty-card">
          <b style={{ fontSize: 16 }}>No clips yet</b>
          <span className="muted">Paste a video link and pick a range, or let Claude find the best moments.</span>
          <button className="tonal" onClick={onNew}>
            + New clip
          </button>
        </div>
      )}

      {jobs.filter((j) => j.clips.length > 0 || !serverRuns.includes(j)).map((job) => (
        <div key={job.id} className="video-group">
          <div className="head">
            <span className="section-title">{displayTitle(job)}</span>
            <span className="muted" style={{ fontSize: 13 }}>
              {job.section ? `${fmt(job.section[0])} – ${fmt(job.section[1])} · ` : ''}
              {job.clips.length} {job.clips.length === 1 ? 'clip' : 'clips'}
            </span>
            {job.height != null && job.height < 720 && (
              <span className="tag wn" title="The video in Drive is low resolution, so vertical clips cut from it look soft. Upload a sharper original to Drive for better clips.">
                {job.height}p source: clips will look soft
              </span>
            )}
            <span className="spacer" />
            <button
              className="link"
              disabled={busy}
              onClick={() => onFind({ source: job.id, top: 5 })}
              title="Claude finds the best moments in this slice (reuses the analysis)"
            >
              Find more moments
            </button>
          </div>
          {job.clips.length === 0 ? (
            <span className="muted small">No clip yet.</span>
          ) : (
            <div className="clip-cards">
              {job.clips.map((c) => (
                <button key={c.clip} className="clip-card" title={c.summary ?? undefined} onClick={() => onOpen(job.id, c.clip)}>
                  <div className="thumb">
                    <img src={STILL(c.style ?? 'hormozi')} alt="" loading="lazy" />
                    {c.score != null && <span className="score">Score {Math.round(c.score)}</span>}
                  </div>
                  <div className="meta">
                    <div className="name">
                      {clipName(c)}
                      <span>{c.style ? PRESETS[c.style as keyof typeof PRESETS]?.label ?? c.style : ''}</span>
                    </div>
                    {c.rendered ? <span className="tag ok">Rendered</span> : <span className="tag">Not rendered</span>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

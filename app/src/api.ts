import { fileUrl, invoke } from './backend'
import type { UpdateNotice,
  JobTranscript,
  TelegramStatus,
  RemoteJobs,
  ChatMessage,
  AudioItem,
  AudioKeysStatus,
  JobResults,
  JobSummary,
  LibraryItem,
  LoopOverview,
  OnlineAudioResult,
  SetupState,
  SyncSummary
} from './types'

export const api = {
  runJob: (source: string, llm: string, captions: string, language?: string) =>
    invoke<void>('run_job', { source, llm, captions, language }),
  resumeJob: (jobId: string, llm?: string, captions?: string, camera?: string) =>
    invoke<void>('resume_job', { jobId, llm, captions, camera }),
  jobResults: (jobId: string) => invoke<JobResults>('job_results', { jobId }),
  listJobs: () => invoke<JobSummary[]>('list_job_dirs'),
  /** How many pipeline runs are alive on the server (0 after a restart). */
  pipelineActive: () => invoke<{ running: number }>('pipeline_active'),
  jobTranscript: (jobId: string) => invoke<JobTranscript>('job_transcript', { jobId }),
  /** Cut a hand-picked source range into a new clip (streams pipeline-event). */
  addClipRange: (jobId: string, start: number, end: number, captions: string, camera: string) =>
    invoke<void>('add_clip_range', { jobId, start, end, captions, camera }),
  saveGeminiKey: (key: string) => invoke<boolean>('save_gemini_key', { key }),
  setupState: () => invoke<SetupState>('get_setup_state'),
  markOnboarded: () => invoke<void>('mark_onboarded'),
  checkOllama: () => invoke<{ running: boolean; models: string[] }>('check_ollama'),
  exportClip: (path: string, title?: string) =>
    invoke<string>('export_clip', { path, title }),
  igStatus: () => invoke<{ connected: boolean; username?: string }>('ig_status'),
  igSync: () => invoke<SyncSummary>('ig_tool', { args: ['sync'] }),
  igOverview: () => invoke<LoopOverview>('ig_tool', { args: ['overview'] }),
  igLink: (jobId: string, clip: number, mediaId: string, source: 'manual' | 'match_confirmed') =>
    invoke<{ ok: boolean }>('ig_tool', {
      args: ['link', jobId, String(clip), mediaId, '--source', source]
    }),
  igUnlink: (mediaId: string) =>
    invoke<{ ok: boolean }>('ig_tool', { args: ['unlink', mediaId] }),
  igReject: (mediaId: string, jobId: string, clip: number) =>
    invoke<{ ok: boolean }>('ig_tool', { args: ['reject', mediaId, jobId, String(clip)] }),
  /** one GET to GitHub's latest release on launch; offline it says nothing */
  checkUpdate: () => invoke<UpdateNotice>('check_update'),
  fileUrl,

  /* ---------- music / sfx library ---------- */
  audioImport: (paths: string[], kind: 'auto' | 'music' | 'sfx') =>
    invoke<{ ok: boolean; items: LibraryItem[]; error?: string }>('audio_import', { paths, kind }),
  audioList: (kind?: 'music' | 'sfx', query?: string) =>
    invoke<{ ok: boolean; items: LibraryItem[] }>('audio_list', { kind, query }),
  audioRemove: (id: string) => invoke<{ ok: boolean }>('audio_remove', { id }),
  audioSearch: (
    query: string,
    source: 'freesound' | 'jamendo' | 'all',
    kind: 'music' | 'sfx',
    maxDuration: number | undefined,
    allowAttribution: boolean
  ) =>
    invoke<{ ok: boolean; results: OnlineAudioResult[]; error?: string }>('audio_search', {
      query, source, kind, maxDuration, allowAttribution
    }),
  audioFetch: (source: 'freesound' | 'jamendo', sourceId: string) =>
    invoke<{ ok: boolean; item?: LibraryItem; error?: string }>('audio_fetch', { source, sourceId }),
  audioSuggest: (jobId: string, clip: number) =>
    invoke<{ ok: boolean; audio: AudioItem[]; error?: string }>('audio_suggest', { jobId, clip }),
  saveFreesoundKey: (key: string) => invoke<boolean>('save_freesound_key', { key }),
  saveJamendoKey: (key: string) => invoke<boolean>('save_jamendo_key', { key }),
  audioKeysStatus: () => invoke<AudioKeysStatus>('audio_keys_status'),
  runAudioBootstrap: () => invoke<void>('run_audio_bootstrap'),

  /* ---------- chat with Claude Code about one video ---------- */
  chatHistory: (jobId: string) =>
    invoke<{ session_id: string | null; messages: ChatMessage[]; available: boolean }>('chat_history', { jobId }),
  /** Starts one turn; replies stream as pipeline-event {event: 'chat'}. */
  chatSend: (jobId: string, message: string) => invoke<void>('chat_send', { jobId, message }),
  chatReset: (jobId: string) => invoke<void>('chat_reset', { jobId }),

  /* ---------- hybrid: analyse on the hosted GPU, render here ---------- */
  /** Range mode: fetch only start-end (source seconds) and cut it (streams). */
  cutRange: (source: string, start: number, end: number, captions: string, language?: string) =>
    invoke<void>('cut_range', { source, start, end, captions, language }),
  /** Download here, upload to the hosted GPU, start it there (streams). */
  pushJob: (source: string, llm: string, captions: string) =>
    invoke<void>('push_job', { source, llm, captions }),
  remoteJobs: () => invoke<RemoteJobs>('remote_jobs'),
  /** Pull a hosted job to this machine and render it (streams pipeline-event). */
  pullJob: (jobId: string) => invoke<void>('pull_job', { jobId }),

  /* ---------- telegram delivery ---------- */
  telegramStatus: () => invoke<TelegramStatus>('telegram_status'),
  telegramSaveToken: (token: string) => invoke<TelegramStatus>('telegram_save_token', { token }),
  telegramLink: () => invoke<TelegramStatus>('telegram_link'),
  telegramSend: (jobId: string, clip: number, caption?: string) =>
    invoke<{ ok: boolean; error?: string; as_video?: boolean; saved?: string }>('telegram_send', {
      jobId,
      clip,
      caption
    })
}

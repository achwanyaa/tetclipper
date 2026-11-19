// The AI chat for the open clip. It lives in the editor (Canvas), not in the
// AI tab, so a reply that arrives while another tab is open isn't lost.
import { useCallback, useEffect, useState } from 'react'
import { invoke, onEvent, type ChatMessage, type ClipData } from './api'
import type { EditorState } from './App'

export interface Chat {
  messages: ChatMessage[]
  busy: boolean
  live: string // the reply as it streams in
  notes: string[] // what the AI is doing right now
  available: boolean
  notice: string | null
  send: (text: string, withContext: boolean) => Promise<void>
  reset: () => Promise<void>
}

export function useChat(data: ClipData, editor: EditorState): Chat {
  const [messages, setMessages] = useState<ChatMessage[]>(data.chat.messages)
  const [busy, setBusy] = useState(data.chat.busy)
  const [live, setLive] = useState('')
  const [notes, setNotes] = useState<string[]>([])

  // Reloaded from the server (e.g. back from a pause): the server's record wins.
  useEffect(() => {
    setMessages(data.chat.messages)
    setBusy(data.chat.busy)
  }, [data.chat])

  useEffect(
    () =>
      onEvent((ev) => {
        if (ev.event !== 'studio-chat' || ev.job_id !== data.jobId || ev.clip !== data.clip) return
        if (ev.kind === 'delta') setLive((t) => t + (ev.text ?? ''))
        else if (ev.kind === 'text') {
          setMessages((m) => [...m, { role: 'assistant', text: ev.text ?? '' }])
          setLive('')
        } else if (ev.kind === 'tool') setNotes((n) => [...n.slice(-3), ev.text ?? ''])
        else if (ev.kind === 'done') {
          // API providers report what the turn cost.
          if (ev.cost != null)
            setMessages((m) => {
              const i = m.map((x) => x.role).lastIndexOf('assistant')
              return i < 0 ? m : m.map((x, k) => (k === i ? { ...x, cost: ev.cost } : x))
            })
          if (ev.error) setMessages((m) => [...m, { role: 'error', text: ev.error ?? '' }])
          setBusy(false)
          setLive('')
          setNotes([])
        }
      }),
    [data.jobId, data.clip]
  )

  const send = useCallback(
    async (text: string, withContext: boolean) => {
      const message = text.trim()
      if (!message || busy) return
      setMessages((m) => [...m, { role: 'user', text: message }])
      setBusy(true)
      try {
        await invoke('studio_chat_send', {
          jobId: data.jobId,
          clip: data.clip,
          message,
          context: withContext ? { playhead: editor.playhead, selection: editor.selection } : null
        })
      } catch (e) {
        setMessages((m) => [...m, { role: 'error', text: String((e as Error).message ?? e) }])
        setBusy(false)
      }
    },
    [busy, data.jobId, data.clip, editor.playhead, editor.selection]
  )

  const reset = useCallback(async () => {
    await invoke('studio_chat_reset', { jobId: data.jobId, clip: data.clip })
    setMessages([])
  }, [data.jobId, data.clip])

  return { messages, busy, live, notes, available: data.chat.available, notice: data.chat.notice ?? null, send, reset }
}

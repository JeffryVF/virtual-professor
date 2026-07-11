'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Loader2, PhoneOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { localAvatarConnect, speakInSession, getSessionHistory, endSession } from '@/lib/api'
import type { Source } from '@/app/session/ChatBubble'
import ChatBubble from '@/app/session/ChatBubble'
import TalkingHeadAvatar from '@/components/student/TalkingHeadAvatar'
import type { TalkingHeadAvatarHandle } from '@/components/student/TalkingHeadAvatar'

interface Message { role: string; content: string; timestamp: string; sources?: Source[] }

interface Props {
  sessionId: string
  onEnded: () => void
}

type Status = 'loading' | 'ready' | 'error' | 'audio-only'

const SILENT_WAV_DATA_URI =
  'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQQAAAAAAA=='

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'object' && err !== null && 'detail' in err) {
    const detail = (err as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const message = (err as { message?: unknown }).message
    if (typeof message === 'string') return message
  }
  return String(err)
}

export default function AvatarSession({ sessionId, onEnded }: Props) {
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const statusRef = useRef<Status>('loading')
  const cancelledRef = useRef(false)
  const isConnectingRef = useRef(false)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const avatarRef = useRef<TalkingHeadAvatarHandle | null>(null)
  const localAudioRef = useRef<HTMLAudioElement | null>(null)

  const [status, setStatus] = useState<Status>('loading')
  const [recording, setRecording] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [history, setHistory] = useState<Message[]>([])
  const historyRef = useRef<HTMLDivElement>(null)

  const updateStatus = useCallback((s: Status) => {
    statusRef.current = s
    setStatus(s)
  }, [])

  const handleAvatarUnavailable = useCallback(() => {
    updateStatus('audio-only')
  }, [updateStatus])

  useEffect(() => {
    cancelledRef.current = false
    void init()

    return () => {
      cancelledRef.current = true
      cleanup()
    }
  }, [sessionId, updateStatus])

  useEffect(() => {
    historyRef.current?.scrollTo({ top: historyRef.current.scrollHeight, behavior: 'smooth' })
  }, [history])

  async function init() {
    if (isConnectingRef.current) return
    isConnectingRef.current = true
    updateStatus('loading')

    try {
      const resp = await localAvatarConnect(sessionId)
      if (cancelledRef.current) return

      if (resp.status === 'ok') {
        updateStatus('ready')
      }

      // Fetch conversation history after successful connect
      const msgs = await getSessionHistory(sessionId)
      setHistory(msgs)
    } catch (err) {
      if (cancelledRef.current) return
      const msg = getErrorMessage(err)
      toast.error(msg)
      updateStatus('error')
    } finally {
      isConnectingRef.current = false
    }
  }

  function cleanup() {
    try {
      recorderRef.current?.stream.getTracks().forEach(track => track.stop())
    } catch { /* stream may already be stopped */ }
    recorderRef.current = null

    try {
      mediaStreamRef.current?.getTracks().forEach(track => track.stop())
    } catch { /* stream may already be stopped */ }
    mediaStreamRef.current = null
  }

  async function unlockLocalAudio() {
    if (!localAudioRef.current) {
      localAudioRef.current = new Audio()
      localAudioRef.current.preload = 'auto'
    }

    const audio = localAudioRef.current
    if (!audio.paused || audio.currentTime > 0) return

    audio.muted = true
    audio.src = SILENT_WAV_DATA_URI
    try {
      await audio.play()
      audio.pause()
      audio.currentTime = 0
    } finally {
      audio.muted = false
    }
  }

  async function getAudioDurationMs(wavBuffer: ArrayBuffer) {
    const audioContext = new AudioContext()
    try {
      const decoded = await audioContext.decodeAudioData(wavBuffer.slice(0))
      return decoded.duration * 1000
    } finally {
      await audioContext.close()
    }
  }

  async function playAudioLocally(wavBuffer: ArrayBuffer) {
    const audio = localAudioRef.current ?? new Audio()
    localAudioRef.current = audio

    const objectUrl = URL.createObjectURL(new Blob([wavBuffer], { type: 'audio/wav' }))
    audio.pause()
    audio.src = objectUrl
    audio.onended = () => {
      setSpeaking(false)
      URL.revokeObjectURL(objectUrl)
    }
    audio.onerror = () => {
      setSpeaking(false)
      URL.revokeObjectURL(objectUrl)
    }

    setSpeaking(true)
    await audio.play()
  }

  async function startRecording() {
    if (processing || (status !== 'ready' && status !== 'audio-only')) return
    try {
      avatarRef.current?.unlockAudio().catch((error) => {
        console.warn('Avatar audio unlock failed; playback may require another user gesture.', error)
      })
      unlockLocalAudio().catch((error) => {
        console.warn('Local audio unlock failed; playback may require another user gesture.', error)
      })
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      recorder.start()
      setRecording(true)
    } catch (err) {
      const message = err instanceof DOMException
        ? (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError'
          ? 'Permiso de cámara/micrófono falló'
          : err.name === 'NotFoundError'
            ? 'No se encontró cámara/micrófono'
            : err.name === 'NotReadableError'
              ? 'La cámara/micrófono está siendo usado por otra aplicación'
              : 'Permiso de cámara/micrófono falló')
        : 'Permiso de cámara/micrófono falló'
      toast.error(message)
    }
  }

  function stopRecording() {
    return new Promise<Blob>((resolve) => {
      const recorder = recorderRef.current!
      const mimeType = recorder.mimeType || 'audio/webm'
      recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: mimeType }))
      recorder.stop()
      recorder.stream.getTracks().forEach(t => t.stop())
      mediaStreamRef.current = null
    })
  }

  async function handlePushToTalkEnd() {
    if (!recording) return
    setRecording(false)

    setProcessing(true)
    try {
      const audioBlob = await stopRecording()
      if (audioBlob.size < 1024) {
        toast.error('Recording too short — please hold the mic button a bit longer.')
        setProcessing(false)
        return
      }
      const result = await speakInSession(sessionId, audioBlob)

      const msgs = await getSessionHistory(sessionId)
      setHistory(msgs)
      const latestProfessorMessage = [...msgs]
        .reverse()
        .find((message) => message.role === 'professor' || message.role === 'assistant')
      const speechText = latestProfessorMessage?.content ?? ''

      if (result.kind === 'audio') {
        void playAudioLocally(result.buffer).catch((error) => {
          console.error('Failed to play spoken response.', error)
          toast.error('No se pudo reproducir la respuesta de audio.')
        })

        if (statusRef.current === 'ready') {
          if (speechText) {
            void avatarRef.current?.playSpeech({ audioBuffer: result.buffer.slice(0), text: speechText })
              .catch((error) => {
                console.warn('Avatar lip-sync animation failed.', error)
              })
          } else {
            void getAudioDurationMs(result.buffer).then((durationMs) => {
              avatarRef.current?.animateMouth(durationMs)
            }).catch((error) => {
              console.warn('Avatar mouth animation failed.', error)
            })
          }
        }
      } else if (result.kind === 'text-only') {
        toast.warning('Audio was unavailable. The full answer is in the conversation.')
      }
    } catch (err) {
      toast.error(getErrorMessage(err))
    } finally {
      setProcessing(false)
    }
  }

  async function handleEndSession() {
    cancelledRef.current = true
    isConnectingRef.current = false
    cleanup()
    await endSession(sessionId)
    onEnded()
  }

  return (
    <div className="flex h-full gap-6">
      <div className="flex flex-col flex-1 gap-4">
        <div className="relative flex-1 bg-black rounded-xl overflow-hidden min-h-0">
          {status === 'ready' ? (
            <TalkingHeadAvatar
              ref={avatarRef}
              onUnavailable={handleAvatarUnavailable}
              onSpeakingChange={setSpeaking}
            />
          ) : status === 'loading' ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white bg-black/60">
              <Loader2 className="h-8 w-8 animate-spin" />
              <span className="text-sm">Connecting&hellip;</span>
            </div>
          ) : status === 'error' ? (
            <div className="absolute inset-0 flex items-center justify-center text-white bg-black/70 text-sm">
              Connection failed. Please try again.
            </div>
          ) : status === 'audio-only' ? (
            <div className="absolute inset-0 flex items-center justify-center text-white bg-black/70 text-sm">
              Audio-only mode — avatar unavailable
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-center gap-4">
          <button
            onPointerDown={(event) => {
              event.preventDefault()
              void startRecording()
            }}
            onPointerUp={(event) => {
              event.preventDefault()
              void handlePushToTalkEnd()
            }}
            onPointerCancel={(event) => {
              event.preventDefault()
              if (recording) void handlePushToTalkEnd()
            }}
            disabled={status === 'loading' || status === 'error' || processing}
            className={cn(
              'w-20 h-20 rounded-full flex items-center justify-center shadow-lg transition-all select-none',
              recording
                ? 'bg-red-500 scale-110 shadow-red-300'
                : processing
                ? 'bg-muted text-muted-foreground'
                : 'bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95'
            )}
          >
            {processing
              ? <Loader2 className="h-7 w-7 animate-spin" />
              : recording
              ? <MicOff className="h-7 w-7 text-white" />
              : <Mic className="h-7 w-7" />
            }
          </button>

          <Button variant="outline" size="icon" className="h-10 w-10 rounded-full" onClick={handleEndSession}>
            <PhoneOff className="h-4 w-4 text-destructive" />
          </Button>
        </div>

        <p className="text-center text-xs text-muted-foreground">
          {recording ? 'Release to send' : processing ? 'Processing…' : 'Hold to speak'}
        </p>
      </div>

      <div className="w-72 shrink-0 flex flex-col bg-white rounded-xl border">
        <div className="px-4 py-3 border-b text-sm font-medium">Conversation</div>
        <div ref={historyRef} className="flex-1 overflow-y-auto p-4 space-y-3 text-sm">
          {history.length === 0
            ? <p className="text-muted-foreground text-xs text-center mt-8">No messages yet.</p>
            : history.map((msg) => (
                <ChatBubble
                  key={msg.timestamp}
                  message={{ id: msg.timestamp, ...msg }}
                />
              ))
          }
        </div>
      </div>
    </div>
  )
}

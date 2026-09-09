'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Loader2, PhoneOff, Send } from 'lucide-react'
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

const SPEECH_RECOGNITION_SUPPORTED =
  typeof window !== 'undefined' &&
  ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

function getRecognitionClass(): any {
  const win = window as unknown as Record<string, unknown>
  return win.SpeechRecognition ?? win.webkitSpeechRecognition
}

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
  const statusRef = useRef<Status>('loading')
  const cancelledRef = useRef(false)
  const isConnectingRef = useRef(false)
  const avatarRef = useRef<TalkingHeadAvatarHandle | null>(null)
  const localAudioRef = useRef<HTMLAudioElement | null>(null)
  const recognitionRef = useRef<any | null>(null)
  const finalTranscriptRef = useRef('')

  const [status, setStatus] = useState<Status>('loading')
  const [recording, setRecording] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [textInput, setTextInput] = useState('')
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
      stopRecognition()
      cleanup()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      localAudioRef.current?.pause()
    } catch { /* ignore */ }
    recognitionRef.current = null
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

  async function getAudioDurationMs(audioBuffer: ArrayBuffer) {
    const audioContext = new AudioContext()
    try {
      const decoded = await audioContext.decodeAudioData(audioBuffer.slice(0))
      return decoded.duration * 1000
    } finally {
      await audioContext.close()
    }
  }

  async function playAudioLocally(audioBuffer: ArrayBuffer) {
    const audio = localAudioRef.current ?? new Audio()
    localAudioRef.current = audio

    const objectUrl = URL.createObjectURL(new Blob([audioBuffer], { type: 'audio/mpeg' }))
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

  function stopRecognition() {
    try {
      recognitionRef.current?.stop()
    } catch { /* already stopped */ }
  }

  function startRecording() {
    if (processing || (statusRef.current !== 'ready' && statusRef.current !== 'audio-only')) return
    if (!SPEECH_RECOGNITION_SUPPORTED) {
      toast.error('El reconocimiento de voz no está disponible en este navegador. Usa el campo de texto.')
      return
    }

    avatarRef.current?.unlockAudio().catch((error) => {
      console.warn('Avatar audio unlock failed; playback may require another user gesture.', error)
    })
    unlockLocalAudio().catch((error) => {
      console.warn('Local audio unlock failed; playback may require another user gesture.', error)
    })

    try {
      const SR = getRecognitionClass()
      const recognition = new SR()
      recognitionRef.current = recognition
      finalTranscriptRef.current = ''

      recognition.lang = '' // browser default; supports both ES and EN teachers
      recognition.interimResults = false
      recognition.continuous = false
      recognition.maxAlternatives = 1

      recognition.onresult = (event: any) => {
        let transcript = ''
        for (let i = 0; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript
        }
        finalTranscriptRef.current = transcript
      }

      recognition.onerror = (event: any) => {
        if (cancelledRef.current) return
        if (event.error === 'no-speech') return
        if (event.error === 'aborted') return
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          toast.error('Permiso de micrófono denegado. Usa el campo de texto.')
        } else if (event.error === 'network') {
          console.warn('Speech recognition network failure:', event.error)
          setRecording(false)
          recognitionRef.current = null
          toast.error('No se pudo conectar con el servicio de voz. Usa el campo de texto para hacerme tu pregunta.')
        } else {
          console.warn('Speech recognition error:', event.error)
        }
      }

      recognition.onend = () => {
        recognitionRef.current = null
        setRecording(false)
        const transcript = finalTranscriptRef.current.trim()
        if (transcript) void processTranscript(transcript)
      }

      recognition.start()
      setRecording(true)
    } catch (err) {
      toast.error('No se pudo iniciar el reconocimiento de voz.')
      console.error('SpeechRecognition start failed:', err)
    }
  }

  async function processTranscript(transcript: string) {
    const clean = transcript.trim()
    if (!clean) return
    if (processing) return

    setProcessing(true)
    try {
      const result = await speakInSession(sessionId, clean)

      if (result.kind === 'audio') {
        void playAudioLocally(result.buffer).catch((error) => {
          console.error('Failed to play spoken response.', error)
          toast.error('No se pudo reproducir la respuesta de audio.')
        })

        void getSessionHistory(sessionId).then((msgs) => {
          setHistory(msgs)
          const latestProfessorMessage = [...msgs]
            .reverse()
            .find((message) => message.role === 'professor' || message.role === 'assistant')
          const speechText = latestProfessorMessage?.content ?? ''

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
        }).catch((error) => {
          console.warn('Failed to refresh session history:', error)
        })
      } else if (result.kind === 'text-only') {
        void getSessionHistory(sessionId).then(setHistory).catch((error) => {
          console.warn('Failed to refresh session history:', error)
        })
        toast.warning('Audio was unavailable. The full answer is in the conversation.')
      }
    } catch (err) {
      toast.error(getErrorMessage(err))
    } finally {
      setProcessing(false)
    }
  }

  function handleTextSubmit() {
    const text = textInput.trim()
    if (!text) return
    setTextInput('')
    void processTranscript(text)
  }

  async function handleEndSession() {
    cancelledRef.current = true
    isConnectingRef.current = false
    stopRecognition()
    cleanup()
    await endSession(sessionId)
    onEnded()
  }

  const micDisabled = status === 'loading' || status === 'error' || processing

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
          {SPEECH_RECOGNITION_SUPPORTED ? (
            <button
              onPointerDown={(event) => {
                event.preventDefault()
                void startRecording()
              }}
              onPointerUp={(event) => {
                event.preventDefault()
                stopRecognition()
              }}
              onPointerCancel={(event) => {
                event.preventDefault()
                stopRecognition()
              }}
              disabled={micDisabled}
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
          ) : (
            <div className="text-xs text-muted-foreground max-w-60 text-center">
              Tu navegador no soporta reconocimiento de voz. Usa el campo de texto para hablar con el profesor.
            </div>
          )}

          <Button variant="outline" size="icon" className="h-10 w-10 rounded-full" onClick={handleEndSession}>
            <PhoneOff className="h-4 w-4 text-destructive" />
          </Button>
        </div>

        <p className="text-center text-xs text-muted-foreground">
          {recording ? 'Release to send' : processing ? 'Processing…' : speaking ? 'Speaking…' : 'Hold to speak'}
        </p>

        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            handleTextSubmit()
          }}
        >
          <input
            type="text"
            value={textInput}
            onChange={(event) => setTextInput(event.target.value)}
            placeholder="O escribe tu pregunta…"
            disabled={processing || status === 'loading' || status === 'error'}
            className="flex-1 rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <Button type="submit" size="icon" disabled={!textInput.trim() || processing} className="shrink-0">
            <Send className="h-4 w-4" />
          </Button>
        </form>
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
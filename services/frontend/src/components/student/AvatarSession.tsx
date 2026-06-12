'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Room, RoomEvent, Track } from 'livekit-client'
import { Mic, MicOff, Loader2, PhoneOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { connectLiveAvatar, speakInSession, getSessionHistory, endSession } from '@/lib/api'

interface Message { role: string; content: string; timestamp: string }

interface Props {
  sessionId: string
  onEnded: () => void
}

type Status = 'connecting' | 'connected' | 'audio-only' | 'error'

export default function AvatarSession({ sessionId, onEnded }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const roomRef = useRef<Room | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const statusRef = useRef<Status>('connecting')

  const [status, setStatus] = useState<Status>('connecting')
  const [recording, setRecording] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [history, setHistory] = useState<Message[]>([])
  const historyRef = useRef<HTMLDivElement>(null)

  const updateStatus = useCallback((s: Status) => {
    statusRef.current = s
    setStatus(s)
  }, [])

  useEffect(() => { init() }, [sessionId])

  useEffect(() => {
    historyRef.current?.scrollTo({ top: historyRef.current.scrollHeight, behavior: 'smooth' })
  }, [history])

  async function init() {
    try {
      try {
        const creds = await connectLiveAvatar(sessionId)

        const room = new Room()
        roomRef.current = room

        room.on(RoomEvent.TrackSubscribed, (track) => {
          if (track.kind === Track.Kind.Video && videoRef.current) {
            track.attach(videoRef.current)
          }
          if (track.kind === Track.Kind.Audio) {
            track.attach()
          }
        })

        room.on(RoomEvent.Disconnected, () => {
          if (statusRef.current !== 'error') {
            toast.warning('Avatar video connection lost. Falling back to audio-only.')
            updateStatus('audio-only')
          }
        })

        await room.connect(creds.livekit_url, creds.livekit_client_token)

        const ws = new WebSocket(creds.ws_url)
        wsRef.current = ws

        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data)
            if (msg.type === 'session.state_updated' && msg.state === 'connected') {
              updateStatus('connected')
            }
          } catch { /* ignore malformed ws messages */ }
        }
        ws.onerror = () => { /* handled by onclose */ }
        ws.onclose = () => {
          if (statusRef.current === 'connected' || statusRef.current === 'connecting') {
            toast.warning('Avatar connection lost. Falling back to audio-only.')
            updateStatus('audio-only')
          }
        }

        updateStatus('connected')
      } catch (connectErr) {
        const msg = connectErr instanceof Error ? connectErr.message : String(connectErr)
        if (msg.includes('503') || msg.includes('4032') || msg.toLowerCase().includes('concurrency limit')) {
          toast.warning('LiveAvatar is busy right now. Falling back to audio-only mode.')
          updateStatus('audio-only')
        } else {
          throw connectErr
        }
      }

      const msgs = await getSessionHistory(sessionId)
      setHistory(msgs)

    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(`Avatar connection failed: ${msg}`)
      updateStatus('error')
    }
  }

  function cleanup() {
    roomRef.current?.disconnect()
    wsRef.current?.close()
  }

  function extractPCM(buffer: ArrayBuffer): ArrayBuffer {
    const view = new DataView(buffer)
    let offset = 12
    while (offset < buffer.byteLength - 8) {
      const id = String.fromCharCode(
        view.getUint8(offset), view.getUint8(offset + 1),
        view.getUint8(offset + 2), view.getUint8(offset + 3)
      )
      const size = view.getUint32(offset + 4, true)
      if (id === 'data') return buffer.slice(offset + 8, offset + 8 + size)
      offset += 8 + size
    }
    return buffer.slice(44)
  }

  function bufferToBase64(buffer: ArrayBuffer): string {
    const bytes = new Uint8Array(buffer)
    let binary = ''
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
    return btoa(binary)
  }

  async function sendAudioToAvatar(wavBuffer: ArrayBuffer) {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    const pcm = extractPCM(wavBuffer)
    const CHUNK = 24000 * 2

    for (let offset = 0; offset < pcm.byteLength; offset += CHUNK) {
      ws.send(JSON.stringify({
        type: 'agent.speak',
        audio: bufferToBase64(pcm.slice(offset, offset + CHUNK)),
      }))
    }
    ws.send(JSON.stringify({ type: 'agent.speak_end' }))
  }

  async function playAudioLocally(wavBuffer: ArrayBuffer) {
    const audio = new Audio(URL.createObjectURL(new Blob([wavBuffer], { type: 'audio/wav' })))
    await audio.play()
  }

  async function startRecording() {
    if (processing || (status !== 'connected' && status !== 'audio-only')) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      recorder.start()
      setRecording(true)

      if (status === 'connected') {
        wsRef.current?.send(JSON.stringify({ type: 'agent.start_listening' }))
      }
    } catch {
      toast.error('Microphone access denied')
    }
  }

  function stopRecording() {
    return new Promise<Blob>((resolve) => {
      const recorder = recorderRef.current!
      const mimeType = recorder.mimeType || 'audio/webm'
      recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: mimeType }))
      recorder.stop()
      recorder.stream.getTracks().forEach(t => t.stop())
    })
  }

  async function handlePushToTalkEnd() {
    if (!recording) return
    setRecording(false)
    if (status === 'connected' && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'agent.stop_listening' }))
    }

    setProcessing(true)
    try {
      const audioBlob = await stopRecording()
      if (audioBlob.size < 1024) {
        toast.error('Recording too short — please hold the mic button a bit longer.')
        setProcessing(false)
        return
      }
      const wavBuffer = await speakInSession(sessionId, audioBlob)

      const msgs = await getSessionHistory(sessionId)
      setHistory(msgs)

      if (status === 'connected' && wsRef.current?.readyState === WebSocket.OPEN) {
        await sendAudioToAvatar(wavBuffer)
      } else {
        await playAudioLocally(wavBuffer)
      }
    } catch (err) {
      toast.error(String(err))
    } finally {
      setProcessing(false)
    }
  }

  async function handleEndSession() {
    cleanup()
    await endSession(sessionId)
    onEnded()
  }

  return (
    <div className="flex h-full gap-6">
      <div className="flex flex-col flex-1 gap-4">
        <div className="relative flex-1 bg-black rounded-xl overflow-hidden min-h-0">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            className="w-full h-full object-cover"
          />
          {status === 'connecting' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white bg-black/60">
              <Loader2 className="h-8 w-8 animate-spin" />
              <span className="text-sm">Connecting to avatar&hellip;</span>
            </div>
          )}
          {status === 'error' && (
            <div className="absolute inset-0 flex items-center justify-center text-white bg-black/70 text-sm">
              Connection failed. Please try again.
            </div>
          )}
        </div>

        <div className="flex items-center justify-center gap-4">
          <button
            onMouseDown={startRecording}
            onMouseUp={handlePushToTalkEnd}
            onTouchStart={startRecording}
            onTouchEnd={handlePushToTalkEnd}
            disabled={status === 'connecting' || status === 'error' || processing}
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
          {status === 'audio-only'
            ? recording ? 'Release to send' : processing ? 'Processing…' : 'Hold to speak'
            : recording ? 'Release to send' : processing ? 'Processing…' : 'Hold to speak'}
        </p>
      </div>

      <div className="w-72 shrink-0 flex flex-col bg-white rounded-xl border">
        <div className="px-4 py-3 border-b text-sm font-medium">Conversation</div>
        <div ref={historyRef} className="flex-1 overflow-y-auto p-4 space-y-3 text-sm">
          {history.length === 0
            ? <p className="text-muted-foreground text-xs text-center mt-8">No messages yet.</p>
            : history.map((msg) => (
                <div
                  key={msg.timestamp}
                  className={cn(
                    'rounded-lg px-3 py-2 max-w-full',
                    msg.role === 'student'
                      ? 'bg-primary/10 text-right ml-4'
                      : 'bg-muted mr-4'
                  )}
                >
                  <p className="text-xs font-medium text-muted-foreground mb-0.5 capitalize">{msg.role}</p>
                  <p>{msg.content}</p>
                </div>
              ))
          }
        </div>
      </div>
    </div>
  )
}

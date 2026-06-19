'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Room, RoomEvent, Track } from 'livekit-client'
import { Mic, MicOff, Loader2, PhoneOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { connectLiveAvatar, speakInSession, getSessionHistory, endSession, stopLiveAvatarSession } from '@/lib/api'
import type { Source } from '@/app/session/ChatBubble'
import ChatBubble from '@/app/session/ChatBubble'

interface Message { role: string; content: string; timestamp: string; sources?: Source[] }

interface Props {
  sessionId: string
  onEnded: () => void
}

type Status = 'connecting' | 'connected' | 'audio-only' | 'error'
const LIVEAVATAR_CONNECT_RETRIES = 3
const LIVEAVATAR_RETRY_DELAYS_MS = [1000, 2000, 4000]
type ConnectionStage = 'idle' | 'fetching-creds' | 'livekit-connecting' | 'ws-validating' | 'ready' | 'stopping'

class AvatarSessionError extends Error {
  constructor(
    public kind: 'backend' | 'capacity' | 'invalid-response' | 'room' | 'microphone' | 'unknown',
    message: string,
  ) {
    super(message)
    this.name = 'AvatarSessionError'
  }
}

function getApiErrorStatus(err: unknown): number | undefined {
  if (typeof err === 'object' && err !== null && 'status' in err) {
    const status = (err as { status?: unknown }).status
    return typeof status === 'number' ? status : undefined
  }
  return undefined
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

function getApiErrorDetail(err: unknown): string | undefined {
  if (typeof err === 'object' && err !== null && 'detail' in err) {
    const detail = (err as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return undefined
}

function isCapacityFailure(err: unknown): boolean {
  const status = getApiErrorStatus(err)
  const message = getErrorMessage(err).toLowerCase()
  return status === 503 || message.includes('capacity') || message.includes('concurrency limit') || message.includes('busy right now')
}

function isProviderInternalFailure(err: unknown): boolean {
  const status = getApiErrorStatus(err)
  const message = getErrorMessage(err).toLowerCase()
  return (
    (typeof status === 'number' && status >= 500 && status !== 503) ||
    message.includes('internal server error') ||
    message.includes('code":5000') ||
    message.includes('code=5000')
  )
}

function isAuthFailure(err: unknown): boolean {
  const status = getApiErrorStatus(err)
  const message = getErrorMessage(err).toLowerCase()
  return status === 401 || message.includes('session expired') || message.includes('sesión expiró')
}

function validateLiveAvatarConnectResponse(creds: Partial<{
  livekit_url: string
  livekit_client_token: string
  ws_url: string
  liveavatar_session_id: string
}>): asserts creds is {
  livekit_url: string
  livekit_client_token: string
  ws_url: string
  liveavatar_session_id: string
} {
  const missing = [
    !creds.livekit_url && 'livekit_url',
    !creds.livekit_client_token && 'livekit_client_token',
    !creds.ws_url && 'ws_url',
    !creds.liveavatar_session_id && 'liveavatar_session_id',
  ].filter(Boolean)

  if (missing.length > 0) {
    throw new AvatarSessionError('invalid-response', `LiveAvatar response missing required fields: ${missing.join(', ')}`)
  }
}

function waitForWebSocketReady(ws: WebSocket, timeoutMs = 15000): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup()
      reject(new AvatarSessionError('room', 'No se pudo crear la room'))
    }, timeoutMs)

    const cleanup = () => {
      window.clearTimeout(timeout)
      ws.removeEventListener('message', onMessage)
      ws.removeEventListener('error', onError)
      ws.removeEventListener('close', onClose)
    }

    const onMessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(String(event.data))
        if (msg.type === 'session.state_updated' && msg.state === 'connected') {
          cleanup()
          resolve()
        }
      } catch {
        // ignore malformed events
      }
    }

    const onError = () => {
      cleanup()
      reject(new AvatarSessionError('room', 'No se pudo crear la room'))
    }

    const onClose = () => {
      cleanup()
      reject(new AvatarSessionError('room', 'No se pudo crear la room'))
    }

    ws.addEventListener('message', onMessage)
    ws.addEventListener('error', onError)
    ws.addEventListener('close', onClose)
  })
}

export default function AvatarSession({ sessionId, onEnded }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const roomRef = useRef<Room | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const statusRef = useRef<Status>('connecting')
  const cancelledRef = useRef(false)
  const isConnectingRef = useRef(false)
  const connectionStageRef = useRef<ConnectionStage>('idle')
  const liveavatarSessionIdRef = useRef<string | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)

  const [status, setStatus] = useState<Status>('connecting')
  const [recording, setRecording] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [history, setHistory] = useState<Message[]>([])
  const historyRef = useRef<HTMLDivElement>(null)

  const updateStatus = useCallback((s: Status) => {
    statusRef.current = s
    setStatus(s)
  }, [])

  useEffect(() => {
    cancelledRef.current = false
    void init()

    return () => {
      cancelledRef.current = true
      void stopLiveAvatarIfNeeded('USER_DISCONNECTED')
      cleanup()
    }
  }, [sessionId, updateStatus])

  useEffect(() => {
    historyRef.current?.scrollTo({ top: historyRef.current.scrollHeight, behavior: 'smooth' })
  }, [history])

  async function init() {
    if (isConnectingRef.current) return
    isConnectingRef.current = true
    connectionStageRef.current = 'fetching-creds'
    updateStatus('connecting')

    try {
      try {
        const creds = await connectLiveAvatarWithRetry(sessionId)
        liveavatarSessionIdRef.current = creds.liveavatar_session_id
        validateLiveAvatarConnectResponse(creds)

        if (cancelledRef.current) {
          await stopLiveAvatarIfNeeded('USER_DISCONNECTED')
          return
        }

        console.info('[LiveAvatar] connect payload ready', {
          sessionId,
          roomId: creds.liveavatar_session_id,
          hasLiveKitUrl: Boolean(creds.livekit_url),
          hasToken: Boolean(creds.livekit_client_token),
          hasWsUrl: Boolean(creds.ws_url),
          willConnectLiveKit: true,
        })

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
          if (cancelledRef.current || statusRef.current === 'error') return
          console.warn('[LiveAvatar] Room disconnected', {
            sessionId,
            roomId: creds.liveavatar_session_id,
            stage: connectionStageRef.current,
          })
          if (connectionStageRef.current === 'livekit-connecting') {
            toast.error('No se pudo crear la room')
            updateStatus('error')
            return
          }
          if (statusRef.current !== 'audio-only') {
            toast.warning('LiveKit se desconectó. Pasando a audio-only.')
            updateStatus('audio-only')
          }
        })

        try {
          connectionStageRef.current = 'livekit-connecting'
          await room.connect(creds.livekit_url, creds.livekit_client_token)
        } catch (err) {
          console.warn('[LiveAvatar] LiveKit connect failed', {
            sessionId,
            roomId: creds.liveavatar_session_id,
            status: getApiErrorStatus(err),
            message: getErrorMessage(err),
          })
          await stopLiveAvatarIfNeeded('SERVER_ERROR')
          throw new AvatarSessionError('room', 'No se pudo crear la room')
        }
        console.info('[LiveAvatar] LiveKit connect succeeded', {
          sessionId,
          roomId: creds.liveavatar_session_id,
          connected: true,
        })
        if (cancelledRef.current) {
          room.disconnect()
          await stopLiveAvatarIfNeeded('USER_DISCONNECTED')
          return
        }

        connectionStageRef.current = 'ws-validating'
        const ws = new WebSocket(creds.ws_url)
        wsRef.current = ws

        ws.onerror = () => {
          console.warn('[LiveAvatar] WebSocket error', {
            sessionId,
            roomId: creds.liveavatar_session_id,
            stage: connectionStageRef.current,
            readyState: ws.readyState,
          })
        }
        ws.onclose = () => {
          if (cancelledRef.current || statusRef.current === 'error') return
          console.warn('[LiveAvatar] WebSocket closed', {
            sessionId,
            roomId: creds.liveavatar_session_id,
            stage: connectionStageRef.current,
            readyState: ws.readyState,
          })
          if (connectionStageRef.current === 'ws-validating') {
            toast.error('No se pudo validar la sesión de LiveAvatar')
            updateStatus('error')
            return
          }
          if (statusRef.current === 'connected' || statusRef.current === 'connecting') {
            toast.warning('WebSocket de LiveAvatar se cerró. Pasando a audio-only.')
            updateStatus('audio-only')
          }
        }

        try {
          await waitForWebSocketReady(ws)
        } catch (err) {
          console.warn('[LiveAvatar] WebSocket validate failed', {
            sessionId,
            roomId: creds.liveavatar_session_id,
            message: getErrorMessage(err),
          })
          await stopLiveAvatarIfNeeded('SERVER_ERROR')
          throw err
        }
        console.info('[LiveAvatar] WebSocket validate succeeded', {
          sessionId,
          roomId: creds.liveavatar_session_id,
          connected: true,
        })
        connectionStageRef.current = 'ready'

        if (cancelledRef.current) {
          room.disconnect()
          await stopLiveAvatarIfNeeded('USER_DISCONNECTED')
          ws.close()
          return
        }

        updateStatus('connected')
        } catch (connectErr) {
        if (cancelledRef.current) return
          if (connectErr instanceof AvatarSessionError) {
            if (connectErr.kind === 'capacity') {
              toast.warning('LiveAvatar está saturado o no pudo crear sesión. Pasando a audio-only.')
              updateStatus('audio-only')
              cleanup()
            } else if (connectErr.kind === 'room' || connectErr.kind === 'invalid-response') {
              void stopLiveAvatarIfNeeded('SERVER_ERROR')
              updateStatus('error')
              cleanup()
              toast.error('No se pudo crear la room')
            } else {
              cleanup()
              toast.error(connectErr.message)
              updateStatus('error')
            }
          } else if (isCapacityFailure(connectErr)) {
            toast.warning('LiveAvatar está saturado o no pudo crear sesión. Pasando a audio-only.')
            updateStatus('audio-only')
            cleanup()
          } else if (isAuthFailure(connectErr)) {
            cleanup()
            toast.error('Tu sesión expiró. Inicia sesión nuevamente.')
            updateStatus('error')
          } else {
            const status = getApiErrorStatus(connectErr)
            const message = getErrorMessage(connectErr)
            const detail = getApiErrorDetail(connectErr)
            console.warn('[LiveAvatar] backend connect failed', { sessionId, status, message, detail })
            if (status === 502) {
              updateStatus('error')
              cleanup()
              toast.error('No se pudo crear la room')
            } else if (status === 503 || isCapacityFailure(connectErr)) {
              updateStatus('audio-only')
              cleanup()
              toast.warning('LiveAvatar está saturado o no pudo crear sesión')
            } else if (status === 401) {
              cleanup()
              toast.error('Tu sesión expiró. Inicia sesión nuevamente.')
              updateStatus('error')
            } else if (isProviderInternalFailure(connectErr)) {
              updateStatus('error')
              cleanup()
              toast.error('LiveAvatar falló internamente al iniciar la sesión')
            } else if (status === 403) {
              updateStatus('error')
              cleanup()
              toast.error('LiveAvatar rechazó la sesión')
            } else if (status === 404) {
              updateStatus('error')
              cleanup()
              toast.error('La sesión local no existe o ya terminó')
            } else if (status && status >= 400) {
              updateStatus('error')
              cleanup()
              toast.error('LiveAvatar no pudo crear la sesión')
            } else {
              // Unknown error — use inner catch fallthrough
              updateStatus('error')
              cleanup()
              toast.error('Error inesperado al conectar con LiveAvatar')
            }
          }
        }

      const msgs = await getSessionHistory(sessionId)
      setHistory(msgs)

    } catch (err) {
      if (cancelledRef.current) return
      cleanup()
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg)
      updateStatus('error')
    } finally {
      isConnectingRef.current = false
      // Only reset stage if cleanup() wasn't already called (which sets 'stopping')
      if (connectionStageRef.current !== 'stopping') {
        connectionStageRef.current = 'idle'
      }
    }
  }

  function sleep(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms))
  }

  function isLiveAvatarCapacityError(message: string) {
    const lower = message.toLowerCase()
    return (
      message.includes('503') ||
      message.includes('4032') ||
      lower.includes('capacity') ||
      lower.includes('concurrency limit') ||
      lower.includes('busy right now')
    )
  }

  async function connectLiveAvatarWithRetry(sessionId: string) {
    let lastErr: unknown = null

    for (let attempt = 0; attempt < LIVEAVATAR_CONNECT_RETRIES; attempt++) {
      try {
        return await connectLiveAvatar(sessionId)
      } catch (err) {
        lastErr = err
        const msg = err instanceof Error ? err.message : String(err)
        if (!isLiveAvatarCapacityError(msg) || attempt === LIVEAVATAR_CONNECT_RETRIES - 1) {
          throw err
        }

        const delay = LIVEAVATAR_RETRY_DELAYS_MS[attempt] ?? LIVEAVATAR_RETRY_DELAYS_MS[LIVEAVATAR_RETRY_DELAYS_MS.length - 1] ?? 4000
        toast.warning(`LiveAvatar is at capacity. Retrying in ${Math.round(delay / 1000)}s...`)
        await sleep(delay)

        if (cancelledRef.current) {
          break
        }
      }
    }

    throw lastErr ?? new Error('LiveAvatar is at capacity right now')
  }

  function cleanup() {
    if (connectionStageRef.current === 'stopping') return  // idempotent
    connectionStageRef.current = 'stopping'
    console.info('[LiveAvatar] cleanup starting', { sessionId, hadRoom: Boolean(roomRef.current), hadWs: Boolean(wsRef.current), hadRecorder: Boolean(recorderRef.current), hadMediaStream: Boolean(mediaStreamRef.current) })

    roomRef.current?.disconnect()
    roomRef.current = null

    wsRef.current?.close()
    wsRef.current = null

    try {
      recorderRef.current?.stream.getTracks().forEach(track => track.stop())
    } catch { /* stream may already be stopped */ }
    recorderRef.current = null

    try {
      mediaStreamRef.current?.getTracks().forEach(track => track.stop())
    } catch { /* stream may already be stopped */ }
    mediaStreamRef.current = null
  }

  async function stopLiveAvatarIfNeeded(reason = 'USER_CLOSED') {
    const liveavatarSessionId = liveavatarSessionIdRef.current
    if (!liveavatarSessionId) return

    try {
      await stopLiveAvatarSession(sessionId, liveavatarSessionId, reason)
      liveavatarSessionIdRef.current = null
    } catch {
      // Best effort cleanup; ignore provider/network errors on unmount.
    }
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
      mediaStreamRef.current = stream
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      recorder.start()
      setRecording(true)

      if (status === 'connected') {
        wsRef.current?.send(JSON.stringify({ type: 'agent.start_listening' }))
      }
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
      const result = await speakInSession(sessionId, audioBlob)

      const msgs = await getSessionHistory(sessionId)
      setHistory(msgs)

      if (result.kind === 'text-only') {
        toast.warning('Audio was unavailable. The full answer is in the conversation.')
        return
      }

      if (status === 'connected' && wsRef.current?.readyState === WebSocket.OPEN) {
        await sendAudioToAvatar(result.buffer)
      } else {
        await playAudioLocally(result.buffer)
      }
    } catch (err) {
      if (isAuthFailure(err)) {
        toast.error('Tu sesión expiró. Inicia sesión nuevamente.')
      } else if (isCapacityFailure(err)) {
        toast.warning('LiveAvatar está saturado o no pudo crear sesión. Pasando a audio-only.')
      } else {
        toast.error(getErrorMessage(err))
      }
    } finally {
      setProcessing(false)
    }
  }

  async function handleEndSession() {
    cancelledRef.current = true
    isConnectingRef.current = false  // abort any in-flight connection attempt
    console.info('[LiveAvatar] handleEndSession', {
      sessionId,
      stage: connectionStageRef.current,
      hadLiveavatarSession: Boolean(liveavatarSessionIdRef.current),
    })
    await stopLiveAvatarIfNeeded('USER_CLOSED')
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

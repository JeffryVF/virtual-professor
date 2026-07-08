'use client'

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'
import { TalkingHead } from '@met4citizen/talkinghead'
import { LipsyncEn } from '@met4citizen/talkinghead/modules/lipsync-en.mjs'

const AVATAR_URL = '/avatars/mpfb.glb'
const AVATAR_BASELINE = {
  headRotateX: -0.01,
  eyeBlinkLeft: 0.05,
  eyeBlinkRight: 0.05,
}

const ALWAYS_MORPHS = [
  'eyeLookInLeft',
  'eyeLookOutLeft',
  'eyeLookInRight',
  'eyeLookOutRight',
  'eyesLookDown',
  'eyesLookUp',
  'eyeLookDownLeft',
  'eyeLookDownRight',
  'eyeLookUpLeft',
  'eyeLookUpRight',
  'eyeSquintLeft',
  'eyeSquintRight',
  'mouthOpen',
  'mouthSmile',
  'eyesClosed',
  'mouthDimpleLeft',
  'mouthDimpleRight',
  'mouthPressLeft',
  'mouthPressRight',
  'mouthStretchLeft',
  'mouthStretchRight',
  'mouthShrugLower',
  'mouthRollLower',
  'mouthRollUpper',
] as const

export interface TalkingHeadAvatarHandle {
  unlockAudio: () => Promise<void>
  playSpeech: (input: { audioBuffer: ArrayBuffer; text: string }) => Promise<void>
  stop: () => void
}

interface TalkingHeadAvatarProps {
  onUnavailable?: (reason?: string) => void
  onSpeakingChange?: (speaking: boolean) => void
}

function buildWordTimings(text: string, totalMs: number) {
  const words = text
    .trim()
    .split(/\s+/)
    .map((word) => word.trim())
    .filter(Boolean)

  if (words.length === 0) {
    return {
      words: [],
      wtimes: [],
      wdurations: [],
    }
  }

  const totalDuration = Math.max(300, Math.round(totalMs))
  const weights = words.map((word) => Math.max(1, word.replace(/[^\p{L}\p{N}]/gu, '').length))
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0)

  let elapsed = 0
  const wtimes: number[] = []
  const wdurations: number[] = []

  words.forEach((_, index) => {
    wtimes.push(elapsed)
    const remainingMs = totalDuration - elapsed
    const isLast = index === words.length - 1

    if (isLast) {
      wdurations.push(Math.max(120, remainingMs))
      elapsed = totalDuration
      return
    }

    const proportional = Math.round((totalDuration * weights[index]) / totalWeight)
    const duration = Math.max(120, proportional)
    wdurations.push(duration)
    elapsed += duration
  })

  return { words, wtimes, wdurations }
}

function ensureMorphs(head: TalkingHead) {
  const avatarMorphs = head.mtAvatar
  if (!avatarMorphs) return

  for (const name of ALWAYS_MORPHS) {
    if (!avatarMorphs[name]) {
      avatarMorphs[name] = {
        value: 0,
        applied: 0,
        system: null,
        systemd: null,
        newvalue: null,
        ref: null,
        base: null,
        fixed: null,
        realtime: null,
        v: 0,
        needsUpdate: false,
        ms: [],
        is: [],
        limit: null,
        onchange() {},
        min: 0,
        max: 1,
        maxv: 0.005,
        acc: 0.00001,
        baseline: 0,
      }
    }
  }

  head.mtRandomized = head.mtRandomized.filter((name) => Boolean(head.mtAvatar?.[name]))
}

const TalkingHeadAvatar = forwardRef<TalkingHeadAvatarHandle, TalkingHeadAvatarProps>(
  function TalkingHeadAvatar({ onUnavailable, onSpeakingChange }, ref) {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const headRef = useRef<TalkingHead | null>(null)
    const speakingTimerRef = useRef<number | null>(null)
    const readyRef = useRef(false)

    const [isReady, setIsReady] = useState(false)
    const [loadingMessage, setLoadingMessage] = useState('Loading 3D avatar...')
    const [subtitle, setSubtitle] = useState('')
    const [initError, setInitError] = useState<string | null>(null)

    const webglOk = useMemo(() => {
      try {
        const canvas = document.createElement('canvas')
        return !!(canvas.getContext('webgl') || canvas.getContext('webgl2'))
      } catch {
        return false
      }
    }, [])

    const clearSpeakingTimer = useCallback(() => {
      if (speakingTimerRef.current !== null) {
        window.clearTimeout(speakingTimerRef.current)
        speakingTimerRef.current = null
      }
    }, [])

    const stopSpeech = useCallback(() => {
      clearSpeakingTimer()
      setSubtitle('')
      onSpeakingChange?.(false)
      headRef.current?.stopSpeaking()
    }, [clearSpeakingTimer, onSpeakingChange])

    useImperativeHandle(
      ref,
      () => ({
        async unlockAudio() {
          const audioContext = headRef.current?.audioCtx
          if (audioContext && audioContext.state !== 'running') {
            await audioContext.resume()
          }
        },
        async playSpeech({ audioBuffer, text }) {
          const head = headRef.current
          if (!head || !readyRef.current) {
            throw new Error('Avatar is not ready')
          }

          if (head.audioCtx.state !== 'running') {
            await head.audioCtx.resume()
          }

          clearSpeakingTimer()
          setSubtitle(text)
          onSpeakingChange?.(true)

          const decodedAudio = await head.audioCtx.decodeAudioData(audioBuffer.slice(0))
          const totalMs = decodedAudio.duration * 1000
          const timing = buildWordTimings(text, totalMs)

          head.speakAudio(
            {
              audio: decodedAudio,
              words: timing.words,
              wtimes: timing.wtimes,
              wdurations: timing.wdurations,
            },
            { lipsyncLang: 'en' },
            (word) => setSubtitle(word || text)
          )

          await new Promise<void>((resolve) => {
            speakingTimerRef.current = window.setTimeout(() => {
              setSubtitle('')
              onSpeakingChange?.(false)
              speakingTimerRef.current = null
              resolve()
            }, Math.max(300, Math.ceil(totalMs + 250)))
          })
        },
        stop() {
          stopSpeech()
        },
      }),
      [clearSpeakingTimer, onSpeakingChange, stopSpeech]
    )

    useEffect(() => {
      if (!webglOk) {
        const reason = '3D rendering unavailable — audio-only mode active'
        setIsReady(false)
        setInitError(reason)
        onUnavailable?.(reason)
        return
      }

      let cancelled = false

      async function init() {
        const container = containerRef.current
        if (!container) return

        try {
          const head = new TalkingHead(container, {
            // Next/Webpack cannot resolve TalkingHead's runtime import('./lipsync-en.mjs').
            // Load the processor statically below and disable the package's dynamic loader.
            lipsyncLang: 'en',
            lipsyncModules: [],
            cameraView: 'head',
            cameraDistance: 0.3,
            cameraY: 0.25,
            cameraRotateEnable: false,
            cameraPanEnable: false,
            cameraZoomEnable: false,
            mixerGainSpeech: 3,
            lightAmbientColor: 0xffffff,
            lightAmbientIntensity: 1.5,
            lightDirectColor: 0x8899cc,
            lightDirectIntensity: 35,
            lightDirectPhi: 0.3,
            lightDirectTheta: 1.8,
            lightSpotColor: 0x4488ff,
            lightSpotIntensity: 8,
            lightSpotPhi: 0.4,
            lightSpotTheta: 3.5,
            lightSpotDispersion: 0.8,
          })

          head.opt.modelRoot = 'Armature'
          head.lipsync.en = new LipsyncEn()

          await head.showAvatar(
            {
              url: AVATAR_URL,
              body: 'F',
              baseline: AVATAR_BASELINE,
              avatarMood: 'neutral',
              lipsyncLang: 'en',
              avatarIdleEyeContact: 1,
              avatarSpeakingEyeContact: 1,
            },
            (event) => {
              if (!event.lengthComputable) return
              const percentage = Math.min(100, Math.round((event.loaded / event.total) * 100))
              setLoadingMessage(`Loading ${percentage}%`)
            }
          )

          if (cancelled) {
            head.dispose()
            return
          }

          ensureMorphs(head)
          headRef.current = head
          readyRef.current = true
          setIsReady(true)
          setInitError(null)
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Avatar failed to load'
          if (cancelled) return
          setIsReady(false)
          setInitError(message)
          onUnavailable?.(message)
        }
      }

      const handleVisibilityChange = () => {
        const head = headRef.current
        if (!head) return
        if (document.visibilityState === 'visible') {
          head.start()
        } else {
          head.stop()
        }
      }

      document.addEventListener('visibilitychange', handleVisibilityChange)
      void init()

      return () => {
        cancelled = true
        document.removeEventListener('visibilitychange', handleVisibilityChange)
        stopSpeech()
        readyRef.current = false
        setIsReady(false)
        headRef.current?.dispose()
        headRef.current = null
      }
    }, [onSpeakingChange, onUnavailable, stopSpeech, webglOk])

    if (initError) {
      return (
        <div className="flex h-full w-full items-center justify-center bg-[#1a1a2e] px-4 text-center text-xs text-muted-foreground">
          {initError}
        </div>
      )
    }

    return (
      <div className="relative h-full w-full bg-[#1a1a2e]">
        <div ref={containerRef} className="h-full w-full" />

        {!isReady ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/40 text-white">
            <div className="h-7 w-7 animate-spin rounded-full border-2 border-white/10 border-t-pink-500" />
            <span className="text-sm">{loadingMessage}</span>
          </div>
        ) : null}

        {subtitle ? (
          <div className="pointer-events-none absolute left-1/2 top-5 max-w-[80%] -translate-x-1/2 rounded-xl bg-black/60 px-4 py-2 text-center text-sm text-slate-200 backdrop-blur">
            {subtitle}
          </div>
        ) : null}
      </div>
    )
  }
)

export default TalkingHeadAvatar

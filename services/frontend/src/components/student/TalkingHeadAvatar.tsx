'use client'

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
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
  animateMouth: (durationMs: number) => void
  stop: () => void
}

interface TalkingHeadAvatarProps {
  onUnavailable?: (reason?: string) => void
  onSpeakingChange?: (speaking: boolean) => void
}

type MorphTargetState = {
  ms?: number[][]
  is?: number[]
  value?: number
  applied?: number
  fixed?: number | null
  system?: number | null
  newvalue?: number | null
  needsUpdate?: boolean
}

function applyMorphDirect(head: TalkingHead, morph: string, value: number) {
  const state = head.mtAvatar?.[morph] as MorphTargetState | undefined
  if (!state) return

  const clamped = Math.max(0, Math.min(1, value))
  state.value = clamped
  state.applied = clamped
  state.fixed = clamped
  state.system = null
  state.newvalue = null
  state.needsUpdate = false

  state.ms?.forEach((influences, index) => {
    const morphIndex = state.is?.[index]
    if (morphIndex !== undefined) {
      influences[morphIndex] = clamped
    }
  })
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
    const mouthAnimationRef = useRef<number | null>(null)
    const onUnavailableRef = useRef(onUnavailable)
    const onSpeakingChangeRef = useRef(onSpeakingChange)

    const [isReady, setIsReady] = useState(false)
    const [loadingMessage, setLoadingMessage] = useState('Loading 3D avatar...')
    const [subtitle, setSubtitle] = useState('')
    const [initError, setInitError] = useState<string | null>(null)

    useEffect(() => {
      onUnavailableRef.current = onUnavailable
      onSpeakingChangeRef.current = onSpeakingChange
    }, [onSpeakingChange, onUnavailable])

    const stopMouthAnimation = useCallback(() => {
      if (mouthAnimationRef.current !== null) {
        window.cancelAnimationFrame(mouthAnimationRef.current)
        mouthAnimationRef.current = null
      }

      const head = headRef.current
      if (!head) return

      for (const morph of [
        'viseme_aa',
        'viseme_E',
        'viseme_I',
        'viseme_O',
        'viseme_U',
        'viseme_PP',
        'jawOpen',
        'mouthOpen',
        'mouthFunnel',
        'mouthPucker',
      ]) {
        applyMorphDirect(head, morph, 0)
      }
    }, [])

    const animateMouth = useCallback((durationMs: number) => {
      const head = headRef.current
      if (!head || !readyRef.current) return

      stopMouthAnimation()
      const startedAt = performance.now()
      const safeDurationMs = Math.max(300, durationMs)
      const visemes = ['viseme_aa', 'viseme_E', 'viseme_O', 'viseme_U', 'viseme_I']

      const tick = (now: number) => {
        const elapsed = now - startedAt
        if (elapsed >= safeDurationMs) {
          stopMouthAnimation()
          return
        }

        const syllableIndex = Math.floor(elapsed / 145)
        const activeViseme = visemes[syllableIndex % visemes.length]
        const pulse = Math.pow((Math.sin(elapsed / 48) + 1) / 2, 0.75)
        const attack = Math.min(1, elapsed / 180)
        const release = Math.min(1, (safeDurationMs - elapsed) / 240)
        const envelope = Math.max(0, Math.min(attack, release))
        const value = Math.min(0.36, pulse * envelope * 0.42)

        for (const morph of visemes) {
          applyMorphDirect(head, morph, morph === activeViseme ? value : 0)
        }

        applyMorphDirect(head, 'jawOpen', value * 0.35)
        applyMorphDirect(head, 'mouthOpen', value * 0.28)
        applyMorphDirect(head, 'mouthFunnel', activeViseme === 'viseme_O' ? value * 0.2 : 0)
        applyMorphDirect(head, 'mouthPucker', activeViseme === 'viseme_U' ? value * 0.2 : 0)
        applyMorphDirect(head, 'viseme_PP', syllableIndex % 7 === 0 ? value * 0.3 : 0)

        mouthAnimationRef.current = window.requestAnimationFrame(tick)
      }

      mouthAnimationRef.current = window.requestAnimationFrame(tick)
    }, [stopMouthAnimation])

    const clearSpeakingTimer = useCallback(() => {
      if (speakingTimerRef.current !== null) {
        window.clearTimeout(speakingTimerRef.current)
        speakingTimerRef.current = null
      }
    }, [])

    const stopSpeech = useCallback(() => {
      clearSpeakingTimer()
      stopMouthAnimation()
      setSubtitle('')
      onSpeakingChangeRef.current?.(false)
      headRef.current?.stopSpeaking()
    }, [clearSpeakingTimer, stopMouthAnimation])

    useImperativeHandle(
      ref,
      () => ({
        async unlockAudio() {
          const audioContext = headRef.current?.audioCtx
          if (audioContext && audioContext.state !== 'running') {
            await audioContext.resume()
          }
        },
        animateMouth,
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
          onSpeakingChangeRef.current?.(true)

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
              onSpeakingChangeRef.current?.(false)
              speakingTimerRef.current = null
              resolve()
            }, Math.max(300, Math.ceil(totalMs + 250)))
          })
        },
        stop() {
          stopSpeech()
        },
      }),
      [animateMouth, clearSpeakingTimer, onSpeakingChange, stopSpeech]
    )

    useEffect(() => {
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
            // Audible playback is handled by AvatarSession's HTMLAudioElement.
            // TalkingHead receives the same WAV silently so it can drive visemes only.
            mixerGainSpeech: 0,
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

          head.opt.modelRoot = 'Human'
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
          console.error('[avatar] failed to initialize:', error)
          setIsReady(false)
          setInitError(message)
          onUnavailableRef.current?.(message)
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
    }, [stopSpeech])

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

declare module '@met4citizen/talkinghead' {
  export interface TalkingHeadOptions {
    lipsyncModules?: string[]
    lipsyncLang?: string
    cameraView?: 'full' | 'mid' | 'upper' | 'head'
    cameraDistance?: number
    cameraY?: number
    cameraRotateEnable?: boolean
    cameraPanEnable?: boolean
    cameraZoomEnable?: boolean
    mixerGainSpeech?: number
    lightAmbientColor?: number | string
    lightAmbientIntensity?: number
    lightDirectColor?: number | string
    lightDirectIntensity?: number
    lightDirectPhi?: number
    lightDirectTheta?: number
    lightSpotColor?: number | string
    lightSpotIntensity?: number
    lightSpotPhi?: number
    lightSpotTheta?: number
    lightSpotDispersion?: number
  }

  export interface TalkingHeadAvatarConfig {
    url: string
    body?: 'M' | 'F'
    baseline?: {
      headRotateX?: number
      eyeBlinkLeft?: number
      eyeBlinkRight?: number
    }
    avatarMood?: string
    lipsyncLang?: string
    avatarIdleEyeContact?: number
    avatarSpeakingEyeContact?: number
  }

  export interface TalkingHeadSpeechPayload {
    audio: AudioBuffer
    words: string[]
    wtimes: number[]
    wdurations: number[]
  }

  export class TalkingHead {
    constructor(nodeAvatar: HTMLElement, options?: TalkingHeadOptions)
    audioCtx: AudioContext
    opt: { modelRoot?: string }
    lipsync: Record<string, unknown>
    mtAvatar?: Record<string, unknown>
    mtRandomized: string[]
    setValue(morphTarget: string, value: number, transitionMs?: number | null): void
    showAvatar(
      avatar: TalkingHeadAvatarConfig,
      onprogress?: (event: ProgressEvent<EventTarget>) => void
    ): Promise<void>
    speakAudio(
      payload: TalkingHeadSpeechPayload,
      options?: { lipsyncLang?: string },
      onsubtitles?: (subtitle?: string) => void
    ): void
    start(): void
    stop(): void
    stopSpeaking(): void
    dispose(): void
  }
}

declare module '@met4citizen/talkinghead/modules/lipsync-en.mjs' {
  export class LipsyncEn {
    preProcessText(text: string): string
    wordsToVisemes(text: string): string[]
  }
}

import config from '../config/env'

export const VOICE_TYPES = {
  FEMALE: 'female',
  MALE: 'male',
} as const

export type VoiceType = typeof VOICE_TYPES[keyof typeof VOICE_TYPES]

export const VOICE_TYPE_NAMES: Record<VoiceType, string> = {
  [VOICE_TYPES.FEMALE]: '女声',
  [VOICE_TYPES.MALE]: '男声',
}

const VOICE_TYPE_STORAGE_KEY = 'tts_voice_type'
const TTS_BASE_URL = config.TTS_BASE_URL
const FIXED_SPEAKER = '中文女'

interface SpeechSynthesisCallbacks {
  onStart?: () => void
  onAudioData?: (data: ArrayBuffer) => void
  onComplete?: () => void
  onError?: (error: string) => void
}

interface TtsSpeakersResponse {
  speaker_count: number
  speakers: string[]
}

export class SpeechSynthesisService {
  private audioElement: HTMLAudioElement | null = null
  private isPlaying = false
  private currentVoiceType: VoiceType = VOICE_TYPES.FEMALE
  private callbacks: SpeechSynthesisCallbacks = {}
  private abortController: AbortController | null = null
  private currentObjectUrl: string | null = null
  private speakersCache: string[] | null = null
  private audioCache = new Map<string, ArrayBuffer>()

  constructor() {
    this.loadVoiceType()
  }

  private loadVoiceType(): void {
    try {
      const savedVoiceType = localStorage.getItem(VOICE_TYPE_STORAGE_KEY)
      if (savedVoiceType && Object.values(VOICE_TYPES).includes(savedVoiceType as VoiceType)) {
        this.currentVoiceType = savedVoiceType as VoiceType
      }
    } catch (error) {
      console.error('加载语音音色配置失败:', error)
    }
  }

  setVoiceType(voiceType: VoiceType): void {
    this.currentVoiceType = voiceType
    try {
      localStorage.setItem(VOICE_TYPE_STORAGE_KEY, voiceType)
    } catch (error) {
      console.error('保存语音音色配置失败:', error)
    }
  }

  getVoiceType(): VoiceType {
    return this.currentVoiceType
  }

  async checkServiceAvailability(): Promise<boolean> {
    try {
      const response = await fetch(`${TTS_BASE_URL}/api/tts/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      })
      return response.ok
    } catch (error) {
      console.error('TTS 服务健康检查失败:', error)
      return false
    }
  }

  private async fetchSpeakers(): Promise<string[]> {
    if (this.speakersCache) {
      return this.speakersCache
    }

    const response = await fetch(`${TTS_BASE_URL}/api/tts/speakers`, {
      method: 'GET',
      signal: AbortSignal.timeout(10000),
    })

    if (!response.ok) {
      throw new Error(`获取音色列表失败: HTTP ${response.status}`)
    }

    const data = (await response.json()) as TtsSpeakersResponse
    this.speakersCache = data.speakers || []
    return this.speakersCache
  }

  private pickSpeaker(speakers: string[]): string {
    if (!speakers.length) {
      throw new Error('TTS 服务未返回可用音色')
    }

    const preferred = speakers.find((speaker) => speaker === FIXED_SPEAKER)
    if (preferred) {
      return preferred
    }

    return speakers[0]
  }

  private buildCacheKey(text: string, speaker: string): string {
    return `${speaker}::${text.trim()}`
  }

  async startSynthesis(text: string, callbacks: SpeechSynthesisCallbacks): Promise<void> {
    if (!text || !text.trim()) {
      callbacks.onError?.('文本不能为空')
      return
    }

    this.stopPlayback()
    this.callbacks = callbacks
    this.isPlaying = true

    try {
      const speakers = await this.fetchSpeakers()
      const speaker = this.pickSpeaker(speakers)
      const cacheKey = this.buildCacheKey(text, speaker)
      const cachedAudio = this.audioCache.get(cacheKey)

      if (cachedAudio) {
        this.callbacks.onStart?.()
        this.callbacks.onAudioData?.(cachedAudio)
        await this.playAudioFromBuffer(cachedAudio)
        return
      }

      this.abortController = new AbortController()
      const formData = new FormData()
      formData.append('text', text.trim())
      formData.append('mode', 'sft')
      formData.append('speaker', speaker)
      formData.append('speed', '1.0')
      formData.append('save_audio', 'true')

      const response = await fetch(`${TTS_BASE_URL}/api/tts/synthesize`, {
        method: 'POST',
        body: formData,
        signal: this.abortController.signal,
      })

      if (!response.ok) {
        let detail = ''
        try {
          const errorData = await response.json()
          detail = errorData?.detail || ''
        } catch {
          detail = response.statusText
        }
        throw new Error(detail || `HTTP ${response.status}`)
      }

      const audioBuffer = await response.arrayBuffer()
      this.audioCache.set(cacheKey, audioBuffer)
      this.callbacks.onStart?.()
      this.callbacks.onAudioData?.(audioBuffer)
      await this.playAudioFromBuffer(audioBuffer)
    } catch (error: any) {
      if (error?.name !== 'AbortError') {
        console.error('TTS 合成失败:', error)
        this.callbacks.onError?.(error?.message || 'TTS 合成失败')
      }
      this.isPlaying = false
    }
  }

  private async playAudioFromBuffer(audioBuffer: ArrayBuffer): Promise<void> {
    if (this.currentObjectUrl) {
      URL.revokeObjectURL(this.currentObjectUrl)
    }

    const blob = new Blob([audioBuffer], { type: 'audio/wav' })
    this.currentObjectUrl = URL.createObjectURL(blob)

    return new Promise((resolve, reject) => {
      this.audioElement = new Audio(this.currentObjectUrl!)
      this.audioElement.preload = 'auto'

      this.audioElement.onended = () => {
        this.isPlaying = false
        this.callbacks.onComplete?.()
        this.cleanupPlayback()
        resolve()
      }

      this.audioElement.onerror = () => {
        const message = '音频播放失败'
        this.isPlaying = false
        this.callbacks.onError?.(message)
        this.cleanupPlayback()
        reject(new Error(message))
      }

      this.audioElement.play().catch((error) => {
        this.isPlaying = false
        this.callbacks.onError?.(error?.message || '音频播放失败')
        this.cleanupPlayback()
        reject(error)
      })
    })
  }

  private cleanupPlayback(): void {
    if (this.audioElement) {
      this.audioElement.pause()
      this.audioElement.src = ''
      this.audioElement.load()
      this.audioElement = null
    }

    if (this.currentObjectUrl) {
      URL.revokeObjectURL(this.currentObjectUrl)
      this.currentObjectUrl = null
    }
  }

  stopPlayback(): void {
    if (this.abortController) {
      this.abortController.abort()
      this.abortController = null
    }

    this.cleanupPlayback()
    this.isPlaying = false
  }

  isAudioPlaying(): boolean {
    return this.isPlaying
  }

  getPlaybackProgress(): number {
    if (!this.audioElement || !this.audioElement.duration) {
      return 0
    }
    return (this.audioElement.currentTime / this.audioElement.duration) * 100
  }

  getPlaybackTime(): { current: number; duration: number; remaining: number } {
    if (!this.audioElement) {
      return { current: 0, duration: 0, remaining: 0 }
    }

    const current = this.audioElement.currentTime || 0
    const duration = this.audioElement.duration || 0
    const remaining = duration - current
    return { current, duration, remaining }
  }

  dispose(): void {
    this.stopPlayback()
    this.audioCache.clear()
  }
}

export const speechSynthesisService = new SpeechSynthesisService()

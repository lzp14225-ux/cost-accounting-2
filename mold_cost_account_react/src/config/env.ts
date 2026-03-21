const readEnv = (value?: string, fallback?: string) => {
  const finalValue = value?.trim() || fallback?.trim() || ''
  return finalValue
}

export const config = {
  API_BASE_URL: readEnv(import.meta.env.VITE_API_BASE_URL),
  API_PREFIX: readEnv(import.meta.env.VITE_API_PREFIX, '/api/v1'),
  AUTH_BASE_URL: readEnv(import.meta.env.VITE_AUTH_BASE_URL, import.meta.env.VITE_API_BASE_URL),
  WS_BASE_URL: readEnv(import.meta.env.VITE_WS_BASE_URL, import.meta.env.VITE_API_BASE_URL),
  CONTINUE_API_BASE_URL: readEnv(import.meta.env.VITE_CONTINUE_API_BASE_URL, import.meta.env.VITE_API_BASE_URL),
  SPEECH_RECOGNITION_BASE_URL: readEnv(import.meta.env.VITE_SPEECH_RECOGNITION_BASE_URL),
  TTS_BASE_URL: readEnv(import.meta.env.VITE_TTS_BASE_URL),

  get API_URL() {
    return `${this.API_BASE_URL}${this.API_PREFIX}`
  },

  get CONTINUE_API_URL() {
    return `${this.CONTINUE_API_BASE_URL}${this.API_PREFIX}`
  },

  get WS_URL() {
    const wsBaseUrl = this.WS_BASE_URL.replace(/^https?:\/\//, '')
    const protocol = this.WS_BASE_URL.startsWith('https') ? 'wss' : 'ws'
    return `${protocol}://${wsBaseUrl}/ws`
  },

  get AUTH_URL() {
    return this.AUTH_BASE_URL
  },

  isDev: import.meta.env.DEV,
  isProd: import.meta.env.PROD,
}

export default config

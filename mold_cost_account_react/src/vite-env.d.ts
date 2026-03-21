/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_API_PREFIX: string
  readonly VITE_AUTH_BASE_URL: string
  readonly VITE_WS_BASE_URL: string
  readonly VITE_CONTINUE_API_BASE_URL: string
  readonly VITE_SPEECH_RECOGNITION_BASE_URL: string
  readonly VITE_TTS_BASE_URL: string
  readonly VITE_DEV_SERVER_PORT: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

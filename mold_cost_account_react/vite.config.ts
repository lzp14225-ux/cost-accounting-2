import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const apiProxyTarget = env.VITE_AUTH_BASE_URL || env.VITE_API_BASE_URL
  const wsProxyTarget = env.VITE_WS_BASE_URL || env.VITE_API_BASE_URL

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: Number(env.VITE_DEV_SERVER_PORT || 3000),
      proxy: {
        '/api': apiProxyTarget
          ? {
              target: apiProxyTarget,
              changeOrigin: true,
            }
          : undefined,
        '/ws': wsProxyTarget
          ? {
              target: wsProxyTarget.replace(/^http/, 'ws'),
              ws: true,
              changeOrigin: true,
            }
          : undefined,
      },
    },
  }
})

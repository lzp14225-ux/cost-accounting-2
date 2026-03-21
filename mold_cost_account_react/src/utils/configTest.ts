import config from '../config/env'

// 配置测试工具
export const testConfig = () => {
  // console.log('🔧 当前配置信息:')
  // console.log('API_BASE_URL:', config.API_BASE_URL)
  // console.log('API_PREFIX:', config.API_PREFIX)
  // console.log('API_URL:', config.API_URL)
  // console.log('WS_BASE_URL:', config.WS_BASE_URL)
  // console.log('WS_URL:', config.WS_URL)
  // console.log('AUTH_BASE_URL:', config.AUTH_BASE_URL)
  // console.log('isDev:', config.isDev)
  // console.log('isProd:', config.isProd)
  
  // 验证环境变量
  // console.log('🌍 环境变量:')
  // console.log('VITE_API_BASE_URL:', import.meta.env.VITE_API_BASE_URL)
  // console.log('VITE_API_PREFIX:', import.meta.env.VITE_API_PREFIX)
  // console.log('VITE_WS_BASE_URL:', import.meta.env.VITE_WS_BASE_URL)
  // console.log('VITE_AUTH_BASE_URL:', import.meta.env.VITE_AUTH_BASE_URL)
  
  // 验证实际API调用URL
  // console.log('🚀 实际API调用URL示例:')
  // console.log('会话列表:', `${config.API_URL}/chat/sessions`)
  // console.log('文件上传:', `${config.API_URL}/jobs/upload`)
  // console.log('WebSocket:', `${config.WS_URL}/{job_id}`)
}

// 在开发环境下自动输出配置信息
if (config.isDev) {
  setTimeout(() => {
    // console.log('🚀 开发环境配置信息:')
    testConfig()
  }, 1000)
}
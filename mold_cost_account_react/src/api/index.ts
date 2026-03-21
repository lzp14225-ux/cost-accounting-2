import config from '../config/env'

// API配置
export const API_CONFIG = {
  BASE_URL: config.AUTH_BASE_URL,
  TIMEOUT: 10000,
  ENDPOINTS: {
    // 认证相关
    LOGIN: '/api/login',
    LOGOUT: '/api/logout',
    USER_INFO: '/api/user/info',
    CHANGE_PASSWORD: '/api/user/change-password',
    
    // 任务相关
    JOBS: '/api/jobs',
    JOB_DETAIL: '/api/jobs/:id',
    CREATE_JOB: '/api/jobs',
    UPDATE_JOB: '/api/jobs/:id',
    DELETE_JOB: '/api/jobs/:id',
    
    // 文件上传
    UPLOAD_CAD: '/api/upload/cad',
    UPLOAD_FILE: '/api/upload/file',
    
    // 成本分析
    ANALYZE_COST: '/api/analyze/cost',
    GET_ANALYSIS_RESULT: '/api/analyze/result/:id',
  }
}

// 导出所有API模块
export * from './auth'

// 工具函数：替换URL中的参数
export const replaceUrlParams = (url: string, params: Record<string, string | number>): string => {
  let result = url
  Object.entries(params).forEach(([key, value]) => {
    result = result.replace(`:${key}`, String(value))
  })
  return result
}

// 工具函数：构建完整的API URL
export const buildApiUrl = (endpoint: string, params?: Record<string, string | number>): string => {
  const url = params ? replaceUrlParams(endpoint, params) : endpoint
  return `${API_CONFIG.BASE_URL}${url}`
}
import axios from 'axios'
import { message } from 'antd'
import config from '../config/env'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

// 创建axios实例
const api = axios.create({
  baseURL: config.API_URL,
  timeout: 10000000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 添加认证token
    const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    
    // 添加请求ID用于追踪
    config.headers['X-Request-ID'] = Date.now().toString() + Math.random().toString(36).substring(2, 9)
    
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    console.error('API Error:', error)
    
    if (error.response) {
      const { status, data } = error.response
      
      switch (status) {
        case 401:
          message.error('认证失败，请重新登录')
          // 清除token并跳转到登录页
          localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
          window.location.href = '/login'
          break
          
        case 403:
          message.error('权限不足')
          break
          
        case 404:
          message.error('请求的资源不存在')
          break
          
        case 413:
          message.error('文件过大，请选择较小的文件')
          break
          
        case 422:
          message.error(data.message || '请求参数错误')
          break
          
        case 429:
          message.error('请求过于频繁，请稍后再试')
          break
          
        case 500:
          message.error('服务器内部错误')
          break
          
        default:
          message.error(data.message || '请求失败')
      }
    } else if (error.request) {
      message.error('网络连接失败，请检查网络')
    } else {
      message.error('请求配置错误')
    }
    
    return Promise.reject(error)
  }
)

export default api
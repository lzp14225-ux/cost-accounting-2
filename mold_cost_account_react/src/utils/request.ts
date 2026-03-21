import { getValidToken, clearAuthData } from './auth'

// 请求配置接口
interface RequestConfig {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  headers?: Record<string, string>
  body?: any
  timeout?: number
}

// 默认配置
const DEFAULT_CONFIG: RequestConfig = {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 10000000,
}

// 请求拦截器
const requestInterceptor = (url: string, config: RequestConfig) => {
  // 添加认证token
  const token = getValidToken()
  if (token) {
    config.headers = {
      ...config.headers,
      'Authorization': `Bearer ${token}`,
    }
  } else {
    // console.log('没有有效的 token')
  }

  // 处理请求体
  if (config.body && config.headers?.['Content-Type'] === 'application/json') {
    config.body = JSON.stringify(config.body)
  }

  return { url, config }
}

// 响应拦截器
const responseInterceptor = async (response: Response): Promise<any> => {
  // 检查响应状态
  if (!response.ok) {
    // 处理 401 未授权错误
    if (response.status === 401) {
      clearAuthData()
      // 跳转到登录页面
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      throw new Error('登录已过期，请重新登录')
    }
    
    const errorText = await response.text()
    // console.log('错误响应内容:', errorText)
    let errorMessage = `请求失败: ${response.status}`
    
    try {
      const errorData = JSON.parse(errorText)
      errorMessage = errorData.message || errorMessage
    } catch {
      errorMessage = errorText || errorMessage
    }

    throw new Error(errorMessage)
  }

  // 解析响应数据
  const contentType = response.headers.get('content-type')
  if (contentType && contentType.includes('application/json')) {
    const data = await response.json()
    return data
  }
  
  const textData = await response.text()
  return textData
}

// 主请求函数
export const request = async <T = any>(
  url: string, 
  config: RequestConfig = {}
): Promise<T> => {
  // 合并配置
  const finalConfig = { ...DEFAULT_CONFIG, ...config }
  
  // 请求拦截
  const { url: finalUrl, config: interceptedConfig } = requestInterceptor(url, finalConfig)

  try {
    // 创建AbortController用于超时控制
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), finalConfig.timeout)

    // 发送请求
    const response = await fetch(finalUrl, {
      method: interceptedConfig.method,
      headers: interceptedConfig.headers,
      body: interceptedConfig.body,
      signal: controller.signal,
    })

    // 清除超时定时器
    clearTimeout(timeoutId)

    // 响应拦截
    const data = await responseInterceptor(response)
    
    return data
  } catch (error: any) {
    // 处理不同类型的错误
    if (error.name === 'AbortError') {
      throw new Error('请求超时，请检查网络连接')
    }
    
    if (error.message.includes('Failed to fetch')) {
      throw new Error('网络连接失败，请检查网络设置')
    }

    throw error
  }
}

// GET请求
export const get = <T = any>(url: string, config?: Omit<RequestConfig, 'method' | 'body'>) => {
  return request<T>(url, { ...config, method: 'GET' })
}

// POST请求
export const post = <T = any>(url: string, data?: any, config?: Omit<RequestConfig, 'method'>) => {
  return request<T>(url, { ...config, method: 'POST', body: data })
}

// PUT请求
export const put = <T = any>(url: string, data?: any, config?: Omit<RequestConfig, 'method'>) => {
  return request<T>(url, { ...config, method: 'PUT', body: data })
}

// DELETE请求
export const del = <T = any>(url: string, config?: Omit<RequestConfig, 'method' | 'body'>) => {
  return request<T>(url, { ...config, method: 'DELETE' })
}

// 文件上传
export const upload = <T = any>(url: string, file: File, config?: Omit<RequestConfig, 'method'>) => {
  const formData = new FormData()
  formData.append('file', file)
  
  return request<T>(url, {
    ...config,
    method: 'POST',
    body: formData,
    headers: {
      // 不设置Content-Type，让浏览器自动设置multipart/form-data
      ...(config?.headers || {}),
    },
  })
}

// 多文件上传 - 专门用于 CAD 文件上传
export const uploadCADFiles = <T = any>(url: string, files: File[], config?: Omit<RequestConfig, 'method'>) => {
  const formData = new FormData()
  
  // 根据文件类型添加到不同的字段
  files.forEach(file => {
    const fileName = file.name.toLowerCase()
    if (fileName.endsWith('.dwg')) {
      formData.append('dwg_file', file)
    } else if (fileName.endsWith('.prt')) {
      formData.append('prt_file', file)
    } else {
      formData.append('file', file)
    }
  })
  
  // // 打印 FormData 内容
  // for (let [key, value] of formData.entries()) {
  //   console.log(key, value)
  // }
  
  return request<T>(url, {
    ...config,
    method: 'POST',
    body: formData,
    headers: {
      // 不设置Content-Type，让浏览器自动设置multipart/form-data
      ...(config?.headers || {}),
    },
  })
}

export default request
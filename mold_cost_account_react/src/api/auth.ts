import { post } from '../utils/request'
import config from '../config/env'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

// 登录请求参数接口
export interface LoginParams {
  username: string
  password: string
}

// 用户信息接口
export interface UserInfo {
  user_id: string
  username: string
  real_name: string
  email: string
  role: string
  department: string | null
  is_active: boolean
  created_at: string
  last_login_at: string
}

// 登录响应接口
export interface LoginResponse {
  success: boolean
  message: string
  user_info: UserInfo
  token?: string
}

// 登录接口
export const loginApi = async (params: LoginParams): Promise<LoginResponse> => {
  try {
    const response = await post<LoginResponse>(`${config.AUTH_URL}/api/login`, params)
    
    // 如果登录成功，保存token（如果有的话）
    if (response.success && response.token) {
      localStorage.setItem(AUTH_STORAGE_KEYS.TOKEN, response.token)
    }
    
    return response
  } catch (error: any) {
    // 统一错误处理
    throw new Error(error.message || '登录失败，请重试')
  }
}

// 退出登录接口
export const logoutApi = async (): Promise<void> => {
  try {
    // 如果后端有退出登录接口，可以在这里调用
    // await post(`${config.AUTH_URL}/api/logout`)
    
    // 清除本地存储的认证信息
    localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
    localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
    localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
  } catch (error) {
    // 即使退出登录接口失败，也要清除本地存储
    localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
    localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
    localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
    throw error
  }
}

// 获取用户信息接口
export const getUserInfoApi = async (): Promise<UserInfo> => {
  try {
    const response = await post<{ success: boolean; user_info: UserInfo }>(`${config.AUTH_URL}/api/user/info`)
    
    if (response.success) {
      return response.user_info
    } else {
      throw new Error('获取用户信息失败')
    }
  } catch (error: any) {
    throw new Error(error.message || '获取用户信息失败')
  }
}

// 修改密码接口
export const changePasswordApi = async (newPassword: string): Promise<{ success: boolean; message: string }> => {
  try {
    const response = await post<{ success: boolean; message: string }>(`${config.AUTH_URL}/api/change-password`, {
      new_password: newPassword,
    })
    
    return response
  } catch (error: any) {
    throw new Error(error.message || '修改密码失败')
  }
}
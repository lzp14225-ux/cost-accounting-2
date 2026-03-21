import { AUTH_STORAGE_KEYS } from '../constants/auth'

// JWT token 工具函数

// 解码 JWT token（不验证签名，仅用于获取 payload）
export const decodeJWT = (token: string) => {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) {
      throw new Error('Invalid JWT format')
    }
    
    const payload = parts[1]
    const decoded = JSON.parse(atob(payload))
    return decoded
  } catch (error) {
    console.error('JWT decode error:', error)
    return null
  }
}

// 检查 token 是否过期
export const isTokenExpired = (token: string): boolean => {
  try {
    const decoded = decodeJWT(token)
    if (!decoded || !decoded.exp) {
      return true
    }
    
    const currentTime = Math.floor(Date.now() / 1000)
    return decoded.exp < currentTime
  } catch (error) {
    console.error('Token expiration check error:', error)
    return true
  }
}

// 获取当前有效的 token
export const getValidToken = (): string | null => {
  const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
  if (!token) {
    return null
  }
  
  if (isTokenExpired(token)) {
    // Token 已过期，清除相关数据
    localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
    localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
    localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
    return null
  }
  
  return token
}

// 从 token 中获取用户信息
export const getUserFromToken = (token: string) => {
  const decoded = decodeJWT(token)
  if (!decoded) {
    return null
  }
  
  return {
    userId: decoded.user_id,
    username: decoded.sub,
    role: decoded.role,
    email: decoded.email,
    realName: decoded.real_name,
  }
}

// 清除认证信息
export const clearAuthData = () => {
  localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
  localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
  localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
}
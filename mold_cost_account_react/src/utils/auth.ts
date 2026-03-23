import { AUTH_STORAGE_KEYS } from '../constants/auth'

type JWTPayload = {
  exp?: number
  iat?: number
  user_id?: string
  sub?: string
  role?: string
  email?: string
  real_name?: string
}

export const decodeJWT = (token: string): JWTPayload | null => {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) {
      throw new Error('Invalid JWT format')
    }

    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
    const decoded = decodeURIComponent(
      atob(padded)
        .split('')
        .map((char) => `%${char.charCodeAt(0).toString(16).padStart(2, '0')}`)
        .join('')
    )
    return JSON.parse(decoded)
  } catch (error) {
    console.error('JWT decode error:', error)
    return null
  }
}

export const isTokenExpired = (token: string): boolean => {
  try {
    const decoded = decodeJWT(token)
    if (!decoded?.exp) {
      return true
    }

    const currentTime = Math.floor(Date.now() / 1000)
    return decoded.exp < currentTime
  } catch (error) {
    console.error('Token expiration check error:', error)
    return true
  }
}

export const isTokenIssuedInFuture = (token: string, leewaySeconds: number = 60): boolean => {
  try {
    const decoded = decodeJWT(token)
    if (!decoded?.iat) {
      return false
    }

    const currentTime = Math.floor(Date.now() / 1000)
    return decoded.iat > currentTime + leewaySeconds
  } catch (error) {
    console.error('Token iat check error:', error)
    return true
  }
}

export const clearAuthData = () => {
  localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
  localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
  localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
}

export const getValidToken = (): string | null => {
  const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
  if (!token) {
    return null
  }

  if (isTokenExpired(token) || isTokenIssuedInFuture(token)) {
    clearAuthData()
    return null
  }

  return token
}

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

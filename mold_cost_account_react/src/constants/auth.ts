// 认证相关常量
export const AUTH_STORAGE_KEYS = {
  TOKEN: 'token',
  IS_LOGGED_IN: 'isLoggedIn',
  USER_INFO: 'userInfo',
  REMEMBERED_USERNAME: 'rememberedUsername',
  REMEMBERED_PASSWORD: 'rememberedPassword',
} as const

// 认证状态枚举
export enum AuthStatus {
  AUTHENTICATED = 'authenticated',
  UNAUTHENTICATED = 'unauthenticated',
  LOADING = 'loading',
  TOKEN_EXPIRED = 'token_expired',
}

// 用户角色枚举
export enum UserRole {
  ADMIN = 'admin',
  USER = 'user',
  MANAGER = 'manager',
}
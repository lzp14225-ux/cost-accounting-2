import React, { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { getValidToken, clearAuthData } from '../utils/auth'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

interface ProtectedRouteProps {
  children: React.ReactNode
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
  const [isLoading, setIsLoading] = useState(true)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const location = useLocation()

  useEffect(() => {
    // 检查用户是否已登录
    const checkAuth = () => {
      const isLoggedIn = localStorage.getItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN) === 'true'
      const userInfo = localStorage.getItem(AUTH_STORAGE_KEYS.USER_INFO)
      const token = getValidToken() // 使用新的工具函数，会自动检查 token 是否过期
      
      console.log('认证检查:', { isLoggedIn, hasUserInfo: !!userInfo, hasToken: !!token })
      
      // 如果有 userInfo 但没有 token，清除所有认证数据
      if (userInfo && !token) {
        console.log('发现 userInfo 但没有有效 token，清除认证数据')
        clearAuthData()
        setIsAuthenticated(false)
        setIsLoading(false)
        return
      }
      
      // 如果有 token 但没有 userInfo，也清除认证数据
      if (token && !userInfo) {
        console.log('发现 token 但没有 userInfo，清除认证数据')
        clearAuthData()
        setIsAuthenticated(false)
        setIsLoading(false)
        return
      }
      
      // 检查登录状态、用户信息和有效的 token 都存在
      if (isLoggedIn && userInfo && token) {
        try {
          const user = JSON.parse(userInfo)
          if (user.userId) {
            console.log('认证成功，用户:', user.username)
            setIsAuthenticated(true)
          } else {
            console.log('用户信息格式错误，清除认证数据')
            clearAuthData()
            setIsAuthenticated(false)
          }
        } catch (error) {
          console.error('解析用户信息失败:', error)
          clearAuthData()
          setIsAuthenticated(false)
        }
      } else {
        console.log('认证信息不完整，需要重新登录')
        setIsAuthenticated(false)
      }
      
      setIsLoading(false)
    }

    checkAuth()
  }, [])

  if (isLoading) {
    return (
      <div style={{
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f5f5f5'
      }}>
        <Spin size="large" tip="正在验证登录状态..." />
      </div>
    )
  }

  if (!isAuthenticated) {
    // 保存当前路径，登录后可以重定向回来
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

export default ProtectedRoute
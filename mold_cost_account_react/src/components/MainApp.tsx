import React, { useEffect, useState } from 'react'
import { Layout, theme, Drawer } from 'antd'
import Sidebar from './Sidebar'
import ChatInterface from './ChatInterface'
import JobList from './JobList'
import Settings from './Settings'
import PriceManagement from './PriceManagement'
import ProcessManagement from './ProcessManagement'
import HistorySessions from './HistorySessions'
import { useAppStore } from '../store/useAppStore'
import { mockJobs, simulateJobProgress } from '../utils/mockData'
import { checkDuplicateIds } from '../utils/testUtils'
import { getValidToken } from '../utils/auth'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

const { Content } = Layout

// 同步检查登录状态的函数
const checkAuthSync = () => {
  const loggedIn = localStorage.getItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN) === 'true'
  const userInfo = localStorage.getItem(AUTH_STORAGE_KEYS.USER_INFO)
  const validToken = getValidToken()
  return loggedIn && !!userInfo && !!validToken
}

const MainApp: React.FC = () => {
  const { 
    currentView, 
    addJob, 
    updateJob, 
    jobs, 
    initialized, 
    setInitialized,
    isMobile,
    mobileDrawerVisible,
    setIsMobile,
    setMobileDrawerVisible,
    setCurrentView,
    themeMode,
  } = useAppStore()
  const { token } = theme.useToken()
  // 使用同步方式初始化登录状态，避免闪动
  const [isLoggedIn, setIsLoggedIn] = useState(() => checkAuthSync())
  const [authChecking, setAuthChecking] = useState(false) // 改为false，因为已经同步检查过了

  // 应用主题到 document.documentElement
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', themeMode)
  }, [themeMode])

  // 检查登录状态
  useEffect(() => {
    const checkAuth = () => {
      const newAuthState = checkAuthSync()
      setIsLoggedIn(newAuthState)
      
      // 如果检测到未登录状态，确保清理可能残留的数据
      if (!newAuthState) {
        const hasLoggedInFlag = localStorage.getItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN) === 'true'
        const hasUserInfo = !!localStorage.getItem(AUTH_STORAGE_KEYS.USER_INFO)
        const hasValidToken = !!getValidToken()
        
        // 如果有登录标记但 token 无效，清理数据
        if ((hasLoggedInFlag || hasUserInfo) && !hasValidToken) {
          localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
          localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
          localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
        }
      }
    }

    // 初始检查
    checkAuth()

    // 监听 storage 事件，当其他标签页登录/登出时同步状态
    const handleStorageChange = () => {
      checkAuth()
    }

    window.addEventListener('storage', handleStorageChange)
    
    // 自定义事件，用于同一标签页内的登录状态变化
    window.addEventListener('loginStateChange', handleStorageChange)
    
    // 定期检查 token 有效性（每30秒检查一次）
    const intervalId = setInterval(() => {
      checkAuth()
    }, 30000)

    return () => {
      window.removeEventListener('storage', handleStorageChange)
      window.removeEventListener('loginStateChange', handleStorageChange)
      clearInterval(intervalId)
    }
  }, [])

  // 未登录时强制显示聊天界面
  useEffect(() => {
    if (!isLoggedIn && currentView !== 'chat') {
      setCurrentView('chat')
    }
  }, [isLoggedIn, currentView, setCurrentView])

  // 监听窗口大小变化
  useEffect(() => {
    const handleResize = () => {
      const isMobileSize = window.innerWidth < 960
      setIsMobile(isMobileSize)
      
      // 如果从移动端切换到桌面端，关闭抽屉
      if (!isMobileSize && mobileDrawerVisible) {
        setMobileDrawerVisible(false)
      }
    }

    // 初始检查
    handleResize()

    // 添加监听器
    window.addEventListener('resize', handleResize)
    
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [setIsMobile, mobileDrawerVisible, setMobileDrawerVisible])

  // // 初始化模拟数据
  // useEffect(() => {
  //   // 只在首次加载且未初始化时执行
  //   if (!initialized && jobs.length === 0) {
  //     console.log('初始化模拟数据...')
      
  //     // 检查模拟数据中是否有重复ID
  //     const duplicateIds = checkDuplicateIds(mockJobs)
  //     if (duplicateIds.length > 0) {
  //       console.error('模拟数据中发现重复ID:', duplicateIds)
  //     }
      
  //     // 添加模拟任务
  //     mockJobs.forEach(job => {
  //       addJob(job)
  //     })

  //     // 标记为已初始化
  //     setInitialized(true)

  //     // 模拟正在处理的任务进度更新
  //     const processingJob = mockJobs.find(job => job.status === 'processing')
  //     if (processingJob) {
  //       setTimeout(() => {
  //         simulateJobProgress(processingJob.id, (progress) => {
  //           updateJob(processingJob.id, {
  //             stage: progress.stage,
  //             progress: progress.progress,
  //             status: progress.status as any,
  //           })
  //         })
  //       }, 1000)
  //     }
  //   }
  // }, [initialized, jobs.length, addJob, updateJob, setInitialized])

  // 开发模式下检查jobs数组中的重复ID
  useEffect(() => {
    if (process.env.NODE_ENV === 'development' && jobs.length > 0) {
      const duplicateIds = checkDuplicateIds(jobs)
      if (duplicateIds.length > 0) {
        console.error('Jobs数组中发现重复ID:', duplicateIds)
      }
    }
  }, [jobs])

  const renderContent = () => {
    switch (currentView) {
      case 'chat':
        return <ChatInterface />
      case 'price':
        return <PriceManagement />
      case 'process':
        return <ProcessManagement />
      case 'jobs':
        return <JobList />
      case 'history':
        return <HistorySessions />
      case 'settings':
        return <Settings />
      default:
        return <ChatInterface />
    }
  }

  return (
    <Layout 
      style={{ 
        height: '100vh',
        background: token.colorBgContainer,
        flexDirection: 'row'
      }}
    >
      {/* 只有登录后才显示侧边栏 */}
      {isLoggedIn && (
        <>
          {/* 桌面端侧边栏 */}
          {!isMobile && <Sidebar />}
          
          {/* 移动端抽屉侧边栏 */}
          {isMobile && (
            <Drawer
              title={null}
              placement="left"
              closable={false}
              onClose={() => setMobileDrawerVisible(false)}
              open={mobileDrawerVisible}
              width={280}
              styles={{
                body: { 
                  padding: 0,
                  height: '100vh',
                  display: 'flex',
                  flexDirection: 'column',
                  overflow: 'hidden',
                },
                header: { display: 'none' },
                mask: {
                  backgroundColor: 'rgba(0, 0, 0, 0.45)',
                },
              }}
              style={{
                zIndex: 1001,
              }}
            >
              <Sidebar />
            </Drawer>
          )}
        </>
      )}
      
      <Layout>
        <Content 
          style={{ 
            overflow: 'hidden',
            background: token.colorBgLayout,
          }}
        >
          {renderContent()}
        </Content>
      </Layout>
    </Layout>
  )
}

export default MainApp
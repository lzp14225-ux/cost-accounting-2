import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { 
  Layout, 
  Button, 
  Tooltip, 
  Typography,
  Space,
  Flex,
  Dropdown,
  Input,
  Modal,
  message,
  theme,
  Spin,
} from 'antd'
import {
  DollarOutlined,
  ToolOutlined,
  PlusOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  HistoryOutlined,
  MoreOutlined,
  EditOutlined,
  DeleteOutlined,
  LoadingOutlined,
} from '@ant-design/icons'
import { useAppStore } from '@/store/useAppStore'
import { sessionService } from '@/services/sessionService'
import { websocketService } from '@/services/websocketService'
import { chatService } from '@/services/chatService'
import UserInfoSection from './UserInfoSection'
import logoImage from '@/assets/images/logo.png'

const { Sider } = Layout
const { Text, Title } = Typography

const Sidebar: React.FC = () => {
  const { 
    currentView, 
    sidebarCollapsed, 
    sessions,
    sessionsLoading,
    sessionsTotal,
    hasMoreSessions,
    isMobile,
    currentJobId, // 添加 currentJobId 用于判断选中状态
    themeMode, // 新增：获取主题模式
    setCurrentView, 
    setSidebarCollapsed,
    setMobileDrawerVisible,
    clearMessages,
    resetUploadState,  // 新增：重置上传状态
    setCurrentJobId,
    setIsTyping,  // 新增：清除打字状态
    setIsCalculating,  // 新增：设置核算状态
    setIsRefreshing,  // 新增：设置刷新状态
    setIsReprocessing,  // 新增：设置重新处理状态
    setHistoryLoadError,  // 新增：清除历史加载错误
    setIsLoadingHistory,  // 新增：清除加载状态
    cancelLoadingHistory,  // 新增：取消正在进行的历史加载
    setSessions,
    addSessions,
    setSessionsLoading,
    deleteSession: deleteSessionFromStore,
    updateSession,
  } = useAppStore()

  const { token } = theme.useToken()
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null)
  const [renameModalVisible, setRenameModalVisible] = useState(false)
  const [renameInputValue, setRenameInputValue] = useState('')
  const [renamingLoading, setRenamingLoading] = useState(false) // 新增：重命名加载状态
  const [isHoveringLogo, setIsHoveringLogo] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [sessionsError, setSessionsError] = useState(false) // 添加错误状态
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const hasLoadedRef = useRef(false) // 添加标记，防止重复加载
  const isClickingRef = useRef(false) // 防止快速连续点击
  const clickTimeoutRef = useRef<NodeJS.Timeout | null>(null) // 点击防抖计时器
  const switchingJobIdRef = useRef<string | null>(null) // 记录正在切换的jobId，防止重复切换

  // 获取用户角色
  const getUserRole = (): string => {
    try {
      const userInfoStr = localStorage.getItem('userInfo')
      if (userInfoStr) {
        const userInfo = JSON.parse(userInfoStr)
        return userInfo.role || ''
      }
    } catch (error) {
      console.error('获取用户角色失败:', error)
    }
    return ''
  }

  const isAdmin = getUserRole() === 'admin'

  // // 监控 sessions 变化
  // useEffect(() => {
  //   console.log('📊 Sidebar - sessions 已更新:', sessions.length, sessions)
  // }, [sessions])

  // 加载会话列表
  const loadSessions = useCallback(async (refresh = false) => {
    try {
      setSessionsLoading(true)
      setSessionsError(false) // 清除错误状态
      const response = await sessionService.getSessions({ limit: 5 })
      setSessions(response.sessions, response.total_count, 0)
    } catch (error: any) {
      console.error('加载会话列表失败:', error)
      setSessionsError(true) // 设置错误状态
      if (error.message?.includes('Token') || error.message?.includes('认证')) {
        // Token失效，不显示错误消息，让用户重新登录
        return
      }
      // 不显示全局错误消息，在UI中显示重新加载按钮
    } finally {
      setSessionsLoading(false)
    }
  }, [setSessions, setSessionsLoading])

  // 加载更多会话
  const loadMoreSessions = useCallback(async () => {
    if (loadingMore || !hasMoreSessions) return
    
    try {
      setLoadingMore(true)
      const offset = sessions.length
      const response = await sessionService.getMoreSessions(offset, 50)
      addSessions(response.sessions, response.total_count, offset)
    } catch (error: any) {
      console.error('加载更多会话失败:', error)
      message.error('加载更多会话失败')
    } finally {
      setLoadingMore(false)
    }
  }, [sessions.length, hasMoreSessions, loadingMore, addSessions])

  // 监听滚动事件，实现无限滚动
  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100
    
    if (isNearBottom && hasMoreSessions && !loadingMore) {
      loadMoreSessions()
    }
  }, [hasMoreSessions, loadingMore, loadMoreSessions])

  // 组件挂载时加载会话列表（只加载一次）
  useEffect(() => {
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true
      loadSessions()
    }
    
    // 监听刷新会话列表事件
    const handleRefreshSessions = () => {
      loadSessions(true)
    }
    
    window.addEventListener('refreshSessions', handleRefreshSessions)
    
    return () => {
      window.removeEventListener('refreshSessions', handleRefreshSessions)
      // 清理防抖计时器
      if (clickTimeoutRef.current) {
        clearTimeout(clickTimeoutRef.current)
      }
    }
  }, []) // 移除 loadSessions 依赖，只在组件挂载时执行一次

  const menuItems: Array<{
    key: string
    icon: React.ReactNode
    label: string
    badge?: number
  }> = [
    {
      key: 'price',
      icon: <DollarOutlined />,
      label: '价格管理',
    },
    {
      key: 'process',
      icon: <ToolOutlined />,
      label: '工艺管理',
    },
  ]

  const handleNewChat = () => {
    // 断开当前 WebSocket 连接
    if (websocketService.isConnected()) {
      console.log('🔌 切换到新对话，断开当前 WebSocket 连接')
      websocketService.disconnect()
    }
    
    // 取消正在进行的历史加载（这会清除 loadingSessionId，使旧请求被忽略）
    cancelLoadingHistory()
    
    // 清除所有状态
    clearMessages()
    setCurrentJobId(undefined)
    resetUploadState()  // 重置上传状态
    setIsTyping(false)  // 清除打字状态
    setIsCalculating(false)  // 清除核算状态
    setIsRefreshing(false)  // 清除刷新状态
    setIsReprocessing(false)  // 清除重新处理状态
    setCurrentView('chat')
    
    // 如果是移动端，关闭抽屉
    if (isMobile) {
      setMobileDrawerVisible(false)
    }
  }

  // 处理会话重命名 - 打开弹窗
  const handleRenameSession = (sessionId: string, currentTitle: string) => {
    setRenamingSessionId(sessionId)
    setRenameInputValue(currentTitle)
    setRenameModalVisible(true)
  }

  // 保存重命名
  const handleSaveRename = async () => {
    if (!renameInputValue.trim() || !renamingSessionId) {
      return
    }

    try {
      setRenamingLoading(true) // 开始加载
      
      // 找到对应的 session 获取 job_id
      const session = sessions.find(s => s.session_id === renamingSessionId)
      if (!session) {
        message.error('找不到对应的会话')
        setRenameModalVisible(false)
        setRenamingSessionId(null)
        setRenameInputValue('')
        setRenamingLoading(false)
        return
      }
      
      await sessionService.renameSession(session.job_id, renameInputValue.trim())
      updateSession(renamingSessionId, { name: renameInputValue.trim() })
      message.success('会话重命名成功')
      setRenameModalVisible(false)
      setRenamingSessionId(null)
      setRenameInputValue('')
    } catch (error) {
      console.error('重命名失败:', error)
      message.error('重命名失败')
    } finally {
      setRenamingLoading(false) // 结束加载
    }
  }

  // 取消重命名
  const handleCancelRename = () => {
    setRenameModalVisible(false)
    setRenamingSessionId(null)
    setRenameInputValue('')
  }

  // 处理会话删除
  const handleDeleteSession = (sessionId: string, sessionTitle: string) => {
    Modal.confirm({
      title: '删除会话',
      content: `确定要删除会话"${sessionTitle}"吗？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          // 找到对应的 session 获取 job_id
          const session = sessions.find(s => s.session_id === sessionId)
          
          if (!session) {
            message.error('找不到对应的会话')
            return
          }
          
          // 检查是否删除的是当前正在查看的会话
          const isCurrentSession = currentJobId === session.job_id
          
          await sessionService.deleteSession(session.job_id)
          
          // // 删除成功后重新加载会话列表，而不是只从本地状态删除
          // await loadSessions(true)
          // 删除成功后从本地状态删除，避免重新加载导致历史会话区域列表重置
          deleteSessionFromStore(sessionId)
          
          // 等待状态更新完成
          await new Promise(resolve => setTimeout(resolve, 50))
          
          // 如果删除后会话数量少于5个，且还有更多会话，则加载更多
          const currentSessionsCount = sessions.length - 1 // 删除了一个
          if (currentSessionsCount < 5 && hasMoreSessions) {
            try {
              await loadSessions(true)
            } catch (error) {
              console.error('❌ 加载更多会话失败:', error)
            }
          }
          
          // 如果删除的是当前会话，返回到新建对话
          if (isCurrentSession) {
            setCurrentView('chat')
            setCurrentJobId(undefined)
            clearMessages()
            resetUploadState() // 清除上传CAD文件的状态
            message.success('会话已删除，已返回到新建对话')
          } else {
            message.success('会话删除成功')
          }
        } catch (error) {
          console.error('删除失败:', error)
          message.error('删除失败')
        }
      },
    })
  }

  // 获取会话标题
  const getSessionTitle = (session: any) => {
    return session.name || session.job_id || `会话 ${session.session_id.slice(0, 8)}`
  }

  // 显示的会话列表（前5个）- 使用 useMemo 确保响应式更新
  const displaySessions = useMemo(() => {
    const result = sessions.slice(0, 5)
    return result
  }, [sessions])

  const sidebarContent = (
    <div style={{ 
      height: '100%', 
      display: 'flex',
      flexDirection: 'column'
    }}>
      {/* 头部固定区域 - Logo */}
      <div style={{ 
        padding: (isMobile ? false : sidebarCollapsed) ? '15px 10px 9px' : '15px 20px 9px',
        flexShrink: 0, // 固定不收缩
      }}>
        <Flex justify="space-between" align="center">
          {sidebarCollapsed ? (
            // 折叠状态：显示 logo，悬浮时显示展开图标
            <Tooltip title="展开侧边栏" placement="right">
              <div
                style={{
                  width: '100%',
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  padding: '8px 10px',
                  height: 40,
                  borderRadius: token.borderRadius,
                  background: isHoveringLogo ? (themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary) : 'transparent',
                  border: themeMode === 'dark' ? 'none' : `1px solid ${isHoveringLogo ? token.colorBorderSecondary : 'transparent'}`,
                }}
                onMouseEnter={() => setIsHoveringLogo(true)}
                onMouseLeave={() => setIsHoveringLogo(false)}
                onClick={() => setSidebarCollapsed(false)}
              >
                {isHoveringLogo ? (
                  <MenuUnfoldOutlined 
                    style={{ 
                      fontSize: 16,
                      color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText,
                    }} 
                  />
                ) : (
                  <img 
                    src={logoImage} 
                    alt="Logo"
                    style={{ 
                      height: 32,
                      width: 'auto',
                    }} 
                  />
                )}
              </div>
            </Tooltip>
          ) : (
            // 展开状态：显示 logo 和折叠按钮
            <>
              <Flex align="center" gap={8}>
                <img 
                  src={logoImage} 
                  alt="Logo"
                  style={{ 
                    height: 32,
                    width: 'auto',
                  }} 
                />
              </Flex>
              {/* 只在桌面端显示折叠按钮 */}
              {!isMobile && (
                <Button
                  type="text"
                  icon={<MenuFoldOutlined />}
                  onClick={() => setSidebarCollapsed(true)}
                  style={{ 
                    color: themeMode === 'dark' ? 'rgba(255, 255, 255, .6)' : token.colorTextSecondary,
                    transition: 'color 0.3s ease, background 0.3s ease',
                    border: 'none',
                    background: 'transparent',
                  }}
                  onMouseEnter={(e) => {
                    if (themeMode === 'dark') {
                      e.currentTarget.style.background = 'rgba(255, 255, 255, .05)'
                    }
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent'
                  }}
                />
              )}
            </>
          )}
        </Flex>
      </div>

      {/* 可滚动的主要内容区域 - 在头部和用户信息之间 */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        overflowX: 'hidden',
        minHeight: 0, // 重要：允许flex子项收缩
        paddingTop: 6
      }}>

        {/* 新建对话按钮 */}
        <div style={{ padding: '0 10px' }}>
          <Tooltip title={(isMobile ? false : sidebarCollapsed) ? "新建对话" : ""} placement="right">
            <div
              style={{
                padding: '8px 10px',
                height: 40,
                borderRadius: token.borderRadius,
                background: 'transparent',
                transition: 'all 0.2s',
                border: `1px solid transparent`,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: (isMobile ? false : sidebarCollapsed) ? 'center' : 'flex-start',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary
                e.currentTarget.style.borderColor = themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
                e.currentTarget.style.borderColor = 'transparent'
              }}
              onClick={handleNewChat}
            >
              <Flex align="center" gap={8}>
                <span style={{ fontSize: 16, color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText }}>
                  <PlusOutlined />
                </span>
                {!(isMobile ? false : sidebarCollapsed) && (
                  <Text style={{ 
                    fontSize: 14, 
                    color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText,
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                  }}>
                    新建对话
                  </Text>
                )}
              </Flex>
            </div>
          </Tooltip>
        </div>

        {/* 导航菜单 */}
        <div style={{ padding: '0 10px' }}>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {menuItems.map(item => (
              <Tooltip key={item.key} title={(isMobile ? false : sidebarCollapsed) ? item.label : ""} placement="right">
                <div
                  style={{
                    padding: '8px 10px',
                    height: 40,
                    borderRadius: token.borderRadius,
                    background: currentView === item.key 
                      ? (themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary)
                      : 'transparent',
                    transition: 'all 0.2s',
                    border: `1px solid ${currentView === item.key 
                      ? (themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary)
                      : 'transparent'}`,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: (isMobile ? false : sidebarCollapsed) ? 'center' : 'flex-start',
                  }}
                  onMouseEnter={(e) => {
                    if (currentView !== item.key) {
                      e.currentTarget.style.background = themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary
                      e.currentTarget.style.borderColor = themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (currentView !== item.key) {
                      e.currentTarget.style.background = 'transparent'
                      e.currentTarget.style.borderColor = 'transparent'
                    }
                  }}
                  onClick={() => {
                    setCurrentView(item.key as any)
                    if (isMobile) {
                      setMobileDrawerVisible(false)
                    }
                  }}
                >
                  <Flex align="center" gap={8}>
                    <span style={{ fontSize: 16, color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText }}>
                      {item.icon}
                    </span>
                    {!(isMobile ? false : sidebarCollapsed) && (
                      <Text style={{ 
                        fontSize: 14, 
                        color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText,
                        fontWeight: 600,
                        whiteSpace: 'nowrap',
                      }}>
                        {item.label}
                      </Text>
                    )}
                  </Flex>
                </div>
              </Tooltip>
            ))}
          </Space>
        </div>

        {/* 最近会话 */}
        {!(isMobile ? false : sidebarCollapsed) && (
          <div style={{ padding: '0 10px', marginTop: 4 }}>
            <div style={{ 
              padding: '8px 10px',
              height: 40,
              display: 'flex',
              alignItems: 'center',
            }}>
              <Flex align="center" gap={8}>
                <HistoryOutlined style={{ 
                  fontSize: 16, 
                  color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText,
                }} />
                <Text style={{ 
                  fontSize: 14, 
                  color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText,
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                }}>
                  历史会话
                </Text>
                {sessionsLoading && (
                  <LoadingOutlined style={{ 
                    fontSize: 12, 
                    color: themeMode === 'dark' ? 'rgba(255, 255, 255, .6)' : token.colorTextSecondary,
                  }} />
                )}
              </Flex>
            </div>
            
            {sessionsLoading && displaySessions.length === 0 ? (
              <div style={{ 
                padding: '20px 10px',
                textAlign: 'center',
              }}>
                <Spin size="small" />
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    加载中...
                  </Text>
                </div>
              </div>
            ) : sessionsError && displaySessions.length === 0 ? (
              <div style={{ 
                padding: '20px 10px',
                textAlign: 'center',
              }}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                  加载失败
                </Text>
                <Button
                  type="link"
                  size="small"
                  onClick={() => loadSessions(true)}
                  style={{ fontSize: 12, padding: 0, height: 'auto' }}
                >
                  重新加载
                </Button>
              </div>
            ) : displaySessions.length === 0 ? (
              <div style={{ 
                padding: '20px 10px',
                textAlign: 'center',
              }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  暂无历史会话
                </Text>
              </div>
            ) : (
              <div style={{ paddingLeft: 24 }}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {displaySessions.map((session) => {
                    const sessionTitle = getSessionTitle(session)
                    // 只有在 chat 视图时才判断是否选中
                    const isSelected = currentView === 'chat' && currentJobId === session.job_id

                    // 会话操作菜单
                    const sessionMenuItems = [
                      {
                        key: 'rename',
                        label: '重命名',
                        icon: <EditOutlined />,
                        onClick: () => handleRenameSession(session.session_id, sessionTitle),
                      },
                      ...(isAdmin ? [
                        {
                          type: 'divider' as const,
                        },
                        {
                          key: 'delete',
                          label: '删除',
                          icon: <DeleteOutlined />,
                          danger: true,
                          onClick: () => handleDeleteSession(session.session_id, sessionTitle),
                        },
                      ] : []),
                    ]

                    return (
                      <div
                        key={session.session_id}
                        className="recent-session-item"
                        style={{
                          padding: '8px 10px',
                          borderRadius: token.borderRadius,
                          background: isSelected
                            ? (themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary)
                            : 'transparent',
                          transition: 'all 0.3s',
                          border: `1px solid ${
                            isSelected
                              ? (themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary)
                              : 'transparent'
                          }`,
                          position: 'relative',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary
                          e.currentTarget.style.borderColor = themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary
                        }}
                        onMouseLeave={(e) => {
                          if (!isSelected) {
                            e.currentTarget.style.background = 'transparent'
                            e.currentTarget.style.borderColor = 'transparent'
                          } else {
                            e.currentTarget.style.background = themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary
                            e.currentTarget.style.borderColor = themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary
                          }
                        }}
                      >
                        <Flex justify="space-between" align="center">
                          <div
                            style={{
                              fontSize: 14,
                              fontWeight: isSelected ? 600 : 500,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              color: themeMode === 'dark' 
                                ? (isSelected ? 'rgba(255, 255, 255, .84)' : 'rgba(255, 255, 255, .6)')
                                : (isSelected ? 'rgba(0, 0, 0, 1)' : 'rgba(0, 0, 0, 0.6)'),
                              cursor: 'pointer',
                              flex: 1,
                              marginRight: 8,
                              transition: 'color 0.3s ease',
                            }}
                            onClick={async () => {
                              // 防止快速连续点击
                              if (isClickingRef.current) {
                                console.log('⏱️ 正在切换会话中，忽略重复点击')
                                return
                              }

                              // 防止重复切换同一个会话
                              if (switchingJobIdRef.current === session.job_id) {
                                console.log('⏱️ 正在切换到该会话，忽略重复请求')
                                return
                              }

                              // 如果点击的是当前会话，切换到聊天视图
                              if (currentJobId === session.job_id) {
                                console.log('📋 点击当前会话，切换到聊天视图')
                                setCurrentView('chat')
                                if (isMobile) {
                                  setMobileDrawerVisible(false)
                                }
                                return
                              }
                              
                              // 标记正在点击
                              isClickingRef.current = true
                              switchingJobIdRef.current = session.job_id
                              
                              // 清除之前的计时器
                              if (clickTimeoutRef.current) {
                                clearTimeout(clickTimeoutRef.current)
                              }
                              
                              // 设置防抖计时器，1000ms后允许下一次点击
                              clickTimeoutRef.current = setTimeout(() => {
                                isClickingRef.current = false
                                switchingJobIdRef.current = null
                              }, 1000)
                              
                              // 断开当前 WebSocket 连接
                              if (websocketService.isConnected()) {
                                console.log('🔌 切换会话，断开当前 WebSocket 连接')
                                websocketService.disconnect()
                              }
                              
                              // 清除当前消息，准备加载新会话的消息
                              clearMessages()
                              
                              // 先将会话信息添加到 jobs 数组，确保标题能立即显示
                              const { addJob, updateJob, jobs } = useAppStore.getState()
                              const existingJob = jobs.find(j => j.id === session.job_id)
                              
                              if (!existingJob) {
                                // 如果 job 不存在，创建一个临时 job
                                addJob({
                                  id: session.job_id,
                                  title: session.name || session.job_id,
                                  status: 'processing',
                                  stage: 'loading',
                                  progress: 0,
                                  createdAt: new Date(session.created_at),
                                  updatedAt: new Date(session.updated_at),
                                })
                              } else if (existingJob.title !== session.name) {
                                // 如果 job 存在但标题不同，更新标题
                                updateJob(session.job_id, {
                                  title: session.name || session.job_id,
                                })
                              }
                              
                              // 切换到新会话
                              setCurrentJobId(session.job_id)
                              setIsTyping(false)  // 清除打字状态
                              setCurrentView('chat')
                              
                              // 连接新会话的 WebSocket
                              try {
                                // console.log('🔗 连接新会话的 WebSocket:', session.job_id)
                                
                                // 导入必要的模块
                                const { addMessage } = useAppStore.getState()
                                
                                await websocketService.connect(session.job_id, {
                                  onConnected: () => {
                                    // console.log('✅ 新会话 WebSocket 连接成功')
                                  },
                                  onCompletionRequest: (jobId, data) => {
                                    // 处理缺失字段补全请求
                                    // console.log('⚠️ 收到缺失字段补全请求:', data)
                                    
                                    // 如果正在等待AI回复，则忽略
                                    const isWaitingForReply = useAppStore.getState().isWaitingForReply
                                    if (isWaitingForReply) {
                                      // console.log('⏭️ 正在等待AI回复，忽略 completion_request 消息')
                                      return
                                    }
                                    
                                    // 停止打字状态
                                    setIsTyping(false)
                                    
                                    // 添加缺失字段卡片消息
                                    addMessage({
                                      type: 'assistant',
                                      content: data.message || '数据不完整，需要补全必填字段',
                                      jobId: jobId,
                                      missingFieldsData: {
                                        message: data.message || '数据不完整，需要补全必填字段',
                                        summary: data.summary || `发现 ${data.missing_fields?.length || 0} 条记录缺少必填字段`,
                                        missing_fields: data.missing_fields || [],
                                        nc_failed_items: data.nc_failed_items || [],
                                        suggestion: data.suggestion,
                                      },
                                    })
                                  },
                                  onProgress: (jobId, data) => {
                                    // 使用 getState() 获取最新的 currentJobId，避免闭包问题
                                    const latestCurrentJobId = useAppStore.getState().currentJobId
                                    
                                    // 检查消息的 job_id 是否与当前会话的 job_id 一致
                                    if (jobId !== latestCurrentJobId) {
                                      return
                                    }
                                    
                                    // 检查是否是 review_display_view 类型（显示表格）
                                    const isReviewDisplayView = (data as any).type === 'review_display_view'
                                    
                                    // 检查是否是 completion_request 类型（缺失字段请求）
                                    const isCompletionRequest = (data as any).type === 'completion_request'
                                    
                                    // 如果正在等待AI回复，且收到的是 review_display_view 或 completion_request，则忽略
                                    const isWaitingForReply = useAppStore.getState().isWaitingForReply
                                    const isRefreshing = useAppStore.getState().isRefreshing
                                    if (isWaitingForReply && !isRefreshing && (isReviewDisplayView || isCompletionRequest)) {
                                      // console.log('⏭️ 正在等待AI回复，忽略 review_display_view 或 completion_request 消息')
                                      return
                                    }
                                    
                                    // 检查是否是任务完成
                                    const isTaskCompleted = data.stage === 'completed' || data.progress === 100
                                    
                                    // 如果任务完成，停止打字状态
                                    if (isTaskCompleted) {
                                      // console.log('✅ 任务完成，停止打字状态')
                                      setIsTyping(false)
                                    }
                                    // 如果是显示表格或缺失字段请求，立即停止打字状态
                                    else if (isReviewDisplayView || isCompletionRequest) {
                                      // console.log('✅ 检测到显示表格或缺失字段请求，立即停止打字状态')
                                      setIsTyping(false)
                                    } else {
                                      // 其他进度消息才设置打字状态
                                      setIsTyping(true)
                                    }
                                    
                                    // 添加所有进度消息到聊天区域
                                    if (isCompletionRequest) {
                                      // 缺失字段请求类型的特殊处理
                                      const completionData = (data as any).data
                                      
                                      addMessage({
                                        type: 'assistant',
                                        content: completionData.message || '数据不完整，需要补全必填字段',
                                        jobId: jobId,
                                        missingFieldsData: {
                                          message: completionData.message || '数据不完整，需要补全必填字段',
                                          summary: completionData.summary || `发现 ${completionData.missing_fields?.length || 0} 条记录缺少必填字段`,
                                          missing_fields: completionData.missing_fields || [],
                                          nc_failed_items: completionData.nc_failed_items || [],
                                          suggestion: completionData.suggestion,
                                        },
                                      })
                                    } else if (isReviewDisplayView) {
                                      // 显示表格类型的特殊处理
                                      const messageData = {
                                        type: 'progress' as const,
                                        content: '特征识别完成，请检查结果并确认',
                                        jobId: jobId,
                                        progressData: {
                                          stage: 'awaiting_confirm',
                                          progress: 50,
                                          message: '特征识别完成，请检查结果并确认',
                                          type: (data as any).type,
                                          data: (data as any).data,
                                        },
                                      }
                                      
                                      addMessage(messageData)
                                    } else {
                                      // 普通进度消息
                                      const messageData = {
                                        type: 'progress' as const,
                                        content: data.message || '处理中...',
                                        jobId: jobId,
                                        progressData: {
                                          stage: data.stage,
                                          progress: data.progress || 0,
                                          message: data.message || '处理中...',
                                          details: data.details,
                                        },
                                      }
                                      
                                      addMessage(messageData)
                                      
                                      // 检查是否是 awaiting_confirm 阶段（特征识别完成，等待确认）
                                      // 从历史会话进入时，需要调用 /review/start 接口启动审核
                                      if (data.stage === 'awaiting_confirm') {
                                        // console.log('✅ 收到 awaiting_confirm，调用 /review/start 接口启动审核')
                                        setTimeout(async () => {
                                          try {
                                            setIsRefreshing(true)
                                            await chatService.startReview(jobId)
                                            console.log('✅ 审核启动成功')
                                          } catch (error) {
                                            console.error('❌ 审核启动失败:', error)
                                          } finally {
                                            setIsRefreshing(false)
                                          }
                                        }, 500)
                                      }
                                      // 检查是否是特征识别完成消息
                                      else if (data.stage === 'feature_recognition_completed') {
                                        // 检查是否是重新处理（details.type === 'reprocess'）
                                        const isReprocess =
                                          data.details?.type === 'reprocess' ||
                                          useAppStore.getState().isReprocessing === true
                                        
                                        if (isReprocess) {
                                          console.log('Wait for backend-pushed review data after feature_recognition_completed (reprocess)')
                                          setIsRefreshing(false)
                                          setIsReprocessing(false)
                                        } else {
                                          // 首次识别完成，从历史会话进入，跳过 refresh，等待 awaiting_confirm
                                          console.log('✅ 收到 feature_recognition_completed (首次)，从历史会话进入，跳过 refresh，等待 awaiting_confirm')
                                          setIsReprocessing(false) // 重置重新处理状态，恢复发送按钮
                                        }
                                      } else if (data.stage === 'pricing_completed') {
                                        console.log('Wait for backend-pushed review data after pricing_completed')
                                        setIsCalculating(false)
                                        setIsRefreshing(false)
                                        setIsReprocessing(false)
                                      } else if (data.stage === 'pricing_started') {
                                        // 价格计算开始，停止核算状态（因为已经开始了）
                                        setIsCalculating(false)
                                      }
                                    }
                                  },
                                  onReviewData: (jobId, data) => {
                                    // 使用 getState() 获取最新的 currentJobId
                                    const latestCurrentJobId = useAppStore.getState().currentJobId
                                    
                                    // 检查消息的 job_id 是否与当前会话的 job_id 一致
                                    if (jobId !== latestCurrentJobId) {
                                      return
                                    }
                                    
                                    setIsTyping(false)
                                  },
                                  onModificationConfirmation: (jobId, data) => {
                                    // 使用 getState() 获取最新的 currentJobId
                                    const latestCurrentJobId = useAppStore.getState().currentJobId
                                    
                                    // 检查消息的 job_id 是否与当前会话的 job_id 一致
                                    if (jobId !== latestCurrentJobId) {
                                      return
                                    }
                                    
                                    addMessage({
                                      type: 'system',
                                      content: '请确认以下修改：',
                                      jobId: jobId,
                                      modificationData: data,
                                    } as any)
                                    setIsTyping(false)
                                  },
                                  onReviewCompleted: (jobId, data) => {
                                    // 使用 getState() 获取最新的 currentJobId
                                    const latestCurrentJobId = useAppStore.getState().currentJobId
                                    
                                    // 检查消息的 job_id 是否与当前会话的 job_id 一致
                                    if (jobId !== latestCurrentJobId) {
                                      return
                                    }
                                    
                                    addMessage({
                                      type: 'system',
                                      content: `审核已完成，共应用了 ${data.modifications_count || 0} 项修改`,
                                      jobId: jobId,
                                    })
                                    setIsTyping(false)
                                  },
                                  onError: (_, error) => {
                                    console.error('❌ 新会话 WebSocket 连接失败:', error)
                                    setIsTyping(false)
                                  }
                                })
                              } catch (error) {
                                console.error('❌ 连接新会话 WebSocket 失败:', error)
                              }
                              
                              // 如果是移动端，点击会话后关闭抽屉
                              if (isMobile) {
                                setMobileDrawerVisible(false)
                              }
                            }}
                          >
                            {sessionTitle}
                          </div>
                          <Dropdown
                            menu={{ items: sessionMenuItems }}
                            trigger={['click']}
                            placement="bottomRight"
                          >
                            <Button
                              type="text"
                              size="small"
                              icon={<MoreOutlined />}
                              className="session-actions session-more-button"
                              style={{
                                color: themeMode === 'dark' ? 'rgba(255, 255, 255, .6)' : token.colorTextSecondary,
                                background: themeMode === 'dark' ? '#161717' : 'transparent',
                                transition: 'color 0.3s ease, background 0.3s ease',
                              }}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </Dropdown>
                        </Flex>
                      </div>
                    )
                  })}
                  
                  {/* 加载更多指示器 */}
                  {loadingMore && (
                    <div style={{
                      padding: '8px 10px',
                      textAlign: 'center',
                    }}>
                      <Spin size="small" />
                      <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                        加载更多...
                      </Text>
                    </div>
                  )}
                  
                  {/* 查看全部按钮 */}
                  {sessions.length >= 5 && (
                    <div
                      className="recent-session-item"
                      style={{
                        padding: '8px 10px',
                        borderRadius: token.borderRadius,
                        background: currentView === 'history' 
                          ? (themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary)
                          : 'transparent',
                        transition: 'all 0.2s',
                        border: `1px solid ${currentView === 'history' 
                          ? (themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary)
                          : 'transparent'}`,
                        position: 'relative',
                        marginTop: 4,
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary
                        e.currentTarget.style.borderColor = themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary
                      }}
                      onMouseLeave={(e) => {
                        if (currentView !== 'history') {
                          e.currentTarget.style.background = 'transparent'
                          e.currentTarget.style.borderColor = 'transparent'
                        } else {
                          e.currentTarget.style.background = themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillTertiary
                          e.currentTarget.style.borderColor = themeMode === 'dark' ? 'transparent' : token.colorBorderSecondary
                        }
                      }}
                    >
                      <Flex justify="space-between" align="center">
                        <div
                          style={{
                            fontSize: 14,
                            fontWeight: currentView === 'history' ? 600 : 500,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            color: themeMode === 'dark'
                              ? (currentView === 'history' ? 'rgba(255, 255, 255, .84)' : 'rgba(255, 255, 255, .6)')
                              : (currentView === 'history' ? 'rgba(0, 0, 0, 1)' : 'rgba(0, 0, 0, 0.6)'),
                            cursor: 'pointer',
                            flex: 1,
                            marginRight: 8,
                          }}
                          onClick={() => {
                            setCurrentView('history')
                            // 不清除 currentJobId，保留以便返回时恢复
                            if (isMobile) {
                              setMobileDrawerVisible(false)
                            }
                          }}
                        >
                          查看全部
                        </div>
                        <Button
                          type="text"
                          size="small"
                          style={{
                            visibility: 'hidden',
                            width: 24,
                            height: 24,
                          }}
                        />
                      </Flex>
                    </div>
                  )}
                </Space>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 用户信息 - 固定在底部 */}
      <div style={{
        flexShrink: 0, // 固定不收缩
      }}>
        <UserInfoSection sidebarCollapsed={isMobile ? false : sidebarCollapsed} />
      </div>

      {/* 重命名弹窗 */}
      <Modal
        title="重命名会话"
        open={renameModalVisible}
        onOk={handleSaveRename}
        onCancel={handleCancelRename}
        okText="确定"
        cancelText="取消"
        width={400}
        confirmLoading={renamingLoading}
      >
        <Input
          value={renameInputValue}
          onChange={(e) => setRenameInputValue(e.target.value)}
          onPressEnter={handleSaveRename}
          placeholder="请输入新的会话名称"
          autoFocus
          maxLength={50}
          disabled={renamingLoading}
          style={{
            fontSize: 14,
          }}
        />
      </Modal>
    </div>
  )

  // 移动端使用普通div，桌面端使用Sider
  if (isMobile) {
    return (
      <div style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: themeMode === 'dark' ? '#161717' : '#F3F5F6',
        position: 'relative',
        transition: 'background 0.3s ease',
      }}>
        {sidebarContent}
      </div>
    )
  }

  return (
    <Sider
      width={280}
      collapsedWidth={72}
      collapsible
      collapsed={sidebarCollapsed}
      onCollapse={setSidebarCollapsed}
      trigger={null}
      style={{
        background: themeMode === 'dark' ? '#161717' : '#F3F5F6',
        borderRight: `1px solid ${themeMode === 'dark' ? 'rgba(255, 255, 255, .1)' : token.colorBorderSecondary}`,
        boxShadow: token.boxShadowTertiary,
        position: 'relative',
        transition: 'background 0.3s ease, border-right 0.3s ease',
      }}
    >
      {sidebarContent}
    </Sider>
  )
}

export default Sidebar

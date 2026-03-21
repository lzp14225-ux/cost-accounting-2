import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { 
  Card, 
  Typography, 
  Input,
  Space, 
  Flex,
  theme,
  Button,
  Empty,
  Dropdown,
  Spin,
  message,
  Modal,
} from 'antd'
import { 
  HistoryOutlined,
  SearchOutlined,
  MenuOutlined,
  CloseOutlined,
  MoreOutlined,
  EditOutlined,
  DeleteOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CheckCircleFilled,
} from '@ant-design/icons'
import { useAppStore } from '../store/useAppStore'
import { sessionService, SessionItem } from '../services/sessionService'
import { websocketService } from '../services/websocketService'
import { chatService } from '../services/chatService'

const { Text } = Typography

const HistorySessions: React.FC = () => {
  const { token } = theme.useToken()
  const { 
    isMobile, 
    setMobileDrawerVisible, 
    currentJobId,
    setCurrentJobId, 
    setCurrentView, 
    setSidebarCollapsed,
    sessions,
    sessionsLoading,
    sessionsTotal,
    hasMoreSessions,
    setSessions,
    addSessions,
    setSessionsLoading,
    deleteSession: deleteSessionFromStore,
    updateSession,
    setIsRefreshing,
    setIsReprocessing,
  } = useAppStore()
  
  const [searchText, setSearchText] = useState('')
  const [windowWidth, setWindowWidth] = useState(window.innerWidth)
  const [loadingMore, setLoadingMore] = useState(false)
  const [allSessionsLoaded, setAllSessionsLoaded] = useState(false)
  const [sessionsError, setSessionsError] = useState(false) // 添加错误状态
  const [renameModalVisible, setRenameModalVisible] = useState(false)
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null)
  const [renameInputValue, setRenameInputValue] = useState('')
  const [renamingLoading, setRenamingLoading] = useState(false) // 新增：重命名加载状态
  const [selectionMode, setSelectionMode] = useState(false) // 新增：是否处于选择模式
  const [selectedSessions, setSelectedSessions] = useState<Set<string>>(new Set()) // 新增：已选择的会话ID集合
  const [deletingBatch, setDeletingBatch] = useState(false) // 新增：批量删除加载状态
  const hasInitializedRef = useRef(false) // 添加ref防止重复初始化
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

  // 加载所有会话
  const loadAllSessions = useCallback(async (forceReload = false) => {
    // 防止重复初始化
    if (hasInitializedRef.current && !forceReload) return
    if (allSessionsLoaded && !forceReload) return
    
    try {
      hasInitializedRef.current = true
      setSessionsLoading(true)
      setSessionsError(false) // 清除错误状态
      const response = await sessionService.getSessions({ limit: 50 })
      setSessions(response.sessions, response.total_count, 0)
      setAllSessionsLoaded(true)
    } catch (error: any) {
      console.error('加载会话列表失败:', error)
      setSessionsError(true) // 设置错误状态
      hasInitializedRef.current = false // 出错时重置，允许重试
      if (error.message?.includes('Token') || error.message?.includes('认证')) {
        // Token失效，不显示错误消息，让用户重新登录
        return
      }
      // 不显示全局错误消息，在UI中显示重新加载按钮
    } finally {
      setSessionsLoading(false)
    }
  }, [allSessionsLoaded, setSessions, setSessionsLoading])

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

  // 组件挂载时加载所有会话
  useEffect(() => {
    loadAllSessions()
  }, [loadAllSessions])

  // 监听窗口大小变化
  React.useEffect(() => {
    const handleResize = () => {
      setWindowWidth(window.innerWidth)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // 清理防抖计时器
  React.useEffect(() => {
    return () => {
      if (clickTimeoutRef.current) {
        clearTimeout(clickTimeoutRef.current)
      }
    }
  }, [])

  const isSmallScreen = windowWidth < 960

  // 处理返回聊天
  const handleBackToChat = () => {
    setCurrentView('chat')
    if (isMobile) {
      setMobileDrawerVisible(false)
    }
  }

  // 处理打开侧边栏
  const handleOpenSidebar = () => {
    if (isMobile) {
      setMobileDrawerVisible(true)
    } else {
      setSidebarCollapsed(false)
    }
  }

  // 获取会话标题
  const getSessionTitle = (session: SessionItem) => {
    return session.name || session.job_id || `会话 ${session.session_id.slice(0, 8)}`
  }

  // 格式化日期
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))
    
    if (days === 0) {
      return '今天'
    } else if (days === 1) {
      return '昨天'
    } else if (days < 7) {
      return `${days}天前`
    } else {
      return date.toLocaleDateString('zh-CN', { 
        year: 'numeric', 
        month: '2-digit', 
        day: '2-digit' 
      })
    }
  }

  // 过滤和搜索会话
  const filteredSessions = useMemo(() => {
    let result = [...sessions]
    
    if (searchText.trim()) {
      result = result.filter(session => {
        const title = getSessionTitle(session).toLowerCase()
        return title.includes(searchText.toLowerCase())
      })
    }
    
    // 按更新时间排序
    // result.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    
    return result
  }, [sessions, searchText])

  // 按日期分组
  const groupedSessions = useMemo(() => {
    const groups: { [key: string]: SessionItem[] } = {}
    
    filteredSessions.forEach(session => {
      const dateKey = formatDate(session.updated_at)
      if (!groups[dateKey]) {
        groups[dateKey] = []
      }
      groups[dateKey].push(session)
    })
    
    return groups
  }, [filteredSessions])

  // 处理会话点击
  const handleSessionClick = async (session: SessionItem) => {
    // 防止快速连续点击
    if (isClickingRef.current) {
      return
    }

    // 防止重复切换同一个会话
    if (switchingJobIdRef.current === session.job_id) {
      return
    }

    // 如果处于选择模式，切换选择状态
    if (selectionMode) {
      handleToggleSelection(session.session_id)
      return
    }
    
    // 如果点击的是当前会话，只切换视图，不重新连接 WebSocket
    if (currentJobId === session.job_id) {
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
      websocketService.disconnect()
    }
    
    // 切换到新会话
    setCurrentJobId(session.job_id)
    setCurrentView('chat')
    
    // 连接新会话的 WebSocket，标记为从历史会话切换
    try {
      // console.log('🔗 连接新会话的 WebSocket:', session.job_id)
      
      // 导入必要的模块
      const { addMessage, setIsTyping } = useAppStore.getState()
      
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
              summary: `发现 ${data.missing_fields?.length || 0} 条记录缺少必填字段`,
              missing_fields: data.missing_fields || [],
              suggestion: data.suggestion,
            },
          })
        },
        onProgress: (jobId, data) => {
          // 检查是否是 review_display_view 类型（显示表格）
          const isReviewDisplayView = (data as any).type === 'review_display_view'
          
          // 检查是否是 completion_request 类型（缺失字段请求）
          const isCompletionRequest = (data as any).type === 'completion_request'
          
          // 如果正在等待AI回复，且收到的是 review_display_view 或 completion_request，则忽略
          const isWaitingForReply = useAppStore.getState().isWaitingForReply
          if (isWaitingForReply && (isReviewDisplayView || isCompletionRequest)) {
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
                summary: `发现 ${completionData.missing_fields?.length || 0} 条记录缺少必填字段`,
                missing_fields: completionData.missing_fields || [],
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
          }
        },
        onReviewData: (jobId, data) => {
          setIsTyping(false)
        },
        onModificationConfirmation: (jobId, data) => {
          addMessage({
            type: 'system',
            content: '请确认以下修改：',
            jobId: jobId,
            modificationData: data,
          } as any)
          setIsTyping(false)
        },
        onReviewCompleted: (jobId, data) => {
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
      }, undefined, true) // 传入 fromHistorySwitch = true
    } catch (error) {
      console.error('❌ 连接新会话 WebSocket 失败:', error)
    }
    
    if (isMobile) {
      setMobileDrawerVisible(false)
    }
  }

  // 切换选择状态
  const handleToggleSelection = (sessionId: string) => {
    setSelectedSessions(prev => {
      const newSet = new Set(prev)
      if (newSet.has(sessionId)) {
        newSet.delete(sessionId)
      } else {
        newSet.add(sessionId)
      }
      return newSet
    })
  }

  // 退出选择模式
  const handleExitSelectionMode = () => {
    setSelectionMode(false)
    setSelectedSessions(new Set())
  }

  // 全选/取消全选
  const handleToggleSelectAll = () => {
    if (selectedSessions.size === filteredSessions.length) {
      // 已全选，取消全选
      setSelectedSessions(new Set())
    } else {
      // 未全选，全选
      setSelectedSessions(new Set(filteredSessions.map(s => s.session_id)))
    }
  }

  // 批量删除
  const handleBatchDelete = () => {
    if (selectedSessions.size === 0) {
      message.warning('请先选择要删除的会话')
      return
    }

    Modal.confirm({
      title: '批量删除会话',
      content: `确定要删除选中的 ${selectedSessions.size} 个会话吗？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          setDeletingBatch(true)
          
          // 获取选中会话的 job_id 列表
          const jobIds = sessions
            .filter(s => selectedSessions.has(s.session_id))
            .map(s => s.job_id)
          
          // 调用批量删除接口
          const result = await sessionService.batchDeleteSessions(jobIds)
          
          // 显示删除结果
          if (result.success) {
            const { success_count, failed_count, total_deleted } = result.data
            
            if (failed_count === 0) {
              message.success(`成功删除 ${success_count} 个会话，共删除 ${total_deleted} 条记录`)
            } else {
              // 有部分失败，显示详细信息
              const failedJobs = result.data.results
                .filter(r => !r.success)
                .map(r => r.job_id)
              
              message.warning({
                content: `批量删除完成：成功 ${success_count} 个，失败 ${failed_count} 个`,
                duration: 5,
              })
              
              console.warn('部分会话删除失败:', failedJobs)
            }
          } else {
            message.error(result.message || '批量删除失败')
          }
          
          // 重新加载会话列表
          await loadAllSessions(true)
          
          // 退出选择模式
          handleExitSelectionMode()
        } catch (error: any) {
          console.error('批量删除失败:', error)
          message.error(error.message || '批量删除失败')
        } finally {
          setDeletingBatch(false)
        }
      },
    })
  }

  // 处理会话重命名 - 打开弹窗
  const handleRenameSession = async (sessionId: string, currentTitle: string) => {
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
          
          await sessionService.deleteSession(session.job_id)
          
          // 删除成功后重新加载会话列表，而不是只从本地状态删除
          await loadAllSessions(true)
          
          message.success('会话删除成功')
        } catch (error) {
          console.error('删除失败:', error)
          message.error('删除失败')
        }
      },
    })
  }

  // 监听滚动事件，实现无限滚动
  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100
    
    if (isNearBottom && hasMoreSessions && !loadingMore) {
      loadMoreSessions()
    }
  }, [hasMoreSessions, loadingMore, loadMoreSessions])

  return (
    <div style={{ 
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: '#ffffff',
      position: 'relative', // 添加相对定位，作为绝对定位的参考
    }}>
      <style>{`
        .history-search-input.ant-input-affix-wrapper {
          height: 46px;
          padding: 8px 12px;
        }
        .history-search-input.ant-input-affix-wrapper:focus,
        .history-search-input.ant-input-affix-wrapper-focused {
          border-color: transparent !important;
          box-shadow: none !important;
        }
        .history-search-input .ant-input-prefix {
          margin-right: 10px;
        }
      `}</style>
      {/* 顶部导航栏 */}
      <div style={{
        padding: '12px 24px',
        background: '#ffffff',
      }}>
        <Flex align="center" justify="space-between">
          {/* 左侧：小屏幕显示菜单按钮 */}
          <div style={{ width: 40 }}>
            {isSmallScreen && (
              <Button
                type="text"
                icon={<MenuOutlined />}
                onClick={handleOpenSidebar}
                style={{
                  color: token.colorTextSecondary,
                  padding: '4px 8px',
                  height: 32,
                  width: 32,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              />
            )}
          </div>
          {/* 中间：空白 */}
          <div style={{ flex: 1 }} />
          {/* 右侧：关闭按钮 */}
          <Button
            type="text"
            icon={<CloseOutlined />}
            onClick={handleBackToChat}
            style={{
              color: token.colorTextSecondary,
              padding: '4px 8px',
              height: 32,
              width: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          />
        </Flex>
      </div>

      {/* 标题 */}
      <div style={{
        padding: '0 120px 12px',
        background: '#ffffff',
      }}>
        <div style={{ maxWidth: 800, margin: '0 auto' }}>
          <Flex align="center" gap={12}>
            <HistoryOutlined style={{ fontSize: 20, color: token.colorPrimary }} />
            <Text style={{ fontSize: 18, fontWeight: 600 }}>历史会话</Text>
            {sessionsLoading && (
              <LoadingOutlined style={{ 
                fontSize: 16, 
                color: token.colorTextSecondary,
              }} />
            )}
          </Flex>
        </div>
      </div>

      {/* 搜索框 */}
      <div style={{ 
        padding: '24px 120px',
        background: '#ffffff',
      }}>
        <div style={{ maxWidth: 800, margin: '0 auto' }}>
          <Input
            className="history-search-input"
            placeholder="搜索历史会话"
            prefix={<SearchOutlined style={{ color: token.colorTextSecondary }} />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            size="large"
            style={{
              borderRadius: 8,
              background: '#F5F5F5',
              border: 'none',
            }}
          />
        </div>
      </div>

      {/* 内容区域 */}
      <div 
        style={{ 
          flex: 1,
          overflow: 'auto',
          padding: '0 120px 24px',
        }}
        onScroll={handleScroll}
      >
        <div style={{ maxWidth: 800, margin: '0 auto' }}>
        {sessionsLoading && sessions.length === 0 ? (
          <div style={{ textAlign: 'center', marginTop: 60 }}>
            <Spin size="large" />
            <div style={{ marginTop: 16 }}>
              <Text type="secondary">加载会话列表中...</Text>
            </div>
          </div>
        ) : sessionsError && sessions.length === 0 ? (
          <div style={{ textAlign: 'center', marginTop: 60 }}>
            <Empty 
              description={
                <Space direction="vertical" size={8}>
                  <Text type="secondary">加载会话列表失败</Text>
                  <Button
                    type="primary"
                    onClick={() => {
                      setAllSessionsLoaded(false)
                      hasInitializedRef.current = false // 重置ref状态
                      loadAllSessions(true) // 强制重新加载
                    }}
                  >
                    重新加载
                  </Button>
                </Space>
              }
            />
          </div>
        ) : filteredSessions.length === 0 ? (
          <Empty 
            description={searchText ? '未找到匹配的会话' : '暂无历史会话'}
            style={{ marginTop: 60 }}
          />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={24}>
            {Object.entries(groupedSessions).map(([dateKey, sessionsInGroup]) => (
              <div key={dateKey}>
                <Text 
                  type="secondary" 
                  style={{ 
                    fontSize: 12, 
                    fontWeight: 500,
                    display: 'block',
                    marginBottom: 12,
                  }}
                >
                  {dateKey}
                </Text>
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  {sessionsInGroup.map((session) => {
                    const sessionTitle = getSessionTitle(session)
                    
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
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 0,
                          marginLeft: -52, // 负边距，让选择框区域向左偏移
                        }}
                        className="session-item-wrapper"
                        onMouseEnter={(e) => {
                          // 显示选择框
                          const checkbox = e.currentTarget.querySelector('.session-checkbox') as HTMLElement
                          if (checkbox && !selectionMode) {
                            checkbox.style.opacity = '1'
                          }
                          // 子项背景色
                          const content = e.currentTarget.querySelector('.session-content') as HTMLElement
                          if (content) {
                            content.style.background = token.colorFillTertiary
                          }
                        }}
                        onMouseLeave={(e) => {
                          // 隐藏选择框（除非处于选择模式）
                          const checkbox = e.currentTarget.querySelector('.session-checkbox') as HTMLElement
                          if (checkbox && !selectionMode) {
                            checkbox.style.opacity = '0'
                          }
                          // 子项背景色 - 如果已选中，保持hover颜色
                          const content = e.currentTarget.querySelector('.session-content') as HTMLElement
                          if (content) {
                            const isSelected = selectedSessions.has(session.session_id)
                            content.style.background = isSelected ? token.colorFillTertiary : 'transparent'
                          }
                        }}
                      >
                        {/* 圆形选择框区域 - 固定宽度52px */}
                        <div
                          style={{
                            width: 52,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexShrink: 0,
                          }}
                        >
                          {isAdmin && (
                            <div
                              className="session-checkbox"
                              style={{
                                width: 20,
                                height: 20,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                cursor: 'pointer',
                                transition: 'all 0.2s',
                                opacity: selectionMode ? 1 : 0,
                              }}
                              onClick={(e) => {
                                e.stopPropagation()
                                if (!selectionMode) {
                                  setSelectionMode(true)
                                }
                                handleToggleSelection(session.session_id)
                              }}
                            >
                              {selectedSessions.has(session.session_id) ? (
                                <CheckCircleFilled style={{ fontSize: 20, color: token.colorPrimary }} />
                              ) : (
                                <div
                                  style={{
                                    width: 20,
                                    height: 20,
                                    borderRadius: '50%',
                                    border: `2px solid ${token.colorBorder}`,
                                  background: 'transparent',
                                }}
                              />
                            )}
                            </div>
                          )}
                        </div>
                        
                        {/* 子项内容 - 独立在右边，左侧与搜索框对齐 */}
                        <div
                          className="session-content"
                          style={{
                            flex: 1,
                            padding: '12px 16px',
                            borderRadius: 8,
                            cursor: 'pointer',
                            transition: 'all 0.2s',
                            background: selectedSessions.has(session.session_id) ? token.colorFillTertiary : 'transparent',
                          }}
                        >
                          <Flex justify="space-between" align="center">
                            <div
                              style={{ flex: 1, marginRight: 8 }}
                              onClick={() => handleSessionClick(session)}
                            >
                              <Text 
                                strong 
                                style={{ 
                                  fontSize: 16,
                                  display: 'block',
                                }}
                              >
                                {sessionTitle}
                              </Text>
                              <Text 
                                type="secondary" 
                                style={{ 
                                  fontSize: 12,
                                  display: 'block',
                                  marginTop: 4,
                                }}
                              >
                                状态: {session.status}
                              </Text>
                            </div>
                            
                            {!selectionMode && (
                              <Dropdown
                                menu={{ items: sessionMenuItems }}
                                trigger={['click']}
                                placement="bottomRight"
                              >
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<MoreOutlined />}
                                  style={{
                                    color: token.colorTextSecondary,
                                  }}
                                  onClick={(e) => e.stopPropagation()}
                                />
                              </Dropdown>
                            )}
                          </Flex>
                        </div>
                      </div>
                    )
                  })}
                </Space>
              </div>
            ))}
            
            {/* 加载更多指示器 */}
            {loadingMore && (
              <div style={{
                padding: '20px',
                textAlign: 'center',
              }}>
                <Spin size="small" />
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  加载更多会话...
                </Text>
              </div>
            )}
            
            {/* 已加载全部提示 */}
            {!hasMoreSessions && sessions.length > 0 && (
              <div style={{
                padding: '20px',
                textAlign: 'center',
              }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已显示全部 {sessionsTotal} 个会话
                </Text>
              </div>
            )}
          </Space>
        )}
        </div>
      </div>

      {/* 底部悬浮操作栏 - 选择模式时显示，在右侧内容区域居中 */}
      {isAdmin && selectionMode && (
        <div
          style={{
            position: 'absolute',
            bottom: 24,
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            zIndex: 1000,
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              background: '#F5F5F5',
              borderRadius: 16,
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.18), 0 2px 8px rgba(0, 0, 0, 0.08)',
              padding: '12px 24px',
              display: 'flex',
              alignItems: 'center',
              gap: 16,
              minWidth: 320,
              pointerEvents: 'auto',
            }}
          >
            {/* 退出按钮 */}
            <Button
              type="text"
              icon={<CloseOutlined />}
              onClick={handleExitSelectionMode}
              style={{
                color: token.colorTextSecondary,
              }}
            >
              退出
            </Button>

            {/* 已选择数量 */}
            <div style={{ flex: 1, textAlign: 'center' }}>
              <Text style={{ fontSize: 14, color: token.colorText }}>
                已选择 {selectedSessions.size} 个会话
              </Text>
            </div>

            {/* 全选/取消全选按钮 */}
            <Button
              type="text"
              onClick={handleToggleSelectAll}
              style={{
                color: token.colorPrimary,
              }}
            >
              {selectedSessions.size === filteredSessions.length ? '取消全选' : '全选'}
            </Button>

            {/* 删除按钮 */}
            <Button
              type="primary"
              danger
              icon={<DeleteOutlined />}
              onClick={handleBatchDelete}
              loading={deletingBatch}
              disabled={selectedSessions.size === 0}
            >
              删除
            </Button>
          </div>
        </div>
      )}

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
}

export default HistorySessions

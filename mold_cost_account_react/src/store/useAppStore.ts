import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { SessionItem } from '../services/sessionService'

// 意图类型
export type IntentType = 
  | 'DATA_MODIFICATION'      // 数据修改
  | 'FEATURE_RECOGNITION'    // 特征识别
  | 'PRICE_CALCULATION'      // 价格计算
  | 'WEIGHT_PRICE_CALCULATION' // 按重量计算价格
  | 'QUERY_DETAILS'          // 查询详情
  | 'GENERAL_CHAT'           // 普通聊天

export interface Message {
  id: string
  type: 'user' | 'assistant' | 'system' | 'progress'
  content: string
  timestamp: Date
  jobId?: string
  attachments?: FileAttachment[]
  progressData?: ProgressMessageData
  modificationData?: ModificationMessageData
  // 新增：意图识别相关字段
  intent?: IntentType
  requiresConfirmation?: boolean
  intentData?: any  // 意图相关的数据（如子图ID列表、修改详情等）
  // 新增：数据完整性检查相关字段
  missingFieldsData?: MissingFieldsData
  // 新增：历史消息相关字段
  reviewData?: any[]  // 审核数据展示
  reviewStartData?: any  // 审核启动数据
  modificationConfirmation?: boolean  // 是否是修改确认消息
  operationCompleted?: {  // 操作完成数据
    action_type?: string
    result?: any
  }
  // 新增：确认状态
  confirmationStatus?: 'confirmed' | 'cancelled'  // 确认状态：已确认或已取消
}

export interface MissingFieldsData {
  message: string
  summary?: string
  missing_fields: Array<{
    table: string
    record_id: string
    record_name: string
    part_code?: string  // 新增：零件编号
    part_name?: string  // 新增：零件名称
    missing: Record<string, string>
    current_values: Record<string, any>
  }>
  nc_failed_items?: NCFailedItem[]
  suggestion?: string
}

export interface NCFailedItem {
  record_id: string
  record_name: string
  subgraph_id?: string
  part_code?: string
  part_name?: string
  reason?: string
}

export interface ModificationMessageData {
  modification_id: string
  parsed_changes: ParsedChange[]
  action_required: 'confirm'
  display_view?: any[] // 新增：显示视图数据
}

export interface ParsedChange {
  table: string
  id: string | number
  field: string
  value: any // 新值
  old_value?: any // 原值（可选）
  new_value?: any // 新值（兼容旧格式）
}

export interface ProgressMessageData {
  stage: string
  progress: number
  message: string
  details?: Record<string, any>
  // 新增：审核数据展示类型
  type?: string
  data?: any
}

export interface FileAttachment {
  id: string
  name: string
  size: number
  type: string
  url?: string
}

export interface Job {
  id: string
  title?: string
  status: 'pending' | 'processing' | 'need_user_input' | 'completed' | 'failed' | 'archived'
  stage: string
  progress: number
  dwgFile?: FileAttachment
  prtFile?: FileAttachment
  totalCost?: number
  subgraphsCount?: number
  createdAt: Date
  updatedAt: Date
  errorMessage?: string
}

export interface InteractionCard {
  id: string
  type: 'missing_input' | 'choice' | 'review'
  title: string
  message: string
  severity: 'info' | 'warning' | 'error'
  fields?: InputField[]
  buttons?: CardButton[]
  jobId: string
}

export interface InputField {
  key: string
  label: string
  component: 'input' | 'number' | 'select' | 'textarea'
  required: boolean
  defaultValue?: any
  options?: { label: string; value: any }[]
  min?: number
  max?: number
  subgraphId?: string
}

export interface CardButton {
  key: string
  label: string
  style: 'primary' | 'default' | 'danger'
}

interface AppState {
  // UI State
  currentView: 'chat' | 'price' | 'process' | 'jobs' | 'settings' | 'history'
  sidebarCollapsed: boolean
  initialized: boolean
  isMobile: boolean // 是否为移动端
  mobileDrawerVisible: boolean // 移动端抽屉是否可见
  themeMode: 'light' | 'dark' // 新增：主题模式
  
  // Chat State
  messages: Message[]
  isTyping: boolean
  currentJobId?: string
  isLoadingHistory: boolean  // 新增：是否正在加载历史消息
  historyLoadError: string | null  // 新增：历史消息加载错误信息
  isNewSession: boolean  // 新增：标记是否为新创建的会话（刚上传文件）
  isCalculating: boolean  // 新增：是否正在进行核算
  isStartingReview: boolean  // 新增：是否正在启动审核（调用/review/start接口）
  isRefreshing: boolean  // 新增：是否正在刷新审核数据（调用/review/refresh接口）
  reviewStarted: boolean  // 新增：审核是否已启动完成（/review/start接口已完成）
  isReprocessing: boolean  // 新增：是否正在重新处理（重新识别特征或重新计算价格）
  loadingSessionId: string | null  // 新增：当前正在加载的会话ID，用于防止竞态条件
  isWaitingForReply: boolean  // 新增：是否正在等待AI回复（发送消息后）
  
  // Jobs State
  jobs: Job[]
  
  // Sessions State
  sessions: SessionItem[]
  sessionsLoading: boolean
  sessionsTotal: number
  sessionsOffset: number
  hasMoreSessions: boolean
  
  // Interaction State
  interactionCards: InteractionCard[]
  
  // WebSocket State
  wsConnected: boolean
  
  // Actions
  setCurrentView: (view: 'chat' | 'price' | 'process' | 'jobs' | 'settings' | 'history') => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setInitialized: (initialized: boolean) => void
  setIsMobile: (isMobile: boolean) => void
  setMobileDrawerVisible: (visible: boolean) => void
  setThemeMode: (mode: 'light' | 'dark') => void // 新增：设置主题模式
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void
  setIsTyping: (typing: boolean) => void
  setCurrentJobId: (jobId?: string) => void
  setIsLoadingHistory: (loading: boolean) => void  // 新增：设置加载历史消息状态
  setHistoryLoadError: (error: string | null) => void  // 新增：设置历史消息加载错误
  setIsNewSession: (isNew: boolean) => void  // 新增：设置是否为新会话
  setIsCalculating: (calculating: boolean) => void  // 新增：设置是否正在核算
  setIsStartingReview: (starting: boolean) => void  // 新增：设置是否正在启动审核
  setIsRefreshing: (refreshing: boolean) => void  // 新增：设置是否正在刷新审核数据
  setReviewStarted: (started: boolean) => void  // 新增：设置审核是否已启动完成
  setIsReprocessing: (reprocessing: boolean) => void  // 新增：设置是否正在重新处理
  setIsWaitingForReply: (waiting: boolean) => void  // 新增：设置是否正在等待AI回复
  updateJob: (jobId: string, updates: Partial<Job>) => void
  addJob: (job: Job) => void
  deleteJob: (jobId: string) => void
  setSessions: (sessions: SessionItem[], total: number, offset: number) => void
  addSessions: (sessions: SessionItem[], total: number, offset: number) => void
  setSessionsLoading: (loading: boolean) => void
  deleteSession: (sessionId: string) => void
  updateSession: (sessionId: string, updates: Partial<SessionItem>) => void
  addInteractionCard: (card: InteractionCard) => void
  removeInteractionCard: (cardId: string) => void
  setWsConnected: (connected: boolean) => void
  clearMessages: () => void
  resetUploadState: () => void  // 新增：重置上传状态
  setMessages: (messages: Message[] | ((prevMessages: Message[]) => Message[])) => void
  loadHistoryMessages: (sessionId: string) => Promise<void>
  cancelLoadingHistory: () => void  // 新增：取消正在进行的历史加载
}

const isReviewTableMessage = (message?: Message | Omit<Message, 'id' | 'timestamp'> | null): boolean => {
  if (!message) return false

  return (
    (message.type === 'progress' && message.progressData?.type === 'review_display_view' && Array.isArray(message.progressData?.data)) ||
    (message.type === 'system' && Array.isArray(message.reviewData))
  )
}

const isMissingFieldsMessage = (message?: Message | Omit<Message, 'id' | 'timestamp'> | null): boolean => {
  return !!message?.missingFieldsData
}

const isStandaloneAwaitingConfirmMessage = (message?: Message | Omit<Message, 'id' | 'timestamp'> | null): boolean => {
  return !!message && message.type === 'progress' && message.progressData?.stage === 'awaiting_confirm' && message.progressData?.type !== 'review_display_view'
}

const isNcReviewPredecessorStage = (stage?: string): boolean => {
  return stage === 'nc_calculation_completed' || stage === 'nc_calculation_skipped'
}

const hasUserDrivenMessagesAfterReviewTable = (messages: Message[], reviewTableIndex: number): boolean => {
  if (reviewTableIndex < 0) return false

  return messages.slice(reviewTableIndex + 1).some(message => (
    message.type === 'user' ||
    !!message.operationCompleted ||
    !!message.modificationConfirmation ||
    ((message.type === 'assistant' || message.type === 'system') &&
      !isMissingFieldsMessage(message) &&
      !isStandaloneAwaitingConfirmMessage(message) &&
      !isReviewTableMessage(message) &&
      !!message.content?.trim())
  ))
}

const insertMessageWithReviewGrouping = (messages: Message[], message: Message): Message[] => {
  const nextMessages = [...messages]
  const lastReviewTableIndex = nextMessages.reduce((foundIndex, currentMessage, currentIndex) => (
    isReviewTableMessage(currentMessage) ? currentIndex : foundIndex
  ), -1)

  if (isReviewTableMessage(message)) {
    if (hasUserDrivenMessagesAfterReviewTable(nextMessages, lastReviewTableIndex)) {
      nextMessages.push(message)
      return nextMessages
    }

    const lastNcIndex = nextMessages.reduce((foundIndex, currentMessage, currentIndex) => (
      currentMessage.type === 'progress' && isNcReviewPredecessorStage(currentMessage.progressData?.stage)
        ? currentIndex
        : foundIndex
    ), -1)

    const insertIndex = lastNcIndex >= 0 ? lastNcIndex + 1 : nextMessages.length
    nextMessages.splice(insertIndex, 0, message)
    return nextMessages
  }

  if (isMissingFieldsMessage(message) || isStandaloneAwaitingConfirmMessage(message)) {
    if (lastReviewTableIndex >= 0) {
      let insertIndex = lastReviewTableIndex + 1
      while (insertIndex < nextMessages.length && isMissingFieldsMessage(nextMessages[insertIndex])) {
        insertIndex += 1
      }
      nextMessages.splice(insertIndex, 0, message)
      return nextMessages
    }
  }

  if (
    message.type === 'progress' &&
    isNcReviewPredecessorStage(message.progressData?.stage) &&
    lastReviewTableIndex >= 0
  ) {
    nextMessages.splice(lastReviewTableIndex, 0, message)
    return nextMessages
  }

  nextMessages.push(message)
  return nextMessages
}

const normalizeReviewMessageOrder = (messages: Message[]): Message[] => {
  return messages.reduce<Message[]>((orderedMessages, currentMessage) => {
    return insertMessageWithReviewGrouping(orderedMessages, currentMessage)
  }, [])
}

export const useAppStore = create<AppState>()(
  devtools(
    (set, get) => ({
      // Initial State
      currentView: 'chat',
      sidebarCollapsed: false,
      initialized: false,
      isMobile: false,
      mobileDrawerVisible: false,
      themeMode: (localStorage.getItem('themeMode') as 'light' | 'dark') || 'light', // 新增：从 localStorage 读取主题，默认浅色
      messages: [], // 移除初始欢迎消息，让用户看到欢迎卡片
      isTyping: false,
      currentJobId: undefined, // 确保初始为 undefined，进入新建对话状态
      isLoadingHistory: false,  // 新增：初始化为false
      historyLoadError: null,  // 新增：初始化为null
      isNewSession: false,  // 新增：初始化为false
      isCalculating: false,  // 新增：初始化为false
      isStartingReview: false,  // 新增：初始化为false
      isRefreshing: false,  // 新增：初始化为false
      reviewStarted: false,  // 新增：初始化为false
      isReprocessing: false,  // 新增：初始化为false
      loadingSessionId: null,  // 新增：初始化为null
      isWaitingForReply: false,  // 新增：初始化为false
      jobs: [],
      sessions: [],
      sessionsLoading: false,
      sessionsTotal: 0,
      sessionsOffset: 0,
      hasMoreSessions: false,
      interactionCards: [],
      wsConnected: false,

      // Actions
      setCurrentView: (view) => set({ currentView: view }),
      
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      
      setInitialized: (initialized) => set({ initialized }),
      
      setIsMobile: (isMobile) => set({ isMobile }),
      
      setMobileDrawerVisible: (visible) => set({ mobileDrawerVisible: visible }),
      
      setThemeMode: (mode) => {
        localStorage.setItem('themeMode', mode) // 持久化到 localStorage
        set({ themeMode: mode })
      },
      
      addMessage: (message) => set((state) => {
        // 验证和清理 progressData
        let cleanedMessage = { ...message }
        if (message.type === 'progress' && message.progressData) {
          cleanedMessage.progressData = {
            stage: message.progressData.stage || 'processing',
            progress: message.progressData.progress || 0,
            message: message.progressData.message || message.content || '处理中...',
            details: message.progressData.details,
            // 保留 type 和 data 字段
            type: message.progressData.type,
            data: message.progressData.data,
          }
        }
        
        const newMessage: Message = {
          ...cleanedMessage,
          // 生成 id 和 timestamp
          id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
          timestamp: new Date(),
        }
        
        // 确保 state.messages 是数组
        const currentMessages = Array.isArray(state.messages) ? state.messages : []
        
        return {
          messages: normalizeReviewMessageOrder(insertMessageWithReviewGrouping(currentMessages, newMessage))
        }
      }),
      
      setIsTyping: (typing) => set({ isTyping: typing }),
      
      setCurrentJobId: (jobId) => set({ currentJobId: jobId }),
      
      setIsLoadingHistory: (loading) => set({ isLoadingHistory: loading }),  // 新增：实现设置加载历史消息状态
      
      setHistoryLoadError: (error) => set({ historyLoadError: error }),  // 新增：实现设置历史消息加载错误
      
      setIsNewSession: (isNew) => set({ isNewSession: isNew }),  // 新增：实现设置是否为新会话
      
      setIsCalculating: (calculating) => set({ isCalculating: calculating }),  // 新增：实现设置是否正在核算
      
      setIsStartingReview: (starting) => set({ isStartingReview: starting }),  // 新增：实现设置是否正在启动审核
      
      setIsRefreshing: (refreshing) => set({ isRefreshing: refreshing }),  // 新增：实现设置是否正在刷新审核数据
      
      setReviewStarted: (started) => set({ reviewStarted: started }),  // 新增：实现设置审核是否已启动完成
      
      setIsReprocessing: (reprocessing) => set({ isReprocessing: reprocessing }),  // 新增：实现设置是否正在重新处理
      
      setIsWaitingForReply: (waiting) => set({ isWaitingForReply: waiting }),  // 新增：实现设置是否正在等待AI回复
      
      updateJob: (jobId, updates) => set((state) => ({
        jobs: state.jobs.map(job => 
          job.id === jobId ? { ...job, ...updates, updatedAt: new Date() } : job
        )
      })),
      
      addJob: (job) => set((state) => {
        // 检查是否已存在相同ID的任务，避免重复添加
        const existingJob = state.jobs.find(j => j.id === job.id)
        if (existingJob) {
          return state // 如果已存在，不添加
        }
        return {
          jobs: [job, ...state.jobs]
        }
      }),
      
      deleteJob: (jobId) => set((state) => ({
        jobs: state.jobs.filter(job => job.id !== jobId)
      })),
      
      setSessions: (sessions, total, offset) => set({
        sessions,
        sessionsTotal: total,
        sessionsOffset: offset,
        hasMoreSessions: sessions.length + offset < total,
      }),
      
      addSessions: (newSessions, total, offset) => set((state) => ({
        sessions: [...state.sessions, ...newSessions],
        sessionsTotal: total,
        sessionsOffset: offset,
        hasMoreSessions: state.sessions.length + newSessions.length + offset < total,
      })),
      
      setSessionsLoading: (loading) => set({ sessionsLoading: loading }),
      
      deleteSession: (sessionId) => {
        
        set((state) => {
          const newSessions = state.sessions.filter(session => session.session_id !== sessionId)
          
          return {
            sessions: [...newSessions], // 确保创建新数组
            sessionsTotal: Math.max(0, state.sessionsTotal - 1),
          }
        })
      },
      
      updateSession: (sessionId, updates) => set((state) => ({
        sessions: state.sessions.map(session =>
          session.session_id === sessionId ? { ...session, ...updates } : session
        ),
      })),
      
      addInteractionCard: (card) => set((state) => ({
        interactionCards: [...state.interactionCards, card]
      })),
      
      removeInteractionCard: (cardId) => set((state) => ({
        interactionCards: state.interactionCards.filter(card => card.id !== cardId)
      })),
      
      setWsConnected: (connected) => set({ wsConnected: connected }),
      
      clearMessages: () => set({ messages: [] }),
      
      resetUploadState: () => {
        // 触发自定义事件，通知FileUpload组件重置状态
        window.dispatchEvent(new CustomEvent('resetUploadState'))
      },
      
      cancelLoadingHistory: () => {
        // 取消正在进行的历史加载
        // 通过清除 loadingSessionId，使得正在进行的请求在完成时会被忽略
        const currentLoadingSessionId = get().loadingSessionId
        if (currentLoadingSessionId) {
          // console.log('🚫 取消历史加载请求:', currentLoadingSessionId)
        }
        set({ loadingSessionId: null, isLoadingHistory: false, historyLoadError: null })
      },
      
      setMessages: (messagesOrUpdater) => {
        if (typeof messagesOrUpdater === 'function') {
          // 支持函数式更新
          set((state) => {
            const currentMessages = Array.isArray(state.messages) ? state.messages : [];
            const newMessages = messagesOrUpdater(currentMessages);
            // console.log('🔧 setMessages 函数式更新:', {
            //   prevCount: currentMessages.length,
            //   newCount: Array.isArray(newMessages) ? newMessages.length : 'NOT_ARRAY'
            // });
            return { messages: Array.isArray(newMessages) ? newMessages : [] };
          });
        } else {
          // 直接设置
          // console.log('🔧 setMessages 直接设置:', {
          //   newMessagesCount: Array.isArray(messagesOrUpdater) ? messagesOrUpdater.length : 'NOT_ARRAY',
          //   newMessagesType: typeof messagesOrUpdater
          // });
          set({ messages: Array.isArray(messagesOrUpdater) ? messagesOrUpdater : [] });
        }
      },
      
      loadHistoryMessages: async (sessionId) => {
        // 检查是否已经在加载这个会话
        const currentLoadingSessionId = get().loadingSessionId
        if (currentLoadingSessionId === sessionId) {
          return
        }
        
        // 如果正在加载其他会话，记录日志但继续（新请求会覆盖旧请求）
        if (currentLoadingSessionId) {
          // console.log('⚠️ 取消之前的加载请求:', currentLoadingSessionId, '开始加载新会话:', sessionId)
        }
        
        // 标记当前正在加载的会话ID
        set({ loadingSessionId: sessionId })
        
        try {
          // 设置加载状态，同时清除打字状态和错误信息
          set({ isLoadingHistory: true, isTyping: false, historyLoadError: null })
          
          const { historyService } = await import('../services/historyService')
          // 使用新的 getAllChatHistory 方法获取所有历史消息
          const historyData = await historyService.getAllChatHistory(sessionId)
          
          // 请求完成后，检查当前正在加载的会话ID是否仍然是这个会话
          // 如果不是，说明用户已经切换到其他会话，忽略这个响应
          const latestLoadingSessionId = get().loadingSessionId
          if (latestLoadingSessionId !== sessionId) {
            return
          }
          
          // 转换历史消息格式
          const convertedMessages = historyService.convertToAppMessages(historyData.messages)
          
          // 设置jobId为当前会话的job_id
          const messagesWithJobId = convertedMessages.map(msg => ({
            ...msg,
            jobId: historyData.session_info.job_id,
          }))
          
          // 获取任务详情（包含上传的文件信息）并添加到消息列表最前面
          if (historyData.session_info.job_id) {
            try {
              const { chatService } = await import('../services/chatService')
              const jobDetailResponse = await chatService.getJobDetail(historyData.session_info.job_id)
              
              if (jobDetailResponse.success && jobDetailResponse.data) {
                const jobData = jobDetailResponse.data
                const attachments: any[] = []
                
                // 添加DWG文件
                if (jobData.dwg_file_name) {
                  attachments.push({
                    id: `dwg-${historyData.session_info.job_id}`,
                    name: jobData.dwg_file_name,
                    size: jobData.dwg_file_size || 0,
                    type: 'application/dwg',
                  })
                }
                
                // 添加PRT文件
                if (jobData.prt_file_name) {
                  attachments.push({
                    id: `prt-${historyData.session_info.job_id}`,
                    name: jobData.prt_file_name,
                    size: jobData.prt_file_size || 0,
                    type: 'application/prt',
                  })
                }
                
                // 如果有文件，在消息列表最前面添加一条用户消息显示文件
                if (attachments.length > 0) {
                  const fileMessage = {
                    id: `file-msg-${historyData.session_info.job_id}`,
                    type: 'user' as const,
                    content: '', // 空内容，只显示附件
                    timestamp: new Date(historyData.session_info.created_at || Date.now()),
                    jobId: historyData.session_info.job_id,
                    attachments: attachments,
                  }
                  
                  // 将文件消息添加到最前面
                  messagesWithJobId.unshift(fileMessage)
                }
              }
            } catch (error) {
              console.error('❌ 获取任务详情失败:', error)
              // 即使获取失败也继续流程
            }
          }
          
          // 再次检查会话ID（防止在转换消息期间切换了会话）
          if (get().loadingSessionId !== sessionId) {
            return
          }
          
          // 更新消息列表（确保审核表格、缺失字段卡片和等待确认提示按同一审核块恢复）
          const normalizedMessages = Array.isArray(messagesWithJobId)
            ? normalizeReviewMessageOrder(messagesWithJobId)
            : []

          set({ messages: normalizedMessages })
          
          // 如果有session_info，更新当前jobId并创建/更新job数据
          if (historyData.session_info.job_id) {
            set({ currentJobId: historyData.session_info.job_id })
            
            // 检查jobs数组中是否已存在该job
            const state = get()
            const existingJob = state.jobs.find(j => j.id === historyData.session_info.job_id)
            
            // 从metadata中获取name，或者从sessions中查找
            const sessionName = historyData.session_info.metadata?.name || 
                               state.sessions.find(s => s.job_id === historyData.session_info.job_id)?.name
            
            if (!existingJob) {
              // 如果不存在，创建一个新的job对象
              const newJob: Job = {
                id: historyData.session_info.job_id,
                title: sessionName || undefined,
                status: 'completed', // 历史会话默认为已完成状态
                stage: 'completed',
                progress: 100,
                createdAt: new Date(historyData.session_info.created_at || Date.now()),
                updatedAt: new Date(historyData.session_info.updated_at || Date.now()),
              }
              
              // 添加到jobs数组
              set((state) => ({
                jobs: [newJob, ...state.jobs]
              }))
            } else {
              // 如果存在，更新title（如果有的话）
              if (sessionName && existingJob.title !== sessionName) {
                set((state) => ({
                  jobs: state.jobs.map(job => 
                    job.id === historyData.session_info.job_id 
                      ? { ...job, title: sessionName }
                      : job
                  )
                }))
              }
            }
          }
          
          // 注释掉：不在加载历史消息后启动审核流程
          // 审核流程应该由 FileUpload 组件在特征识别完成后启动
          // 避免重复调用 /review/start 接口
          /*
          // 加载历史消息成功后，启动审核流程
          if (historyData.session_info.job_id) {
            try {
              console.log('📥 历史消息加载完成，启动审核流程:', historyData.session_info.job_id);
              const { chatService } = await import('../services/chatService')
              await chatService.startReview(historyData.session_info.job_id)
              console.log('✅ 审核流程启动成功');
            } catch (reviewError) {
              console.error('❌ 启动审核流程失败:', reviewError);
              // 不阻断历史消息加载，只是记录错误
            }
          }
          */
        } catch (error) {
          console.error('❌ 加载历史消息失败:', error)
          
          // 检查是否仍然是当前会话（防止错误信息显示给错误的会话）
          if (get().loadingSessionId !== sessionId) {
            return
          }
          
          // 保存错误信息
          const errorMessage = error instanceof Error ? error.message : '加载历史消息失败，请重试'
          set({ historyLoadError: errorMessage })
          
          // 加载失败时，清空消息列表（确保是数组）
          set({ messages: [] })
        } finally {
          // 只有当前加载的会话ID仍然是这个会话时，才清除加载状态
          if (get().loadingSessionId === sessionId) {
            set({ isLoadingHistory: false, loadingSessionId: null })
          }
        }
      },
    }),
    {
      name: 'mold-cost-app-store',
    }
  )
)

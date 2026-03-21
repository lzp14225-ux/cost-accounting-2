import { useState, useEffect, useCallback, useRef } from 'react'
import { 
  websocketService, 
  WebSocketMessage, 
  ProgressData, 
  InteractionCard, 
  ConnectionStatus,
  WebSocketCallbacks,
  HeartbeatConfig,
  ConnectionStats
} from '../services/websocketService'
import { interactionService } from '../services/interactionService'

export interface UseWebSocketOptions {
  autoConnect?: boolean
  heartbeatConfig?: Partial<HeartbeatConfig>
  onConnected?: (jobId: string) => void
  onProgress?: (jobId: string, data: ProgressData) => void
  onNeedUserInput?: (jobId: string, card: InteractionCard) => void
  onInteractionResponseReceived?: (jobId: string, message: string) => void
  onError?: (jobId: string, error: string) => void
  onHeartbeat?: (stats: ConnectionStats) => void
  onConnectionQuality?: (quality: 'good' | 'poor' | 'bad') => void
  onHistoryLoaded?: (messages: WebSocketMessage[]) => void
  onReviewData?: (jobId: string, data: any) => void
  onModificationConfirmation?: (jobId: string, data: any) => void
  onReviewCompleted?: (jobId: string, data: any) => void
  onCompletionRequest?: (jobId: string, data: any) => void
}

export interface UseWebSocketReturn {
  // 连接状态
  status: ConnectionStatus
  isConnected: boolean
  
  // 消息数据
  messages: WebSocketMessage[]
  latestMessage: WebSocketMessage | null
  progressData: ProgressData | null
  currentInteractionCard: InteractionCard | null
  
  // 心跳和统计
  connectionStats: ConnectionStats | null
  connectionQuality: 'good' | 'poor' | 'bad' | null
  
  // 操作方法
  connect: (jobId: string, fromHistorySwitch?: boolean) => Promise<void>
  disconnect: () => void
  sendMessage: (message: any) => void
  submitUserInput: (cardId: string, action: string, inputs: Record<string, any>) => Promise<void>
  
  // 心跳控制
  updateHeartbeatConfig: (config: Partial<HeartbeatConfig>) => void
  getHeartbeatConfig: () => HeartbeatConfig
  
  // 工具方法
  clearMessages: () => void
  getMessageHistory: () => Promise<void>
}

export const useWebSocket = (
  initialJobId?: string, 
  options: UseWebSocketOptions = {}
): UseWebSocketReturn => {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [messages, setMessages] = useState<WebSocketMessage[]>([])
  const [latestMessage, setLatestMessage] = useState<WebSocketMessage | null>(null)
  const [progressData, setProgressData] = useState<ProgressData | null>(null)
  const [currentInteractionCard, setCurrentInteractionCard] = useState<InteractionCard | null>(null)
  const [connectionStats, setConnectionStats] = useState<ConnectionStats | null>(null)
  const [connectionQuality, setConnectionQuality] = useState<'good' | 'poor' | 'bad' | null>(null)
  
  const jobIdRef = useRef<string | null>(initialJobId || null)
  const optionsRef = useRef(options)
  
  // 更新选项引用
  useEffect(() => {
    optionsRef.current = options
  }, [options])

  // WebSocket回调处理
  const callbacks: WebSocketCallbacks = {
    onStatusChange: (newStatus) => {
      // console.log('WebSocket状态变更:', newStatus)
      setStatus(newStatus)
    },
    
    onMessage: (message) => {
      setMessages(prev => [...prev, message])
      setLatestMessage(message)
    },
    
    onHistoryLoaded: (historyMessages) => {
      setMessages(historyMessages)
      if (historyMessages.length > 0) {
        setLatestMessage(historyMessages[historyMessages.length - 1])
      }
      optionsRef.current.onHistoryLoaded?.(historyMessages)
    },
    
    onConnected: (jobId) => {
      // console.log('WebSocket已连接:', jobId)
      optionsRef.current.onConnected?.(jobId)
    },
    
    onProgress: (jobId, data) => {
      // console.log('收到进度更新:', jobId, data)
      setProgressData(data)
      optionsRef.current.onProgress?.(jobId, data)
    },
    
    onNeedUserInput: (jobId, card) => {
      console.log('需要用户输入:', jobId, card)
      setCurrentInteractionCard(card)
      optionsRef.current.onNeedUserInput?.(jobId, card)
    },
    
    onInteractionResponseReceived: (jobId, message) => {
      console.log('交互响应已接收:', jobId, message)
      setCurrentInteractionCard(null) // 清除当前交互卡片
      optionsRef.current.onInteractionResponseReceived?.(jobId, message)
    },
    
    onReviewData: (jobId, data) => {
      console.log('收到审核数据:', jobId, data)
      optionsRef.current.onReviewData?.(jobId, data)
    },
    
    onModificationConfirmation: (jobId, data) => {
      console.log('收到修改确认请求:', jobId, data)
      optionsRef.current.onModificationConfirmation?.(jobId, data)
    },
    
    onReviewCompleted: (jobId, data) => {
      console.log('审核已完成:', jobId, data)
      optionsRef.current.onReviewCompleted?.(jobId, data)
    },
    
    onCompletionRequest: (jobId, data) => {
      console.log('收到补全请求（缺失字段）:', jobId, data)
      optionsRef.current.onCompletionRequest?.(jobId, data)
    },
    
    onError: (jobId, error) => {
      console.error('WebSocket错误:', jobId, error)
      optionsRef.current.onError?.(jobId, error)
    },
    
    onHeartbeat: (stats) => {
      setConnectionStats(stats)
      optionsRef.current.onHeartbeat?.(stats)
    },
    
    onConnectionQuality: (quality) => {
      setConnectionQuality(quality)
      optionsRef.current.onConnectionQuality?.(quality)
    },
  }

  // 连接WebSocket
  const connect = useCallback(async (jobId: string, fromHistorySwitch: boolean = false) => {
    try {
      jobIdRef.current = jobId
      console.log('开始连接WebSocket:', jobId, fromHistorySwitch ? '(从历史会话切换)' : '')
      
      // WebSocket服务会自动获取历史消息
      await websocketService.connect(jobId, callbacks, options.heartbeatConfig, fromHistorySwitch)
    } catch (error) {
      console.error('WebSocket连接失败:', error)
      throw error
    }
  }, [])

  // 断开连接
  const disconnect = useCallback(() => {
    websocketService.disconnect()
    jobIdRef.current = null
    setMessages([])
    setLatestMessage(null)
    setProgressData(null)
    setCurrentInteractionCard(null)
    setConnectionStats(null)
    setConnectionQuality(null)
  }, [])

  // 发送消息
  const sendMessage = useCallback((message: any) => {
    websocketService.send(message)
  }, [])

  // 提交用户输入
  const submitUserInput = useCallback(async (
    cardId: string, 
    action: string, 
    inputs: Record<string, any>
  ) => {
    if (!jobIdRef.current) {
      throw new Error('没有活跃的任务ID')
    }

    try {
      console.log('提交用户输入:', { cardId, action, inputs })
      
      await interactionService.submitUserInput(jobIdRef.current, {
        card_id: cardId,
        action,
        inputs,
      })
      
      console.log('用户输入提交成功')
    } catch (error) {
      console.error('提交用户输入失败:', error)
      throw error
    }
  }, [])

  // 更新心跳配置
  const updateHeartbeatConfig = useCallback((config: Partial<HeartbeatConfig>) => {
    websocketService.updateHeartbeatConfig(config)
  }, [])

  // 获取心跳配置
  const getHeartbeatConfig = useCallback(() => {
    return websocketService.getHeartbeatConfig()
  }, [])

  // 清除消息
  const clearMessages = useCallback(() => {
    setMessages([])
    setLatestMessage(null)
    setProgressData(null)
    setCurrentInteractionCard(null)
    setConnectionStats(null)
    setConnectionQuality(null)
  }, [])

  // 获取消息历史
  const getMessageHistory = useCallback(async () => {
    if (!jobIdRef.current) {
      console.warn('没有活跃的任务ID，无法获取消息历史')
      return
    }

    try {
      const result = await interactionService.getMessageHistory(jobIdRef.current)
      setMessages(result.messages)
      console.log('消息历史加载完成:', result.count, '条')
    } catch (error) {
      console.error('获取消息历史失败:', error)
    }
  }, [])

  // 自动连接
  useEffect(() => {
    if (options.autoConnect && initialJobId) {
      connect(initialJobId).catch(error => {
        console.error('自动连接失败:', error)
      })
    }

    // 组件卸载时断开连接
    return () => {
      if (websocketService.isConnected()) {
        disconnect()
      }
    }
  }, [initialJobId, options.autoConnect, connect, disconnect])

  // 更新状态
  useEffect(() => {
    setStatus(websocketService.getStatus())
  }, [])

  return {
    // 连接状态
    status,
    isConnected: status === 'connected',
    
    // 消息数据
    messages,
    latestMessage,
    progressData,
    currentInteractionCard,
    
    // 心跳和统计
    connectionStats,
    connectionQuality,
    
    // 操作方法
    connect,
    disconnect,
    sendMessage,
    submitUserInput,
    
    // 心跳控制
    updateHeartbeatConfig,
    getHeartbeatConfig,
    
    // 工具方法
    clearMessages,
    getMessageHistory,
  }
}
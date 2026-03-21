import config from '../config/env'
import { historyService } from './historyService'

// WebSocket消息类型定义
export interface WebSocketMessage {
  type: 'connected' | 'progress' | 'need_user_input' | 'interaction_response_received' | 'error' | 'pong' | 'review_data' | 'modification_confirmation' | 'review_completed' | 'review_display_view' | 'completion_request'
  job_id?: string
  message?: string
  error?: string
  data?: any
}

// 进度消息数据结构
export interface ProgressData {
  stage: string
  progress: number
  message: string
  details?: Record<string, any>
}

// 交互卡片数据结构
export interface InteractionCard {
  id: string
  type: 'input' | 'select' | 'confirm'
  title: string
  description?: string
  fields?: Array<{
    name: string
    label: string
    type: 'text' | 'number' | 'select' | 'checkbox'
    required?: boolean
    options?: Array<{ label: string; value: any }>
    defaultValue?: any
  }>
  actions?: Array<{
    label: string
    action: string
    type?: 'primary' | 'default' | 'danger'
  }>
}

// WebSocket连接状态
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error' | 'reconnecting'

// 心跳配置
export interface HeartbeatConfig {
  interval: number // 心跳间隔（毫秒）
  timeout: number // 心跳超时时间（毫秒）
  maxMissed: number // 最大允许丢失的心跳次数
  enabled: boolean // 是否启用心跳
}

// 连接统计信息
export interface ConnectionStats {
  connectTime: number // 连接时间戳
  totalMessages: number // 总消息数
  heartbeatsSent: number // 发送的心跳数
  heartbeatsReceived: number // 接收的心跳数
  missedHeartbeats: number // 丢失的心跳数
  reconnectCount: number // 重连次数
  lastHeartbeatTime: number // 最后心跳时间
  latency: number // 延迟（毫秒）
}

// WebSocket事件回调类型
export interface WebSocketCallbacks {
  onConnected?: (jobId: string) => void
  onProgress?: (jobId: string, data: ProgressData) => void
  onNeedUserInput?: (jobId: string, card: InteractionCard) => void
  onInteractionResponseReceived?: (jobId: string, message: string) => void
  onError?: (jobId: string, error: string) => void
  onStatusChange?: (status: ConnectionStatus) => void
  onMessage?: (message: WebSocketMessage) => void
  onHeartbeat?: (stats: ConnectionStats) => void // 心跳统计回调
  onConnectionQuality?: (quality: 'good' | 'poor' | 'bad') => void // 连接质量回调
  onHistoryLoaded?: (messages: WebSocketMessage[]) => void // 历史消息加载回调
  onReviewData?: (jobId: string, data: any) => void // 审核数据回调
  onModificationConfirmation?: (jobId: string, data: any) => void // 修改确认回调
  onReviewCompleted?: (jobId: string, data: any) => void // 审核完成回调
  onCompletionRequest?: (jobId: string, data: any) => void // 补全请求回调（缺失字段）
}

export class WebSocketService {
  private ws: WebSocket | null = null
  private jobId: string | null = null
  private callbacks: WebSocketCallbacks = {}
  private status: ConnectionStatus = 'disconnected'
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private heartbeatInterval: NodeJS.Timeout | null = null
  private heartbeatTimeout: NodeJS.Timeout | null = null
  private qualityCheckInterval: NodeJS.Timeout | null = null
  private connectingJobId: string | null = null // 记录正在连接的jobId，防止重复连接
  
  // 心跳配置
  private heartbeatConfig: HeartbeatConfig = {
    interval: 30000, // 30秒
    timeout: 10000, // 10秒超时
    maxMissed: 3, // 最多丢失3次心跳
    enabled: true
  }
  
  // 连接统计
  private stats: ConnectionStats = {
    connectTime: 0,
    totalMessages: 0,
    heartbeatsSent: 0,
    heartbeatsReceived: 0,
    missedHeartbeats: 0,
    reconnectCount: 0,
    lastHeartbeatTime: 0,
    latency: 0
  }
  
  // 心跳发送时间记录
  private heartbeatSendTimes: Map<number, number> = new Map()
  private heartbeatSequence = 0

  constructor() {
    this.handleMessage = this.handleMessage.bind(this)
    this.handleOpen = this.handleOpen.bind(this)
    this.handleClose = this.handleClose.bind(this)
    this.handleError = this.handleError.bind(this)
  }

  /**
   * 连接WebSocket
   * @param jobId 任务ID
   * @param callbacks 回调函数
   * @param heartbeatConfig 心跳配置
   * @param fromHistorySwitch 是否从历史会话列表切换（true时使用新的GET接口）
   */
  connect(jobId: string, callbacks: WebSocketCallbacks = {}, heartbeatConfig?: Partial<HeartbeatConfig>, fromHistorySwitch: boolean = false): Promise<void> {
    return new Promise(async (resolve, reject) => {
      try {
        // 防止重复连接同一个jobId
        if (this.connectingJobId === jobId) {
          reject(new Error('已有相同jobId的连接正在进行中'))
          return
        }

        this.connectingJobId = jobId
        this.jobId = jobId
        this.callbacks = callbacks
        
        // 更新心跳配置
        if (heartbeatConfig) {
          this.heartbeatConfig = { ...this.heartbeatConfig, ...heartbeatConfig }
        }
        
        // 重置统计信息
        this.resetStats()
        this.setStatus('connecting')

        // 先获取历史消息
        try {
          if (fromHistorySwitch) {
            // 从历史会话列表切换时，使用新的 GET 接口
            const historyData = await historyService.getChatHistory(jobId, { limit: 100 })
            
            // 将历史消息转换为 WebSocket 消息格式
            const messages: WebSocketMessage[] = historyData.messages.map(msg => ({
              type: 'progress' as const,
              job_id: jobId,
              message: msg.content,
              data: msg.metadata,
            }))
            
            // 通过回调传递历史消息
            if (messages.length > 0 && this.callbacks.onHistoryLoaded) {
              this.callbacks.onHistoryLoaded(messages)
            }
          } else {
            // 新上传文件或断开重连时，使用旧的 WebSocket 接口
            const history = await fetch(`${config.API_BASE_URL}/ws/${jobId}/history`)
            const data = await history.json()
            const messages = data.messages || []
            
            // 通过回调传递历史消息
            if (messages.length > 0 && this.callbacks.onHistoryLoaded) {
              this.callbacks.onHistoryLoaded(messages)
            }
          }
        } catch (error) {
          console.error('❌ 获取历史消息失败:', error)
          // 历史消息获取失败不阻止连接
        }

        // 构建WebSocket URL
        const wsUrl = `${config.WS_URL}/${jobId}`

        this.ws = new WebSocket(wsUrl)
        this.ws.onopen = () => {
          this.handleOpen()
          this.connectingJobId = null // 连接成功，清除标记
          resolve()
        }
        this.ws.onmessage = this.handleMessage
        this.ws.onclose = this.handleClose
        this.ws.onerror = (error) => {
          this.handleError(error)
          this.connectingJobId = null // 连接失败，清除标记
          reject(error)
        }
      } catch (error) {
        console.error('WebSocket连接失败:', error)
        this.setStatus('error')
        this.connectingJobId = null // 连接失败，清除标记
        reject(error)
      }
    })
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    this.stopHeartbeat()
    this.stopQualityCheck()
    this.connectingJobId = null // 清除连接标记
    
    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onclose = null
      this.ws.onerror = null
      this.ws.close()
      this.ws = null
    }
    
    this.setStatus('disconnected')
    this.jobId = null
    this.callbacks = {}
    this.reconnectAttempts = 0
    this.resetStats()
  }

  /**
   * 发送消息
   */
  send(message: any): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const messageStr = typeof message === 'string' ? message : JSON.stringify(message)
      this.ws.send(messageStr)
    } else {
      console.warn('WebSocket未连接，无法发送消息:', message)
    }
  }

  /**
   * 发送心跳
   */
  sendHeartbeat(): void {
    if (!this.heartbeatConfig.enabled) return
    
    const sequence = ++this.heartbeatSequence
    const timestamp = Date.now()
    
    // 记录发送时间用于计算延迟
    this.heartbeatSendTimes.set(sequence, timestamp)
    
    // 发送带序列号的心跳
    this.send(JSON.stringify({
      type: 'ping',
      sequence,
      timestamp
    }))
    
    this.stats.heartbeatsSent++
    this.stats.lastHeartbeatTime = timestamp
  }

  /**
   * 获取连接统计信息
   */
  getStats(): ConnectionStats {
    return { ...this.stats }
  }

  /**
   * 获取心跳配置
   */
  getHeartbeatConfig(): HeartbeatConfig {
    return { ...this.heartbeatConfig }
  }

  /**
   * 更新心跳配置
   */
  updateHeartbeatConfig(config: Partial<HeartbeatConfig>): void {
    this.heartbeatConfig = { ...this.heartbeatConfig, ...config }
    
    // 如果连接中，重启心跳
    if (this.isConnected()) {
      this.stopHeartbeat()
      if (this.heartbeatConfig.enabled) {
        this.startHeartbeat()
      }
    }
  }

  /**
   * 重置统计信息
   */
  private resetStats(): void {
    this.stats = {
      connectTime: Date.now(),
      totalMessages: 0,
      heartbeatsSent: 0,
      heartbeatsReceived: 0,
      missedHeartbeats: 0,
      reconnectCount: this.stats.reconnectCount, // 保留重连次数
      lastHeartbeatTime: 0,
      latency: 0
    }
    this.heartbeatSendTimes.clear()
    this.heartbeatSequence = 0
  }

  /**
   * 获取连接状态
   */
  getStatus(): ConnectionStatus {
    return this.status
  }

  /**
   * 是否已连接
   */
  isConnected(): boolean {
    return this.status === 'connected' && this.ws?.readyState === WebSocket.OPEN
  }

  /**
   * 处理连接打开
   */
  private handleOpen(): void {
    // console.log('WebSocket连接已建立')
    this.setStatus('connected')
    this.reconnectAttempts = 0
    this.startHeartbeat()
  }

  /**
   * 处理消息接收
   */
  private handleMessage(event: MessageEvent): void {
    try {
      this.stats.totalMessages++
      
      // 处理心跳响应
      if (event.data === 'pong') {
        this.handleHeartbeatResponse()
        return
      }

      // 尝试解析JSON消息
      let message: any
      try {
        message = JSON.parse(event.data)
      } catch {
        // 如果不是JSON，可能是简单的pong响应
        if (event.data === 'pong') {
          this.handleHeartbeatResponse()
          return
        }
        console.warn('无法解析的消息格式:', event.data)
        return
      }

      // 处理带序列号的pong响应
      if (message.type === 'pong' && message.sequence) {
        this.handleHeartbeatResponse(message.sequence, message.timestamp)
        return
      }
      
      // 调用通用消息回调
      this.callbacks.onMessage?.(message as WebSocketMessage)

      // 根据消息类型调用特定回调
      switch (message.type) {
        case 'connected':
          this.callbacks.onConnected?.(message.job_id!)
          break
          
        case 'progress':
          this.callbacks.onProgress?.(message.job_id!, message.data as ProgressData)
          break
          
        case 'review_display_view':
          // 将 review_display_view 消息转换为 progress 消息处理
          this.callbacks.onProgress?.(message.job_id!, {
            stage: 'review_display_view',
            progress: 50,
            message: '特征识别完成，请检查结果并确认',
            type: 'review_display_view',
            data: message.data,
          } as any)
          break
          
        case 'completion_request':
          // 处理缺失字段补全请求
          // console.log('⚠️ 收到 completion_request 消息（缺失字段）')
          this.callbacks.onCompletionRequest?.(message.job_id!, message.data)
          break
          
        case 'need_user_input':
          this.callbacks.onNeedUserInput?.(message.job_id!, message.data as InteractionCard)
          break
          
        case 'interaction_response_received':
          this.callbacks.onInteractionResponseReceived?.(message.job_id!, message.message!)
          break
          
        case 'review_data':
          this.callbacks.onReviewData?.(message.job_id!, message.data)
          break
          
        case 'modification_confirmation':
          this.callbacks.onModificationConfirmation?.(message.job_id!, message.data)
          break
          
        case 'review_completed':
          this.callbacks.onReviewCompleted?.(message.job_id!, message.data)
          break
          
        case 'error':
          this.callbacks.onError?.(message.job_id!, message.error!)
          break
          
        case 'pong':
          this.handleHeartbeatResponse(message.sequence, message.timestamp)
          break
          
        default:
          console.warn('未知的消息类型:', message.type)
      }
    } catch (error) {
      console.error('解析WebSocket消息失败:', error, event.data)
    }
  }

  /**
   * 处理连接关闭
   */
  private handleClose(event: CloseEvent): void {
    // console.log('WebSocket连接已关闭:', event.code, event.reason)
    this.stopHeartbeat()
    this.stopQualityCheck()
    
    // 根据关闭代码设置状态
    if (event.code === 1000) {
      this.setStatus('disconnected') // 正常关闭
    } else {
      this.setStatus('error') // 异常关闭
    }

    // 如果不是主动关闭，尝试重连
    if (event.code !== 1000 && this.jobId && this.reconnectAttempts < this.maxReconnectAttempts) {
      this.setStatus('reconnecting')
      this.stats.reconnectCount++
      this.attemptReconnect()
    }
  }

  /**
   * 处理连接错误
   */
  private handleError(error: Event): void {
    console.error('WebSocket连接错误:', error)
    this.setStatus('error')
  }

  /**
   * 尝试重连
   */
  private attemptReconnect(): void {
    this.reconnectAttempts++
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1) // 指数退避
    
    setTimeout(() => {
      if (this.jobId) {
        this.connect(this.jobId, this.callbacks).catch(error => {
          console.error('重连失败:', error)
        })
      }
    }, delay)
  }

  /**
   * 设置连接状态
   */
  private setStatus(status: ConnectionStatus): void {
    if (this.status !== status) {
      this.status = status
      // console.log('WebSocket状态变更:', status)
      this.callbacks.onStatusChange?.(status)
    }
  }

  /**
   * 开始心跳
   */
  private startHeartbeat(): void {
    if (!this.heartbeatConfig.enabled) {
      // console.log('心跳检测已禁用')
      return
    }
    
    this.stopHeartbeat()
    
    // 定期发送心跳
    this.heartbeatInterval = setInterval(() => {
      if (this.isConnected()) {
        this.sendHeartbeat()
        
        // 设置心跳超时检测
        this.heartbeatTimeout = setTimeout(() => {
          this.stats.missedHeartbeats++
          console.warn(`心跳超时 #${this.heartbeatSequence}，丢失次数: ${this.stats.missedHeartbeats}`)
          
          // 检查是否超过最大丢失次数
          if (this.stats.missedHeartbeats >= this.heartbeatConfig.maxMissed) {
            console.error('心跳丢失过多，强制断开连接')
            this.ws?.close(4000, '心跳超时')
          }
        }, this.heartbeatConfig.timeout)
      }
    }, this.heartbeatConfig.interval)
    
    // 开始连接质量检测
    this.startQualityCheck()
  }

  /**
   * 停止心跳
   */
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }
    
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout)
      this.heartbeatTimeout = null
    }
  }

  /**
   * 处理心跳响应
   */
  private handleHeartbeatResponse(sequence?: number, serverTimestamp?: number): void {
    // 清除超时定时器
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout)
      this.heartbeatTimeout = null
    }
    
    this.stats.heartbeatsReceived++
    
    // 计算延迟
    if (sequence && this.heartbeatSendTimes.has(sequence)) {
      const sendTime = this.heartbeatSendTimes.get(sequence)!
      const now = Date.now()
      this.stats.latency = now - sendTime
      this.heartbeatSendTimes.delete(sequence)
    } else {
      // console.log('收到心跳响应')
    }
    
    // 重置丢失计数
    this.stats.missedHeartbeats = 0
    
    // 触发心跳回调
    this.callbacks.onHeartbeat?.(this.getStats())
  }

  /**
   * 开始连接质量检测
   */
  private startQualityCheck(): void {
    this.stopQualityCheck()
    
    // 每分钟检查一次连接质量
    this.qualityCheckInterval = setInterval(() => {
      this.checkConnectionQuality()
    }, 60000)
  }

  /**
   * 停止连接质量检测
   */
  private stopQualityCheck(): void {
    if (this.qualityCheckInterval) {
      clearInterval(this.qualityCheckInterval)
      this.qualityCheckInterval = null
    }
  }

  /**
   * 检查连接质量
   */
  private checkConnectionQuality(): void {
    const stats = this.getStats()
    let quality: 'good' | 'poor' | 'bad' = 'good'
    
    // 基于延迟判断
    if (stats.latency > 1000) {
      quality = 'bad'
    } else if (stats.latency > 500) {
      quality = 'poor'
    }
    
    // 基于丢失心跳判断
    if (stats.missedHeartbeats > 1) {
      quality = 'bad'
    } else if (stats.missedHeartbeats > 0) {
      quality = 'poor'
    }
    
    // 基于心跳成功率判断
    if (stats.heartbeatsSent > 0) {
      const successRate = stats.heartbeatsReceived / stats.heartbeatsSent
      if (successRate < 0.8) {
        quality = 'bad'
      } else if (successRate < 0.9) {
        quality = 'poor'
      }
    }
    
    // console.log('连接质量检查:', {
    //   quality,
    //   latency: stats.latency,
    //   missedHeartbeats: stats.missedHeartbeats,
    //   successRate: stats.heartbeatsSent > 0 ? (stats.heartbeatsReceived / stats.heartbeatsSent * 100).toFixed(1) + '%' : 'N/A'
    // })
    
    this.callbacks.onConnectionQuality?.(quality)
  }
}

// 创建全局WebSocket服务实例
export const websocketService = new WebSocketService()
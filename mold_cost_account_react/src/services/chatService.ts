import api from './api'
import { delay } from '../utils/mockData'
import { sseService, SSECallbacks, ChatMessage as SSEChatMessage } from './sseService'
import { reviewService } from './reviewService'
import config from '../config/env'
import axios from 'axios'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

export interface ChatMessage {
  content: string
  jobId?: string
  attachments?: string[]
}

export interface ChatResponse {
  message: string
  jobId?: string
  cards?: any[]
  progress?: {
    stage: string
    progress: number
    status: string
  }
}

export interface StreamChatCallbacks {
  onStart?: (messageId: string) => void
  onContent?: (delta: string) => void
  onComplete?: (fullMessage: string) => void
  onError?: (error: string) => void
}

export const chatService = {
  /**
   * 发送流式聊天消息（推荐使用）
   */
  async sendStreamMessage(
    content: string,
    jobId: string,
    history: SSEChatMessage[] = [],
    callbacks: StreamChatCallbacks
  ): Promise<void> {
    try {
      let fullMessage = ''

      const sseCallbacks: SSECallbacks = {
        onStart: (messageId) => {
          console.log('开始生成消息:', messageId)
          callbacks.onStart?.(messageId)
        },
        
        onContent: (delta) => {
          fullMessage += delta
          callbacks.onContent?.(delta)
        },
        
        onDone: (finishReason) => {
          console.log('消息生成完成:', finishReason)
          callbacks.onComplete?.(fullMessage)
        },
        
        onError: (error) => {
          console.error('流式聊天错误:', error)
          callbacks.onError?.(error)
        },
      }

      await sseService.streamChat({
        job_id: jobId,
        message: content,
        history,
        stream: true,
      }, sseCallbacks)

    } catch (error: any) {
      console.error('发送流式消息失败:', error)
      callbacks.onError?.(error.message || '发送消息失败')
      throw error
    }
  },

  /**
   * 取消流式聊天
   */
  cancelStream(): void {
    sseService.cancelStream()
  },

  /**
   * 检查是否正在流式聊天
   */
  isStreaming(): boolean {
    return sseService.isStreaming()
  },

  /**
   * 启动审核流程（CAD文件上传后调用）
   * 根据文档，直接调用 /review/start 接口，不需要先检查状态
   */
  async startReview(jobId: string): Promise<any> {
    try {
      // console.log('🚀 启动审核流程:', jobId)
      // console.trace('📍 startReview 调用栈:') // 添加调用栈追踪
      
      // 直接启动审核，不再先检查状态
      // 后端会处理重复启动的情况
      const result = await reviewService.startReview(jobId)

      return result
    } catch (error: any) {
      console.error('启动审核失败:', error)
      // 如果是 REVIEW_LOCKED 错误，说明已经在审核中
      if (error.message?.includes('REVIEW_LOCKED') || error.message?.includes('审核中')) {
        console.log('审核已在进行中，继续等待 WebSocket 推送')
        return // 不抛出错误，让流程继续
      }
      throw error
    }
  },

  /**
   * 提交修改指令
   */
  async submitModification(jobId: string, modificationText: string) {
    try {
      console.log('提交修改指令:', { jobId, modificationText })
      
      const result = await reviewService.submitModification(jobId, modificationText)
      console.log('修改指令提交成功:', result)

      return result
    } catch (error: any) {
      console.error('提交修改指令失败:', error)
      throw error
    }
  },

  /**
   * 确认修改
   */
  async confirmModification(jobId: string, comment?: string) {
    try {
      console.log('确认修改:', { jobId, comment })
      
      const result = await reviewService.confirmModification(jobId, comment)
      console.log('修改确认成功:', result)

      return result
    } catch (error: any) {
      console.error('确认修改失败:', error)
      throw error
    }
  },

  /**
   * 刷新审核数据
   */
  async refreshReview(jobId: string) {
    try {
      // console.trace('📍 refreshReview 调用栈:') // 添加调用栈追踪
      
      const result = await reviewService.refreshReview(jobId)

      return result
    } catch (error: any) {
      console.error('刷新审核数据失败:', error)
      throw error
    }
  },

  /**
   * 获取审核状态
   */
  async getReviewStatus(jobId: string) {
    try {
      const result = await reviewService.getReviewStatus(jobId)
      return result.data
    } catch (error: any) {
      console.error('获取审核状态失败:', error)
      throw error
    }
  },

  /**
   * 继续核算流程
   * POST /api/v1/jobs/{job_id}/continue
   * 注意：此接口使用独立的域名（从环境变量 VITE_CONTINUE_API_BASE_URL 读取）
   */
  async continueCalculation(jobId: string) {
    try {
      // 使用独立的 axios 实例调用 continue 接口
      const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
      const response = await axios.post(
        `${config.CONTINUE_API_URL}/jobs/${jobId}/continue`,
        {},
        {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': token ? `Bearer ${token}` : '',
            'X-Request-ID': Date.now().toString() + Math.random().toString(36).substring(2, 9)
          },
          timeout: 10000000
        }
      )
      
      return response.data
    } catch (error: any) {
      console.error('继续核算失败:', error)
      throw new Error(error.response?.data?.message || '继续核算失败')
    }
  },

  /**
   * 发送聊天消息（兼容旧版本，建议使用 sendStreamMessage）
   * @deprecated 请使用 sendStreamMessage 替代
   */
  async sendMessage(content: string, jobId?: string): Promise<ChatResponse> {
    try {
      // 模拟网络延迟
      await delay(1000 + Math.random() * 2000)

      // 模拟AI响应
      let response: ChatResponse

      if (content.includes('上传') || content.includes('文件')) {
        response = {
          message: '请点击左下角的📎按钮上传您的DWG或PRT文件，我将为您进行成本核算分析。',
          jobId,
        }
      } else if (content.includes('成本') || content.includes('价格')) {
        response = {
          message: '成本核算包括以下几个方面：\n\n1. **材料成本** - 根据材质和重量计算\n2. **加工成本** - 包括线割、NC加工、磨床等\n3. **热处理成本** - 根据热处理工艺计算\n4. **管理费用** - 通常为总成本的10-15%\n\n请上传CAD文件，我将为您提供详细的成本分析。',
          jobId,
        }
      } else if (content.includes('工艺') || content.includes('加工')) {
        response = {
          message: '我们支持多种加工工艺的成本计算：\n\n🔧 **线割加工**\n- 快丝线割\n- 中丝线割  \n- 慢丝线割\n\n⚙️ **NC加工**\n- 钻孔加工\n- 开粗加工\n- 精铣加工\n\n🔨 **其他工艺**\n- 磨床加工\n- 放电加工\n- 雕刻加工\n\n系统会根据您的CAD文件自动识别所需工艺并计算成本。',
          jobId,
        }
      } else {
        response = {
          message: '我理解您的问题。作为模具成本核算专家，我可以帮您：\n\n📄 **解析CAD文件** - 支持DWG、PRT格式\n🔍 **识别加工特征** - 自动识别线割、钻孔等特征\n⚙️ **制定加工工艺** - 智能推荐最优加工方案\n💰 **计算精确成本** - 提供详细的成本分解\n📊 **生成专业报表** - 输出Excel格式的核算清单\n\n请告诉我您需要什么帮助，或直接上传CAD文件开始分析。',
          jobId,
        }
      }

      return response

      // 实际API调用（注释掉用于演示）
      /*
      const response = await api.post('/chat/message', {
        content,
        jobId,
      })
      
      return response.data
      */
    } catch (error) {
      console.error('发送消息失败:', error)
      throw error
    }
  },

  /**
   * 提交交互响应
   */
  async submitInteraction(
    cardId: string, 
    action: string, 
    inputs: Record<string, any>
  ): Promise<void> {
    try {
      await api.post('/chat/interaction', {
        cardId,
        action,
        inputs,
      })
    } catch (error) {
      console.error('提交交互失败:', error)
      throw error
    }
  },

  /**
   * 获取聊天历史（已废弃，请使用 historyService.getChatHistory）
   * @deprecated 请使用 historyService.getChatHistory 替代
   */
  async getChatHistory(jobId?: string) {
    try {
      const response = await api.get('/chat/history', {
        params: { jobId },
      })
      
      return response.data
    } catch (error) {
      console.error('获取聊天历史失败:', error)
      throw error
    }
  },

  /**
   * 清除聊天历史
   */
  async clearChatHistory(jobId?: string): Promise<void> {
    try {
      await api.delete('/chat/history', {
        params: { jobId },
      })
    } catch (error) {
      console.error('清除聊天历史失败:', error)
      throw error
    }
  },

  /**
   * 获取API基础URL
   */
  getApiBaseUrl(): string {
    return config.API_BASE_URL
  },

  /**
   * 获取Continue API基础URL（核算服务）
   */
  getContinueApiBaseUrl(): string {
    return config.CONTINUE_API_BASE_URL
  },

  /**
   * 获取Continue API完整URL（核算服务，包含 /api/v1 前缀）
   */
  getContinueApiUrl(): string {
    return config.CONTINUE_API_URL
  },

  /**
   * 获取任务详情（包含上传的文件信息）
   * GET /api/jobs/{job_id}
   */
  async getJobDetail(jobId: string) {
    try {
      const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
      const response = await axios.get(
        `${config.AUTH_BASE_URL}/api/jobs/${jobId}`,
        {
          headers: {
            'Authorization': token ? `Bearer ${token}` : '',
          },
          timeout: 10000
        }
      )
      
      return response.data
    } catch (error: any) {
      console.error('获取任务详情失败:', error)
      throw new Error(error.response?.data?.message || '获取任务详情失败')
    }
  },
}
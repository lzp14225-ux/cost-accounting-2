import config from '../config/env'
import { getValidToken } from '../utils/auth'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SSEChatRequest {
  job_id: string
  message: string
  history: ChatMessage[]
  stream: boolean
}

export interface SSEResponse {
  type: 'start' | 'content' | 'done' | 'error'
  message_id?: string
  delta?: string
  finish_reason?: string
  message?: string
}

export interface SSECallbacks {
  onStart?: (messageId: string) => void
  onContent?: (delta: string) => void
  onDone?: (finishReason: string) => void
  onError?: (error: string) => void
}

class SSEService {
  private controller: AbortController | null = null

  /**
   * 发送流式聊天请求
   * POST /api/v1/chat/completions (SSE)
   */
  async streamChat(
    request: SSEChatRequest,
    callbacks: SSECallbacks
  ): Promise<void> {
    // 取消之前的请求
    if (this.controller) {
      this.controller.abort()
    }

    this.controller = new AbortController()
    const token = getValidToken()

    if (!token) {
      throw new Error('未找到有效的认证Token')
    }

    try {
      const response = await fetch(`${config.API_URL}/chat/completions`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(request),
        signal: this.controller.signal,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail?.message || `HTTP ${response.status}`)
      }

      if (!response.body) {
        throw new Error('响应体为空')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      try {
        while (true) {
          const { done, value } = await reader.read()

          if (done) {
            break
          }

          buffer += decoder.decode(value, { stream: true })

          // 处理SSE数据
          const lines = buffer.split('\n')
          buffer = lines.pop() || '' // 保留不完整的行

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data: SSEResponse = JSON.parse(line.slice(6))
                this.handleSSEMessage(data, callbacks)
              } catch (parseError) {
                console.error('解析SSE消息失败:', parseError, 'Line:', line)
              }
            }
          }
        }
      } finally {
        reader.releaseLock()
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        // console.log('SSE请求被取消')
        return
      }

      console.error('SSE流式聊天失败:', error)
      callbacks.onError?.(error.message || '流式聊天失败')
      throw error
    } finally {
      this.controller = null
    }
  }

  /**
   * 处理SSE消息
   */
  private handleSSEMessage(data: SSEResponse, callbacks: SSECallbacks): void {
    switch (data.type) {
      case 'start':
        if (data.message_id) {
          callbacks.onStart?.(data.message_id)
        }
        break

      case 'content':
        if (data.delta) {
          callbacks.onContent?.(data.delta)
        }
        break

      case 'done':
        callbacks.onDone?.(data.finish_reason || 'stop')
        break

      case 'error':
        callbacks.onError?.(data.message || '未知错误')
        break

      default:
        console.warn('未知的SSE消息类型:', data.type)
    }
  }

  /**
   * 取消当前的流式请求
   */
  cancelStream(): void {
    if (this.controller) {
      this.controller.abort()
      this.controller = null
    }
  }

  /**
   * 检查是否有活跃的流式请求
   */
  isStreaming(): boolean {
    return this.controller !== null
  }
}

export const sseService = new SSEService()
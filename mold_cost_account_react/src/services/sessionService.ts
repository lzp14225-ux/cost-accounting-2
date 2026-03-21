import axios from 'axios'
import config from '../config/env'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

export interface SessionItem {
  session_id: string
  job_id: string
  created_at: string
  updated_at: string
  status: 'active' | 'completed' | 'failed'
  metadata?: Record<string, any>
  name?: string | null  // 新增：会话名称
  user_id?: string  // 新增：用户ID
}

export interface SessionsResponse {
  user_id?: string  // 改为可选
  sessions: SessionItem[]
  total_count: number
}

export interface GetSessionsParams {
  limit?: number
  offset?: number
}

class SessionService {
  /**
   * 获取会话列表
   * 注意：此接口使用独立的域名（http://localhost:8000）
   */
  async getSessions(params: GetSessionsParams = {}): Promise<SessionsResponse> {
    const { limit = 5, offset = 0 } = params
    
    try {
      // 使用独立的 axios 实例调用获取会话列表接口
      const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
      const response = await axios.get(
        `${config.AUTH_BASE_URL}/api/chat-sessions/`,
        {
          params: {
            limit,
            offset,
          },
          headers: {
            'Content-Type': 'application/json',
            'Authorization': token ? `Bearer ${token}` : '',
          },
          timeout: 10000000
        }
      )
      
      // 适配新的返回格式
      const apiResponse = response.data
      if (apiResponse.success && apiResponse.data) {
        return {
          sessions: apiResponse.data.sessions || [],
          total_count: apiResponse.data.total || 0,
          user_id: apiResponse.data.sessions[0]?.user_id, // 从第一个会话中获取 user_id
        }
      }
      
      // 如果格式不符合预期，返回空数据
      return {
        sessions: [],
        total_count: 0,
      }
    } catch (error: any) {
      // 处理特定的错误响应
      if (error.response?.data?.detail) {
        const detail = error.response.data.detail
        if (detail === '无效的Token') {
          throw new Error('Token已失效，请重新登录')
        } else if (detail === 'Not authenticated') {
          throw new Error('未认证，请先登录')
        }
      }
      
      throw new Error(error.response?.data?.message || '获取会话列表失败')
    }
  }

  /**
   * 获取更多会话（分页）
   */
  async getMoreSessions(offset: number, limit: number = 50): Promise<SessionsResponse> {
    return this.getSessions({ limit, offset })
  }

  /**
   * 删除会话
   * 注意：此接口使用独立的域名（http://localhost:8000）
   */
  async deleteSession(jobId: string): Promise<void> {
    try {
      // 使用独立的 axios 实例调用删除接口
      const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
      const response = await axios.delete(
        `${config.AUTH_BASE_URL}/api/chat-sessions/delete-by-job`,
        {
          data: {
            job_id: jobId,
          },
          headers: {
            'Content-Type': 'application/json',
            'Authorization': token ? `Bearer ${token}` : '',
          },
          timeout: 10000000
        }
      )
      
      return response.data
    } catch (error: any) {
      throw new Error(error.response?.data?.message || '删除会话失败')
    }
  }

  /**
   * 重命名会话
   * 注意：此接口使用独立的域名（http://localhost:8000）
   */
  async renameSession(jobId: string, name: string): Promise<void> {
    try {
      // 使用独立的 axios 实例调用重命名接口
      const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
      const response = await axios.put(
        `${config.AUTH_BASE_URL}/api/chat-sessions/update-name`,
        {
          job_id: jobId,
          name: name,
        },
        {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': token ? `Bearer ${token}` : '',
          },
          timeout: 10000000
        }
      )
      
      return response.data
    } catch (error: any) {
      throw new Error(error.response?.data?.message || '重命名会话失败')
    }
  }

  /**
   * 批量删除会话
   * 注意：此接口使用独立的域名（http://localhost:8000）
   * @param jobIds - 要删除的 job_id 数组，最多支持 100 个
   */
  async batchDeleteSessions(jobIds: string[]): Promise<{
    success: boolean
    message: string
    data: {
      total: number
      success_count: number
      failed_count: number
      total_deleted: number
      elapsed_seconds: number
      results: Array<{
        job_id: string
        success: boolean
        message: string
        deleted_count: number
      }>
    }
  }> {
    try {
      // 验证 job_ids 数量
      if (jobIds.length === 0) {
        throw new Error('请至少选择一个会话')
      }
      if (jobIds.length > 100) {
        throw new Error('最多支持批量删除 100 个会话')
      }

      // 使用独立的 axios 实例调用批量删除接口
      const token = localStorage.getItem(AUTH_STORAGE_KEYS.TOKEN)
      const response = await axios.post(
        `${config.AUTH_BASE_URL}/api/chat-sessions/batch-delete-by-job`,
        {
          job_ids: jobIds,
        },
        {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': token ? `Bearer ${token}` : '',
          },
          timeout: 30000 // 批量删除可能需要更长时间
        }
      )
      
      return response.data
    } catch (error: any) {
      throw new Error(error.response?.data?.message || '批量删除会话失败')
    }
  }
}

export const sessionService = new SessionService()
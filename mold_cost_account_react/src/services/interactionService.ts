import { request } from '../utils/request'
import config from '../config/env'

// 用户输入数据结构
export interface UserInputData {
  card_id: string
  action: string
  inputs: Record<string, any>
}

// 交互记录
export interface InteractionRecord {
  id: string
  job_id: string
  card_id: string
  action: string
  inputs: Record<string, any>
  created_at: string
  status: 'pending' | 'completed' | 'failed'
}

// 任务状态
export interface JobStatus {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  stage: string
  progress: number
  message: string
  created_at: string
  updated_at: string
}

export const interactionService = {
  /**
   * 提交用户输入
   */
  async submitUserInput(jobId: string, inputData: UserInputData): Promise<void> {
    try {
      console.log('提交用户输入:', { jobId, inputData })
      
      const response = await request<{ message: string }>({
        url: `${config.API_URL}/jobs/${jobId}/submit`,
        method: 'POST',
        data: inputData,
      })
      
      console.log('用户输入提交成功:', response)
    } catch (error) {
      console.error('提交用户输入失败:', error)
      throw error
    }
  },

  /**
   * 获取交互记录
   */
  async getInteractions(jobId: string): Promise<InteractionRecord[]> {
    try {
      console.log('获取交互记录:', jobId)
      
      const response = await request<InteractionRecord[]>({
        url: `${config.API_URL}/jobs/${jobId}/interactions`,
        method: 'GET',
      })
      
      console.log('获取交互记录成功:', response)
      return response
    } catch (error) {
      console.error('获取交互记录失败:', error)
      throw error
    }
  },

  /**
   * 获取任务状态
   */
  async getJobStatus(jobId: string): Promise<JobStatus> {
    try {
      console.log('获取任务状态:', jobId)
      
      const response = await request<JobStatus>({
        url: `${config.API_URL}/jobs/${jobId}/status`,
        method: 'GET',
      })
      
      console.log('获取任务状态成功:', response)
      return response
    } catch (error) {
      console.error('获取任务状态失败:', error)
      throw error
    }
  },

  /**
   * 获取WebSocket消息历史
   */
  async getMessageHistory(jobId: string): Promise<{ messages: any[]; count: number }> {
    try {
      console.log('获取消息历史:', jobId)
      
      const response = await fetch(`${config.API_BASE_URL}/ws/${jobId}/history`)
      const data = await response.json()
      
      console.log('获取消息历史成功:', data)
      return {
        messages: data.messages || [],
        count: data.count || 0
      }
    } catch (error) {
      console.error('获取消息历史失败:', error)
      // 消息历史获取失败不应该阻止主流程
      return {
        messages: [],
        count: 0
      }
    }
  },

  /**
   * 检查WebSocket连接状态
   */
  async checkConnectionStatus(): Promise<{ active_connections: number; total_connections: number }> {
    try {
      const response = await request<{ active_connections: number; total_connections: number }>({
        url: `${config.WS_URL}/status`,
        method: 'GET',
      })
      
      console.log('WebSocket连接状态:', response)
      return response
    } catch (error) {
      console.error('检查WebSocket连接状态失败:', error)
      throw error
    }
  },

  /**
   * 健康检查
   */
  async healthCheck(): Promise<{ status: string; timestamp: string }> {
    try {
      const response = await request<{ status: string; timestamp: string }>({
        url: `${config.API_BASE_URL}/health`,
        method: 'GET',
      })
      
      console.log('健康检查结果:', response)
      return response
    } catch (error) {
      console.error('健康检查失败:', error)
      throw error
    }
  },
}
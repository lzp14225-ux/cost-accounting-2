import api from './api'
import { Job } from '../store/useAppStore'

export interface JobListResponse {
  jobs: Job[]
  total: number
  page: number
  pageSize: number
}

export interface JobDetailResponse extends Job {
  subgraphs?: any[]
  reports?: any[]
  interactions?: any[]
  logs?: any[]
}

export const jobService = {
  /**
   * 获取任务列表
   */
  async getJobs(params?: {
    page?: number
    pageSize?: number
    status?: string
    search?: string
    startDate?: string
    endDate?: string
  }): Promise<JobListResponse> {
    try {
      const response = await api.get('/jobs', { params })
      return response.data
    } catch (error) {
      console.error('获取任务列表失败:', error)
      throw error
    }
  },

  /**
   * 获取任务详情
   */
  async getJobDetail(jobId: string): Promise<JobDetailResponse> {
    try {
      const response = await api.get(`/jobs/${jobId}`)
      return response.data
    } catch (error) {
      console.error('获取任务详情失败:', error)
      throw error
    }
  },

  /**
   * 获取任务状态
   */
  async getJobStatus(jobId: string) {
    try {
      const response = await api.get(`/jobs/${jobId}/status`)
      return response.data
    } catch (error) {
      console.error('获取任务状态失败:', error)
      throw error
    }
  },

  /**
   * 重新处理任务
   */
  async retryJob(jobId: string): Promise<void> {
    try {
      await api.post(`/jobs/${jobId}/retry`)
    } catch (error) {
      console.error('重新处理任务失败:', error)
      throw error
    }
  },

  /**
   * 取消任务
   */
  async cancelJob(jobId: string): Promise<void> {
    try {
      await api.post(`/jobs/${jobId}/cancel`)
    } catch (error) {
      console.error('取消任务失败:', error)
      throw error
    }
  },

  /**
   * 归档任务
   */
  async archiveJob(jobId: string): Promise<void> {
    try {
      await api.post(`/jobs/${jobId}/archive`)
    } catch (error) {
      console.error('归档任务失败:', error)
      throw error
    }
  },

  /**
   * 删除任务
   */
  async deleteJob(jobId: string): Promise<void> {
    try {
      await api.delete(`/jobs/${jobId}`)
    } catch (error) {
      console.error('删除任务失败:', error)
      throw error
    }
  },

  /**
   * 下载报表
   */
  async downloadReport(jobId: string, format: 'xlsx' | 'pdf' = 'xlsx'): Promise<string> {
    try {
      const response = await api.get(`/jobs/${jobId}/report`, {
        params: { format },
      })
      return response.data.downloadUrl
    } catch (error) {
      console.error('下载报表失败:', error)
      throw error
    }
  },

  /**
   * 重算成本
   */
  async recalculateCost(
    jobId: string, 
    subgraphIds?: string[], 
    modifications?: Record<string, any>
  ): Promise<void> {
    try {
      await api.post(`/jobs/${jobId}/recalculate`, {
        subgraphIds,
        modifications,
      })
    } catch (error) {
      console.error('重算成本失败:', error)
      throw error
    }
  },
}
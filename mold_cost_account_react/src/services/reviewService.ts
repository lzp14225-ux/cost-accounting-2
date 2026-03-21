import api from './api'

export interface ReviewStartRequest {
  job_id: string
}

export interface ReviewStartResponse {
  status: 'ok'
  message: string
  data: {
    job_id: string
    features_count?: number
    price_snapshots_count?: number
    process_snapshots_count?: number
    subgraphs_count?: number
    // 数据完整性检查相关字段
    completeness?: {
      is_complete: boolean
      missing_fields?: Array<{
        table: string
        record_id: string
        record_name: string
        part_code?: string  // 新增：零件编号
        part_name?: string  // 新增：零件名称
        missing: Record<string, string>  // 字段名 -> 中文描述
        current_values: Record<string, any>
      }>
      summary?: string
    }
  }
  suggestion?: string  // AI建议的补全内容
}

export interface ModificationRequest {
  modification_text: string
}

export interface ParsedChange {
  table: string
  id: string
  field: string
  old_value: any
  new_value: any
}

// 意图类型
export type IntentType = 
  | 'DATA_MODIFICATION'      // 数据修改
  | 'FEATURE_RECOGNITION'    // 特征识别
  | 'PRICE_CALCULATION'      // 价格计算
  | 'QUERY_DETAILS'          // 查询详情
  | 'GENERAL_CHAT'           // 普通聊天

export interface ModificationResponse {
  status: 'ok'
  intent: IntentType                    // 新增：意图类型
  message: string
  requires_confirmation: boolean        // 新增：是否需要确认
  data: {
    modification_id?: string
    parsed_changes?: ParsedChange[]
    subgraph_ids?: string[]            // 特征识别/价格计算时的子图ID列表
    count?: number                     // 子图数量
    subgraph_id?: string               // 查询详情时的子图ID
    calculation_steps?: any[]          // 计算步骤
  }
}

export interface ConfirmRequest {
  comment?: string
}

export interface ConfirmResponse {
  status: 'ok'
  message: string
  data: {
    action_type: IntentType              // 新增：操作类型
    changes_count?: number               // 数据修改时的变更数量
    task_id?: string                     // 特征识别/价格计算时的任务ID
    subgraph_ids?: string[]              // 特征识别/价格计算时的子图ID列表
    modifications_count?: number         // 兼容旧版本
    updated_tables?: string[]            // 兼容旧版本
  }
}

export interface ReviewStatus {
  job_id: string
  review_status: 'pending_completion' | 'reviewing' | 'completed'
  is_locked: boolean
  modifications_count: number
  created_at: string
  last_modified_at: string
}

export interface ReviewStatusResponse {
  status: 'ok'
  data: ReviewStatus
}

export interface RefreshResponse {
  status: 'ok'
  message: string
  data: {
    job_id: string
    refresh_count: number
    features_count: number
    subgraphs_count: number
    price_snapshots_count: number
    process_snapshots_count: number
    is_complete: boolean
    missing_fields_count: number
  }
}

class ReviewService {
  /**
   * 启动审核流程
   * POST /api/v1/review/start
   */
  async startReview(jobId: string): Promise<ReviewStartResponse> {
    try {
      const response = await api.post('/review/start', {
        job_id: jobId,
      })
      
      return response.data
    } catch (error: any) {
      console.error('启动审核失败:', error)
      
      // 处理特定错误
      if (error.response?.data?.detail) {
        const detail = error.response.data.detail
        if (detail.error === 'REVIEW_LOCKED') {
          throw new Error('该任务正在被其他用户审核，请稍后重试')
        } else if (detail.error === 'SESSION_NOT_FOUND') {
          throw new Error('会话不存在')
        }
      }
      
      throw error
    }
  }

  /**
   * 提交修改指令
   * POST /api/v1/review/{job_id}/modify
   */
  async submitModification(jobId: string, modificationText: string): Promise<ModificationResponse> {
    try {
      const response = await api.post(`/review/${jobId}/modify`, {
        modification_text: modificationText,
      })
      
      return response.data
    } catch (error: any) {
      console.error('提交修改失败:', error)
      
      // 处理特定错误
      if (error.response?.data?.detail) {
        const detail = error.response.data.detail
        
        // 处理会话不存在错误 - 自动重启会话并重试
        if (detail.error === 'SESSION_NOT_FOUND' && error.response?.status === 404) {
          console.warn('⚠️ 会话不存在，尝试重新启动审核会话...')
          
          try {
            // 重新启动审核会话
            await this.startReview(jobId)
            console.log('✅ 审核会话已重新启动，重试提交修改...')
            
            // 重试提交修改
            const retryResponse = await api.post(`/review/${jobId}/modify`, {
              modification_text: modificationText,
            })
            
            return retryResponse.data
          } catch (retryError: any) {
            console.error('❌ 重启会话后重试失败:', retryError)
            throw new Error('会话已过期，重新启动失败，请刷新页面重试')
          }
        } else if (detail.error === 'PARSE_FAILED') {
          throw new Error('修改指令解析失败，请重新输入')
        } else if (detail.error === 'REVIEW_LOCKED') {
          throw new Error('该任务正在被其他用户审核')
        } else if (detail.error === 'MODIFICATION_FAILED') {
          // 处理修改验证失败错误，直接显示后端返回的详细错误信息
          throw new Error(detail.message || '修改验证失败')
        }
      }
      
      throw error
    }
  }

  /**
   * 确认修改
   * POST /api/v1/review/{job_id}/confirm
   */
  async confirmModification(jobId: string, comment?: string): Promise<ConfirmResponse> {
    try {
      const response = await api.post(`/review/${jobId}/confirm`, {
        comment,
      })
      
      return response.data
    } catch (error: any) {
      console.error('确认修改失败:', error)
      
      // 处理会话不存在错误 - 自动重启会话并重试
      if (error.response?.status === 404 && error.response?.data?.detail?.error === 'SESSION_NOT_FOUND') {
        console.warn('⚠️ 会话不存在，尝试重新启动审核会话...')
        
        try {
          // 重新启动审核会话
          await this.startReview(jobId)
          console.log('✅ 审核会话已重新启动，重试确认修改...')
          
          // 重试确认修改
          const retryResponse = await api.post(`/review/${jobId}/confirm`, {
            comment,
          })
          
          return retryResponse.data
        } catch (retryError: any) {
          console.error('❌ 重启会话后重试失败:', retryError)
          throw new Error('会话已过期，重新启动失败，请刷新页面重试')
        }
      }
      
      throw error
    }
  }

  /**
   * 刷新审核数据
   * POST /api/v1/review/{job_id}/refresh
   */
  async refreshReview(jobId: string): Promise<RefreshResponse> {
    try {
      const response = await api.post(`/review/${jobId}/refresh`)
      
      return response.data
    } catch (error: any) {
      console.error('刷新审核数据失败:', error)
      throw error
    }
  }

  /**
   * 查询审核状态
   * GET /api/v1/review/{job_id}/status
   * 
   * @deprecated 不推荐使用，应该通过 WebSocket 的 review_data 消息获取审核数据
   * 根据 FRONTEND_API_GUIDE(1).md，审核数据通过 WebSocket 推送，不需要轮询此接口
   */
  async getReviewStatus(jobId: string): Promise<ReviewStatusResponse> {
    console.warn('⚠️ getReviewStatus 已废弃，建议使用 WebSocket 推送代替')
    try {
      const response = await api.get(`/review/${jobId}/status`)
      
      return response.data
    } catch (error: any) {
      console.error('查询审核状态失败:', error)
      
      // 处理404错误（会话不存在）
      if (error.response?.status === 404) {
        throw new Error('审核会话不存在或已过期')
      }
      
      throw error
    }
  }

  /**
   * 检查是否可以开始审核
   * 
   * @deprecated 不推荐使用，直接调用 startReview 即可，后端会处理重复启动的情况
   */
  async canStartReview(jobId: string): Promise<boolean> {
    console.warn('⚠️ canStartReview 已废弃，直接调用 startReview 即可')
    try {
      const statusResponse = await this.getReviewStatus(jobId)
      const status = statusResponse.data
      
      // 如果已经在审核中且被锁定，不能重新开始
      if (status.review_status === 'reviewing' && status.is_locked) {
        return false
      }
      
      // 如果已完成，不能重新开始
      if (status.review_status === 'completed') {
        return false
      }
      
      return true
    } catch (error) {
      // 如果会话不存在，可以开始审核
      if (error instanceof Error && error.message.includes('不存在')) {
        return true
      }
      
      console.error('检查审核状态失败:', error)
      return false
    }
  }

  /**
   * 获取意图类型的中文描述
   */
  getIntentText(intent: IntentType): string {
    const intentMap: Record<IntentType, string> = {
      'DATA_MODIFICATION': '数据修改',
      'FEATURE_RECOGNITION': '特征识别',
      'PRICE_CALCULATION': '价格计算',
      'QUERY_DETAILS': '查询详情',
      'GENERAL_CHAT': '普通聊天'
    }
    return intentMap[intent] || '未知意图'
  }

  /**
   * 检查是否需要确认操作
   */
  needsConfirmation(response: ModificationResponse): boolean {
    return response.requires_confirmation === true
  }

  /**
   * 格式化子图ID列表
   */
  formatSubgraphIds(subgraphIds: string[]): string {
    if (!subgraphIds || subgraphIds.length === 0) {
      return '无'
    }
    return subgraphIds.join(', ')
  }

  /**
   * 获取审核状态文本
   */
  getStatusText(status: ReviewStatus['review_status']): string {
    const statusMap = {
      'pending_completion': '等待补全',
      'reviewing': '审核中',
      'completed': '已完成'
    }
    return statusMap[status] || '未知状态'
  }

  /**
   * 格式化修改变更为可读文本
   */
  formatChanges(changes: ParsedChange[]): string {
    return changes.map(change => {
      return `${change.table}.${change.id}.${change.field}: ${change.old_value} → ${change.new_value}`
    }).join('\n')
  }
}

export const reviewService = new ReviewService()
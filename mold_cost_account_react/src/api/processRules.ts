import axios from 'axios'
import { getValidToken } from '../utils/auth'
import config from '../config/env'

const API_BASE_URL = config.AUTH_BASE_URL

// 创建axios实例
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器 - 添加token
apiClient.interceptors.request.use(
  (config) => {
    const token = getValidToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    // 调试：打印响应数据
    if (response.config.url?.includes('process-rules')) {
      // console.log('工艺规则API响应:', response.data)
    }
    return response.data
  },
  (error) => {
    const message = error.response?.data?.message || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

// 特征类型枚举
export enum FeatureType {
  WIRE = 'WIRE',   // 线割
  NC = 'NC',       // 数控
  EDM = 'EDM',     // 电火花
  MILL = 'MILL',   // 铣削
  DRILL = 'DRILL', // 钻孔
}

// 特征类型显示名称
export const FeatureTypeLabels: Record<FeatureType, string> = {
  [FeatureType.WIRE]: '线割',
  [FeatureType.NC]: '数控',
  [FeatureType.EDM]: '电火花',
  [FeatureType.MILL]: '铣削',
  [FeatureType.DRILL]: '钻孔',
}

// 辅助函数：获取特征类型显示名称（容错处理）
export const getFeatureTypeLabel = (type: string | FeatureType | undefined | null): string => {
  if (!type) return '未知'
  
  // 尝试直接匹配
  if (type in FeatureTypeLabels) {
    return FeatureTypeLabels[type as FeatureType]
  }
  
  // 尝试转换为大写后匹配
  const upperType = String(type).toUpperCase()
  if (upperType in FeatureTypeLabels) {
    return FeatureTypeLabels[upperType as FeatureType]
  }
  
  // 如果都不匹配，返回原值或未知
  return String(type) || '未知'
}

// 工艺规则接口
export interface ProcessRule {
  id: string
  version_id: string
  feature_type: FeatureType
  name: string
  description?: string
  priority: number
  is_active: boolean
  conditions: string
  output_params: string
  created_at: string
}

// 创建规则参数
export interface CreateRuleParams {
  id: string
  version_id: string
  feature_type: FeatureType
  name: string
  description?: string
  priority?: number
  is_active?: boolean
  conditions: string
  output_params: string
}

// 更新规则参数
export interface UpdateRuleParams {
  version_id?: string
  feature_type?: FeatureType
  name?: string
  description?: string
  priority?: number
  is_active?: boolean
  conditions?: string
  output_params?: string
}

// 查询参数
export interface QueryRulesParams {
  page?: number
  page_size?: number
  version_id?: string
  feature_type?: FeatureType
  is_active?: boolean
  name?: string
}

// 分页响应
export interface PaginatedResponse<T> {
  total: number
  page: number
  page_size: number
  total_pages: number
  data: T[]
}

// API响应
export interface ApiResponse<T = any> {
  success: boolean
  message: string
  data?: T
}

// 1. 创建工艺规则
export const createProcessRule = async (params: CreateRuleParams): Promise<ApiResponse<ProcessRule>> => {
  return apiClient.post('/api/process-rules', params)
}

// 2. 获取单个规则
export const getProcessRule = async (ruleId: string): Promise<ApiResponse<ProcessRule>> => {
  return apiClient.get(`/api/process-rules/${ruleId}`)
}

// 3. 获取规则列表
export const getProcessRules = async (params?: QueryRulesParams): Promise<ApiResponse<PaginatedResponse<ProcessRule>>> => {
  return apiClient.get('/api/process-rules', { params })
}

// 4. 更新规则
export const updateProcessRule = async (ruleId: string, params: UpdateRuleParams): Promise<ApiResponse<ProcessRule>> => {
  return apiClient.put(`/api/process-rules/${ruleId}`, params)
}

// 5. 软删除规则（单个）
export const deleteProcessRule = async (ruleId: string): Promise<ApiResponse> => {
  return apiClient.put(`/api/process-rules/${ruleId}/soft-delete`)
}

// 6. 批量软删除规则
export const batchDeleteProcessRules = async (ids: string[]): Promise<ApiResponse<{ deleted_count: number }>> => {
  return apiClient.post('/api/process-rules/batch-soft-delete', { ids })
}

// 7. 根据版本和类型获取规则
export const getRulesByVersionType = async (
  versionId: string,
  featureType: FeatureType,
  activeOnly: boolean = true
): Promise<ApiResponse<ProcessRule[]>> => {
  return apiClient.get('/api/process-rules/by-version-type', {
    params: {
      version_id: versionId,
      feature_type: featureType,
      active_only: activeOnly,
    },
  })
}

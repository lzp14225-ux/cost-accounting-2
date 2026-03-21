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
    return response.data
  },
  (error) => {
    const message = error.response?.data?.message || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

// 类别枚举
export enum PriceCategory {
  WIRE = 'wire',                    // 线割工艺
  SPECIAL = 'special',              // 线割特殊费
  BASE = 'base',                    // 线割基础费
  MATERIAL = 'material',            // 材质单价
  HEAT = 'heat',                    // 热处理单价
  NC = 'NC',                        // NC单价
  RULE = 'rule',                    // 倍数规则
  S_WATER_MILL = 'S_water_mill',    // 小水磨
  L_WATER_MILL = 'L_water_mill',    // 大水磨
  TOOTH_HOLE = 'tooth_hole',        // 牙孔
  SCREW = 'screw',                  // 普通螺丝
  STOP_SCREW = 'stop_screw',        // 止付螺丝
  DENSITY = 'density',              // 材质密度
}

// 类别显示名称
export const PriceCategoryLabels: Record<PriceCategory, string> = {
  [PriceCategory.WIRE]: '线割工艺',
  [PriceCategory.SPECIAL]: '线割特殊费',
  [PriceCategory.BASE]: '线割基础费',
  [PriceCategory.MATERIAL]: '材质单价',
  [PriceCategory.HEAT]: '热处理单价',
  [PriceCategory.NC]: 'NC单价',
  [PriceCategory.RULE]: '倍数规则',
  [PriceCategory.S_WATER_MILL]: '小水磨',
  [PriceCategory.L_WATER_MILL]: '大水磨',
  [PriceCategory.TOOTH_HOLE]: '牙孔',
  [PriceCategory.SCREW]: '普通螺丝',
  [PriceCategory.STOP_SCREW]: '止付螺丝',
  [PriceCategory.DENSITY]: '材质密度',
}

// 价格项接口
export interface PriceItem {
  id: string
  version_id?: string
  category?: PriceCategory
  sub_category?: string
  price?: string
  unit?: string
  work_hours?: string
  min_num?: string
  add_price?: string
  weight_num?: string
  description?: string
  note?: string
  instruction?: string
  is_active: boolean
  created_by?: string
  created_at: string
  updated_at: string
}

// 创建价格项参数
export interface CreatePriceItemParams {
  id: string
  version_id?: string
  category?: PriceCategory
  sub_category?: string
  price?: string
  unit?: string
  work_hours?: string
  min_num?: string
  add_price?: string
  weight_num?: string
  description?: string
  note?: string
  instruction?: string
  is_active?: boolean
  created_by?: string
}

// 更新价格项参数
export interface UpdatePriceItemParams {
  version_id?: string
  category?: PriceCategory
  sub_category?: string
  price?: string
  unit?: string
  work_hours?: string
  min_num?: string
  add_price?: string
  weight_num?: string
  description?: string
  note?: string
  instruction?: string
  is_active?: boolean
  created_by?: string
}

// 查询参数
export interface QueryPriceItemsParams {
  page?: number
  page_size?: number
  version_id?: string
  category?: PriceCategory
  sub_category?: string
  is_active?: boolean
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

// 1. 创建价格项
export const createPriceItem = async (params: CreatePriceItemParams): Promise<ApiResponse<PriceItem>> => {
  return apiClient.post('/api/price-items', params)
}

// 2. 获取单个价格项
export const getPriceItem = async (itemId: string): Promise<ApiResponse<PriceItem>> => {
  return apiClient.get(`/api/price-items/${itemId}`)
}

// 3. 获取价格项列表
export const getPriceItems = async (params?: QueryPriceItemsParams): Promise<ApiResponse<PaginatedResponse<PriceItem>>> => {
  return apiClient.get('/api/price-items', { params })
}

// 4. 更新价格项
export const updatePriceItem = async (itemId: string, params: UpdatePriceItemParams): Promise<ApiResponse<PriceItem>> => {
  return apiClient.put(`/api/price-items/${itemId}`, params)
}

// 5. 软删除价格项（单个）
export const deletePriceItem = async (itemId: string): Promise<ApiResponse> => {
  return apiClient.put(`/api/price-items/${itemId}/soft-delete`)
}

// 6. 批量软删除价格项
export const batchDeletePriceItems = async (ids: string[]): Promise<ApiResponse<{ deleted_count: number }>> => {
  return apiClient.post('/api/price-items/batch-soft-delete', { ids })
}

// 7. 根据版本和类别获取价格项
export const getPriceItemsByVersionCategory = async (
  versionId: string,
  category: PriceCategory,
  activeOnly: boolean = true
): Promise<ApiResponse<PriceItem[]>> => {
  return apiClient.get('/api/price-items/by-version-category', {
    params: {
      version_id: versionId,
      category: category,
      active_only: activeOnly,
    },
  })
}

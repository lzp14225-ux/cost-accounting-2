import { uploadCADFiles } from '../utils/request'
import config from '../config/env'

export interface UploadResponse {
  job_id: string
  status: string
  message: string
  files: {
    dwg?: {
      filename: string
      size: number
    }
    prt?: {
      filename: string
      size: number
    }
  }
}

export const fileService = {
  /**
   * 上传文件
   */
  async uploadFiles(
    formData: FormData, 
    onProgress?: (progress: number) => void
  ): Promise<UploadResponse> {
    try {
      // 从 FormData 中获取文件
      const files = formData.getAll('files') as File[]
      
      if (files.length === 0) {
        throw new Error('没有选择文件')
      }

      // 初始化进度为0
      if (onProgress) {
        onProgress(0)
      }

      // 模拟上传进度
      let progress = 0
      const progressInterval = setInterval(() => {
        progress += Math.random() * 15
        if (progress > 90) {
          progress = 90
        }
        if (onProgress) {
          onProgress(progress)
        }
      }, 200)

      try {
        // 调用真实的上传API
        const response = await uploadCADFiles<UploadResponse>(
          `${config.API_URL}/jobs/upload`, 
          files
        )

        // 完成上传
        clearInterval(progressInterval)
        if (onProgress) {
          onProgress(100)
        }

        return response
      } finally {
        clearInterval(progressInterval)
      }
    } catch (error) {
      console.error('文件上传失败:', error)
      // 确保在失败时也清理进度回调
      if (onProgress) {
        onProgress(0)
      }
      throw error
    }
  },

  /**
   * 获取文件下载链接
   */
  async getDownloadUrl(fileId: string): Promise<string> {
    try {
      // TODO: 实现文件下载链接获取
      console.log('请求下载链接 for fileId:', fileId)
      throw new Error('文件下载功能暂未实现')
    } catch (error) {
      console.error('获取下载链接失败:', error)
      throw error
    }
  },

  /**
   * 获取文件预签名URL
   */
  async getPresignedUrl(filePath: string, expiresIn: number = 3600): Promise<{
    url: string
    expires_at: string
    expires_in: number
    file_path: string
    bucket: string
  }> {
    try {
      const { post } = await import('../utils/request')
      const config = await import('../config/env')
      
      const response = await post<{
        success: boolean
        data: {
          url: string
          expires_at: string
          expires_in: number
          file_path: string
          bucket: string
        }
      }>(`${config.default.API_URL}/files/presigned-url`, {
        file_path: filePath,
        expires_in: expiresIn
      })

      if (response.success && response.data) {
        return response.data
      } else {
        throw new Error('获取预签名URL失败')
      }
    } catch (error) {
      console.error('获取预签名URL失败:', error)
      throw error
    }
  },

  /**
   * 删除文件
   */
  async deleteFile(fileId: string): Promise<void> {
    try {
      // TODO: 实现文件删除
      console.log('删除文件 fileId:', fileId)
      throw new Error('文件删除功能暂未实现')
    } catch (error) {
      console.error('删除文件失败:', error)
      throw error
    }
  },

  /**
   * 获取文件信息
   */
  async getFileInfo(fileId: string) {
    try {
      // TODO: 实现文件信息获取
      console.log('获取文件信息 for fileId:', fileId)
      throw new Error('获取文件信息功能暂未实现')
    } catch (error) {
      console.error('获取文件信息失败:', error)
      throw error
    }
  },
}
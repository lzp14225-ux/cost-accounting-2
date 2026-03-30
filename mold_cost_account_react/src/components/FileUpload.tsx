import React, { useState, useCallback, useEffect, useRef } from 'react'
import { Modal, Button, Progress, Typography, Card, Space, Flex, theme, message as antdMessage } from 'antd'
import { InboxOutlined, DeleteOutlined, FileOutlined, CloudUploadOutlined } from '@ant-design/icons'
import { useDropzone } from 'react-dropzone'
import { useAppStore } from '../store/useAppStore'
import { fileService } from '../services/fileService'
import { chatService } from '../services/chatService'
import { useMessage } from '../hooks/useMessage'
import { useWebSocket } from '../hooks/useWebSocket'



const { Text, Title } = Typography

interface FileUploadProps {
  visible: boolean
  onClose: () => void
}

interface UploadFile {
  id: string
  name: string
  size: number
  type: string
  file: File
  progress: number
  status: 'waiting' | 'uploading' | 'success' | 'error'
  errorMessage?: string
}

const FileUpload: React.FC<FileUploadProps> = ({ visible, onClose }) => {
  const [files, setFiles] = useState<UploadFile[]>([])
  const [uploading, setUploading] = useState(false)
  const [progressInterval, setProgressInterval] = useState<NodeJS.Timeout | null>(null)
  const [globalDragActive, setGlobalDragActive] = useState(false) // 全局拖拽状态
  const [currentJobId, setCurrentJobId] = useState<string | null>(null)
  const [isConnectingWebSocket, setIsConnectingWebSocket] = useState(false) // WebSocket连接状态
  const message = useMessage()
  const { token } = theme.useToken()
  
  const { addMessage, setCurrentJobId: setStoreJobId, addJob, setIsTyping, setIsNewSession, setIsStartingReview, setReviewStarted, setIsCalculating, setIsRefreshing, setIsReprocessing } = useAppStore()

  // 使用 ref 追踪是否已经启动过审核流程，避免重复调用
  const reviewStartedRef = useRef<Set<string>>(new Set())

  // 特征识别完成后启动审核流程
  const startReviewAfterFeatureRecognition = async (jobId: string) => {
    // 检查是否已经启动过
    if (reviewStartedRef.current.has(jobId)) {
      // console.log('⏭️ 审核流程已启动过，跳过:', jobId)
      return
    }
    
    try {
      // console.log('特征识别完成，启动审核流程...')
      reviewStartedRef.current.add(jobId) // 标记为已启动
      
      // 设置正在启动审核状态，禁用输入框
      setIsStartingReview(true)
      
      const { chatService } = await import('../services/chatService')
      const result = await chatService.startReview(jobId)
      
      // 审核启动完成，允许输入
      setIsStartingReview(false)
      
      // 标记审核已启动完成，允许显示开始核算卡片
      setReviewStarted(true)
      
      // 不再使用接口返回的数据，等待 WebSocket 推送 completion_request 或 review_display_view
      // console.log('⏳ 等待 WebSocket 推送数据...')
      
      // 确保停止打字状态，允许用户输入
      setIsTyping(false)
      
    } catch (reviewError) {
      console.error('启动审核流程失败:', reviewError)
      reviewStartedRef.current.delete(jobId) // 失败时移除标记，允许重试
      
      // 审核启动失败，允许输入
      setIsStartingReview(false)
      
      // 显示错误消息
      addMessage({
        type: 'assistant',
        content: `启动审核流程失败: ${reviewError instanceof Error ? reviewError.message : '未知错误'}`,
        jobId: jobId,
      })
      
      // 确保停止打字状态，允许用户输入
      console.log('❌ 审核流程失败，停止打字状态，允许用户输入')
      setIsTyping(false)
    }
  }

  // WebSocket连接
  const {
    isConnected,
    connect: connectWebSocket,
  } = useWebSocket(undefined, {
    heartbeatConfig: {
      interval: 15000, // 15秒心跳间隔
      timeout: 8000,   // 8秒超时
      maxMissed: 3,    // 最多丢失3次
      enabled: true
    },
    onHistoryLoaded: (messages) => {
      if (messages.length > 0) {
        antdMessage.info(`加载了 ${messages.length} 条历史消息`)
      }
    },
    onConnected: () => {
      // console.log('WebSocket连接成功')
      // antdMessage.success('实时连接已建立')
    },
    onCompletionRequest: (jobId, data) => {
      // 处理缺失字段补全请求
      // console.log('⚠️ 收到缺失字段补全请求:', data)
      
      // 如果正在等待AI回复，则忽略
      const isWaitingForReply = useAppStore.getState().isWaitingForReply
      if (isWaitingForReply) {
        // console.log('⏭️ 正在等待AI回复，忽略 completion_request 消息')
        return
      }
      
      // 停止打字状态
      setIsTyping(false)
      
      // 添加缺失字段卡片消息
      addMessage({
        type: 'assistant',
        content: data.message || '数据不完整，需要补全必填字段',
        jobId: jobId,
        missingFieldsData: {
          message: data.message || '数据不完整，需要补全必填字段',
          summary: data.summary || `发现 ${data.missing_fields?.length || 0} 条记录缺少必填字段`,
          missing_fields: data.missing_fields || [],
          nc_failed_items: data.nc_failed_items || [],
          suggestion: data.suggestion,
        },
      })
    },
    onProgress: (jobId, data) => {
      // 检查是否是 review_display_view 类型（显示表格）
      const isReviewDisplayView = (data as any).type === 'review_display_view'
      
      // 检查是否是 completion_request 类型（缺失字段请求）
      const isCompletionRequest = (data as any).type === 'completion_request'
      
      // 如果正在等待AI回复，且收到的是 review_display_view 或 completion_request，则忽略
      const isWaitingForReply = useAppStore.getState().isWaitingForReply
      const isRefreshing = useAppStore.getState().isRefreshing
      if (isWaitingForReply && !isRefreshing && (isReviewDisplayView || isCompletionRequest)) {
        console.log('⏭️ 正在等待AI回复，忽略 review_display_view 或 completion_request 消息')
        return
      }
      
      // 检查是否是等待确认状态（特征识别完成，等待用户确认）
      const isAwaitingConfirm = data.stage === 'awaiting_confirm'
      
      // 检查是否是任务完成
      const isTaskCompleted = data.stage === 'completed' || data.progress === 100
      
      // 检查是否是特征识别完成
      const isFeatureRecognitionCompleted = 
        data.stage === 'feature_recognition_completed' || 
        (data.message && data.message.includes('特征识别完成')) ||
        isReviewDisplayView ||
        isCompletionRequest ||
        isAwaitingConfirm  // 添加等待确认状态的判断
      
      // 如果任务完成，重置核算状态并停止打字状态
      if (isTaskCompleted) {
        // console.log('✅ 任务完成，重置核算状态和打字状态')
        setIsCalculating(false)
        setIsTyping(false)
      }
      // 如果是显示表格、缺失字段请求、等待确认或特征识别完成，立即停止打字状态
      else if (isFeatureRecognitionCompleted) {
        setIsTyping(false)
      } else {
        // 其他进度消息才设置打字状态
        setIsTyping(true)
      }
      
      // 添加所有进度消息到聊天区域
      if (isCompletionRequest) {
        // 缺失字段请求类型的特殊处理
        const completionData = (data as any).data
        
        addMessage({
          type: 'assistant',
          content: completionData.message || '数据不完整，需要补全必填字段',
          jobId: jobId,
          missingFieldsData: {
            message: completionData.message || '数据不完整，需要补全必填字段',
            summary: completionData.summary || `发现 ${completionData.missing_fields?.length || 0} 条记录缺少必填字段`,
            missing_fields: completionData.missing_fields || [],
            nc_failed_items: completionData.nc_failed_items || [],
            suggestion: completionData.suggestion,
          },
        })
      } else if (isReviewDisplayView) {
        // 显示表格类型的特殊处理
        // review_display_view 表示特征识别完成，设置进度为50%（等待用户确认）
        const messageData = {
          type: 'progress' as const,
          content: '特征识别完成，请检查结果并确认',
          jobId: jobId,
          progressData: {
            stage: 'awaiting_confirm',
            progress: 50, // 设置为50%，表示特征识别完成，等待用户确认
            message: '特征识别完成，请检查结果并确认',
            type: (data as any).type,
            data: (data as any).data,
          },
        }
        
        addMessage(messageData)
      } else if (isAwaitingConfirm) {
        // 等待确认状态的特殊处理
        const messageData = {
          type: 'progress' as const,
          content: data.message || '特征识别完成，请检查结果并确认',
          jobId: jobId,
          progressData: {
            stage: 'awaiting_confirm',
            progress: 50, // 设置为50%，表示特征识别完成，等待用户确认
            message: data.message || '特征识别完成，请检查结果并确认',
            details: data.details,
          },
        }
        
        addMessage(messageData)
        
        // 收到 awaiting_confirm 消息后，调用 /review/start 接口
        // console.log('✅ 收到 awaiting_confirm 消息，准备调用 /review/start 接口')
        setTimeout(() => {
          startReviewAfterFeatureRecognition(jobId)
        }, 100)
      } else {
        // 普通进度消息
        const messageData = {
          type: 'progress' as const,
          content: data.message || '处理中...',
          jobId: jobId,
          progressData: {
            stage: data.stage,
            progress: data.progress || 0,
            message: data.message || '处理中...',
            details: data.details,
          },
        }
        
        addMessage(messageData)
        
        // 检查是否是特征识别或价格计算完成消息
        // 注意：首次特征识别完成后会调用 /review/start 接口，不需要再调用 refresh
        // 只有在重新识别特征或重新计算价格时才需要调用 refresh
        if (data.stage === 'feature_recognition_completed') {
          // 检查是否是重新处理（通过 isReprocessing 状态判断）
          // 如果是首次识别，不调用 refresh（会由 /review/start 接口处理）
          // 如果是重新识别，才调用 refresh
          const { isReprocessing } = useAppStore.getState()
          if (isReprocessing) {
            setIsRefreshing(false)
            setIsReprocessing(false)
            console.log('Wait for backend-pushed review data after feature_recognition_completed (reprocess)')
          } else {
            // console.log('⏭️ 首次特征识别完成，跳过 refresh（等待 /review/start 接口）')
          }
        } else if (data.stage === 'pricing_completed') {
          // console.log('Wait for backend-pushed review data after pricing_completed')
          setIsCalculating(false)
          setIsRefreshing(false)
          setIsReprocessing(false)
        } else if (data.stage === 'pricing_started') {
          // 价格计算开始，停止核算状态（因为已经开始了）
          setIsCalculating(false)
        }
      }
      
      // 注意：不再在这里检查特征识别完成并启动审核流程
      // 改为在收到 awaiting_confirm 消息时才调用 /review/start 接口
      // 这样可以确保在正确的时机调用接口
    },
    onReviewData: (_, data) => {
      console.log('收到审核数据:', data)
      // 不再添加审核数据消息，让界面保持简洁
      // 用户可以直接看到表格并输入修改内容
      setIsTyping(false)
    },
    onModificationConfirmation: (jobId, data) => {
      console.log('收到修改确认请求:', data)
      // 添加修改确认消息到聊天区域
      addMessage({
        type: 'system',
        content: '请确认以下修改：',
        jobId: jobId,
        modificationData: data,
      } as any)
      antdMessage.info('请确认修改内容')
      setIsTyping(false)
    },
    onReviewCompleted: (jobId, data) => {
      console.log('审核已完成:', data)
      addMessage({
        type: 'system',
        content: `审核已完成，共应用了 ${data.modifications_count || 0} 项修改`,
        jobId: jobId,
      })
      antdMessage.success('审核已完成')
      setIsTyping(false)
    },
    onNeedUserInput: (_, card) => {
      console.log('需要用户输入:', card)
      antdMessage.info(`需要您的输入: ${card.title}`)
      // 需要用户输入时停止打字状态
      setIsTyping(false)
    },
    onInteractionResponseReceived: (_, msg) => {
      console.log('交互响应已接收:', msg)
      antdMessage.success('输入已提交')
      // 用户输入提交后，重新开始AI处理
      setIsTyping(true)
    },
    onError: (_, error) => {
      console.error('WebSocket错误:', error)
      antdMessage.error(`连接错误: ${error}`)
      // 出错时停止打字状态
      setIsTyping(false)
    },
    onHeartbeat: (stats) => {
      // console.log('心跳统计:', stats)
    },
    onConnectionQuality: (quality) => {
      // 不显示网络连接质量通知
      // console.log('网络连接质量:', quality)
    },
  })

  // 清理定时器
  useEffect(() => {
    return () => {
      if (progressInterval) {
        clearInterval(progressInterval)
      }
    }
  }, [progressInterval])

  // 监听重置上传状态事件
  useEffect(() => {
    const handleResetUploadState = () => {
      // 重置所有状态
      setCurrentJobId(null)
      setIsConnectingWebSocket(false)
      setUploading(false)
      setFiles([])
      setGlobalDragActive(false)
      
      // 清理定时器
      if (progressInterval) {
        clearInterval(progressInterval)
        setProgressInterval(null)
      }
      
      // 清理审核流程追踪
      reviewStartedRef.current.clear()
    }

    window.addEventListener('resetUploadState', handleResetUploadState)
    
    return () => {
      window.removeEventListener('resetUploadState', handleResetUploadState)
    }
  }, [progressInterval])

  // 添加全局拖拽事件监听器
  useEffect(() => {
    let dragCounter = 0

    const handleDragEnter = (e: DragEvent) => {
      e.preventDefault()
      dragCounter++
      console.log('Window拖拽进入，计数器:', dragCounter)
      
      if (dragCounter === 1) {
        setGlobalDragActive(true)
        console.log('设置全局拖拽状态为 true')
      }
    }

    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault()
      
      // 检查是否离开了窗口边界
      const rect = document.documentElement.getBoundingClientRect()
      const x = e.clientX
      const y = e.clientY
      
      if (x <= rect.left || x >= rect.right || y <= rect.top || y >= rect.bottom) {
        dragCounter--
        console.log('Window拖拽离开窗口边界，计数器:', dragCounter)
        
        if (dragCounter <= 0) {
          dragCounter = 0
          setGlobalDragActive(false)
          console.log('设置全局拖拽状态为 false')
        }
      }
    }

    const handleDragOver = (e: DragEvent) => {
      e.preventDefault()
    }

    const handleDrop = (e: DragEvent) => {
      e.preventDefault()
      dragCounter = 0
      setGlobalDragActive(false)
    }

    if (visible) {
      window.addEventListener('dragenter', handleDragEnter)
      window.addEventListener('dragleave', handleDragLeave)
      window.addEventListener('dragover', handleDragOver)
      window.addEventListener('drop', handleDrop)
    }

    return () => {
      window.removeEventListener('dragenter', handleDragEnter)
      window.removeEventListener('dragleave', handleDragLeave)
      window.removeEventListener('dragover', handleDragOver)
      window.removeEventListener('drop', handleDrop)
      setGlobalDragActive(false)
      dragCounter = 0
    }
  }, [visible])

  const onDrop = useCallback((acceptedFiles: File[], rejectedFiles: any[]) => {
    
    // 如果正在上传，不处理新文件
    if (uploading) {
      message.warning('正在上传中，请等待上传完成')
      return
    }
    
    // 处理被拒绝的文件
    if (rejectedFiles.length > 0) {
      console.log('被拒绝的文件:', rejectedFiles)
      rejectedFiles.forEach(({ file, errors }) => {
        message.error(`文件 ${file.name} 不支持: ${errors.map((e: any) => e.message).join(', ')}`)
      })
    }
    
    // 验证文件组合
    const allFiles = [...files, ...acceptedFiles]
    const dwgFiles = allFiles.filter(f => f.name.toLowerCase().endsWith('.dwg'))
    const prtFiles = allFiles.filter(f => f.name.toLowerCase().endsWith('.prt'))
    
    // 检查文件数量限制
    if (allFiles.length > 2) {
      message.error('最多只能上传2个文件')
      return
    }
    
    // 检查文件类型组合
    if (dwgFiles.length > 1) {
      message.error('只能上传1个DWG文件')
      return
    }
    
    if (prtFiles.length > 1) {
      message.error('只能上传1个PRT文件')
      return
    }
    
    // 检查是否有其他类型的文件
    const validFiles = allFiles.filter(f => {
      const name = f.name.toLowerCase()
      return name.endsWith('.dwg') || name.endsWith('.prt')
    })
    
    if (validFiles.length !== allFiles.length) {
      message.error('只支持DWG和PRT文件')
      return
    }
    
    const newFiles: UploadFile[] = acceptedFiles.map(file => ({
      id: Date.now().toString() + Math.random().toString(36).substring(2, 11),
      name: file.name,
      size: file.size,
      type: file.type,
      file,
      progress: 0,
      status: 'waiting',
    }))
    
    if (newFiles.length > 0) {
      setFiles(prev => [...prev, ...newFiles])
      message.success(`成功添加 ${newFiles.length} 个文件`)
    }
  }, [message, files, uploading])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    noClick: uploading,
    noKeyboard: uploading,
    noDrag: uploading,
    multiple: true,
    maxFiles: 2,
    disabled: uploading,
    accept: {
      'application/acad': ['.dwg'],
      'application/x-prt': ['.prt'],
      'application/octet-stream': ['.dwg', '.prt'],
    },
    validator: (file) => {
      const fileName = file.name.toLowerCase()
      
      if (fileName.endsWith('.dwg') || fileName.endsWith('.prt')) {
        return null
      }
      
      return {
        code: 'invalid-file-type',
        message: '只支持 DWG 和 PRT 文件格式'
      }
    },
    onDragEnter: () => {
      console.log('Dropzone拖拽进入 - 保持全局拖拽状态')
      // 不重置全局拖拽状态，保持放大效果
    },
    onDragLeave: () => {
      console.log('Dropzone拖拽离开')
    },
    onDropAccepted: (files) => {
      // 文件被接受后才重置全局状态
      setGlobalDragActive(false)
    },
    onDropRejected: (rejectedFiles) => {
      console.log('文件被拒绝:', rejectedFiles)
      // 文件被拒绝后才重置全局状态
      setGlobalDragActive(false)
    }
  })

  const removeFile = (fileId: string) => {
    setFiles(prev => prev.filter(f => f.id !== fileId))
  }

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const handleUpload = async () => {
    if (files.length === 0) {
      message.warning('请先选择文件')
      return
    }

    setUploading(true)
    
    // 清理之前的进度定时器
    if (progressInterval) {
      clearInterval(progressInterval)
      setProgressInterval(null)
    }
    
    // 重置所有文件的进度和状态
    setFiles(prev => prev.map(f => ({ 
      ...f, 
      status: 'uploading' as const,
      progress: 0,
      errorMessage: undefined
    })))
    
    try {
      const formData = new FormData()
      files.forEach(fileItem => {
        formData.append('files', fileItem.file)
      })

      // 模拟上传进度
      const interval = setInterval(() => {
        setFiles(prev => prev.map(f => {
          if (f.status === 'uploading') {
            return {
              ...f,
              progress: Math.min(f.progress + Math.random() * 20, 90)
            }
          }
          return f
        }))
      }, 500)
      setProgressInterval(interval)

      // 调用上传服务
      const result = await fileService.uploadFiles(formData, (progress) => {
        setFiles(prev => prev.map(f => {
          if (f.status === 'uploading') {
            return {
              ...f,
              progress: Math.max(f.progress, progress)
            }
          }
          return f
        }))
      })

      // 清理进度定时器
      clearInterval(interval)
      setProgressInterval(null)

      // 更新文件状态为成功
      setFiles(prev => prev.map(f => ({ 
        ...f, 
        status: 'success' as const, 
        progress: 100 
      })))

      // 添加文件上传消息（只显示附件，不显示文本内容）
      addMessage({
        type: 'user',
        content: '', // 空内容，只显示附件
        attachments: files.map(f => ({
          id: f.id,
          name: f.name,
          size: f.size,
          type: f.type,
        }))
      })

      // 设置当前任务ID，并标记为新会话（避免加载历史消息）
      setCurrentJobId(result.job_id)
      setIsNewSession(true)  // 标记为新会话，跳过历史消息加载
      setStoreJobId(result.job_id)

      // 连接WebSocket
      try {
        setIsConnectingWebSocket(true) // 开始连接，禁用关闭
        await connectWebSocket(result.job_id)
        
        // WebSocket连接成功后自动关闭弹窗
        message.success('文件上传成功，WebSocket连接已建立')
        
        // 触发更新侧边栏历史会话列表
        window.dispatchEvent(new CustomEvent('refreshSessions'))
        
        setTimeout(() => {
          setIsConnectingWebSocket(false) // 连接完成，允许关闭
          onClose()
          setFiles([])
        }, 1000) // 延迟1秒关闭，让用户看到成功提示
        
      } catch (wsError) {
        console.error('WebSocket连接失败:', wsError)
        setIsConnectingWebSocket(false) // 连接失败，允许关闭
        antdMessage.warning('实时连接失败，但文件上传成功')
        
        // 即使WebSocket连接失败，也关闭弹窗（因为文件上传成功了）
        setTimeout(() => {
          onClose()
          setFiles([])
        }, 2000) // 失败时延迟2秒关闭，让用户看到警告信息
      }

      // 添加任务到列表
      addJob({
        id: result.job_id,
        status: result.status as any,
        stage: '文件上传完成',
        progress: 0,
        dwgFile: result.files.dwg ? {
          id: Date.now().toString(),
          name: result.files.dwg.filename,
          size: result.files.dwg.size,
          type: 'application/acad',
        } : undefined,
        prtFile: result.files.prt ? {
          id: Date.now().toString(),
          name: result.files.prt.filename,
          size: result.files.prt.size,
          type: 'application/x-prt',
        } : undefined,
        createdAt: new Date(),
        updatedAt: new Date(),
      })

      // 设置AI正在处理状态（只显示旋转动画，不添加文字消息）
      setIsTyping(true)

      // REMOVED: 添加AI响应消息 - 只显示旋转动画即可
      // addMessage({
      //   type: 'assistant',
      //   content: result.message,
      //   jobId: result.job_id,
      // })

      // REMOVED: 立即启动审核流程 - 现在等待特征识别完成后再启动
      // 根据 chat-review-interface-trigger 规范，审核流程应在特征识别完成后启动
      /*
      try {
        console.log('启动审核流程...')
        const { chatService } = await import('../services/chatService')
        await chatService.startReview(result.job_id)
        console.log('审核流程启动成功')
        
        // 添加审核启动消息
        addMessage({
          type: 'system',
          content: '审核流程已启动，正在分析CAD文件数据...',
          jobId: result.job_id,
        })
      } catch (reviewError) {
        console.error('启动审核流程失败:', reviewError)
        // 不阻断文件上传流程，只是记录错误
        addMessage({
          type: 'system',
          content: '文件上传成功，但审核流程启动失败。您仍可以进行聊天交互。',
          jobId: result.job_id,
        })
      }
      */

      // 注意：成功消息和弹窗关闭逻辑已移至WebSocket连接成功后处理

    } catch (error) {
      console.error('上传失败:', error)
      
      // 重置WebSocket连接状态
      setIsConnectingWebSocket(false)
      
      // 清理进度定时器
      if (progressInterval) {
        clearInterval(progressInterval)
        setProgressInterval(null)
      }
      
      // 停止打字状态
      setIsTyping(false)
      
      // 更新文件状态为失败，重置进度为0
      setFiles(prev => prev.map(f => ({ 
        ...f, 
        status: 'error' as const,
        progress: 0,
        errorMessage: error instanceof Error ? error.message : '上传失败'
      })))
      
      message.error('文件上传失败，请重试')
    } finally {
      setUploading(false)
    }
  }

  const handleCancel = () => {
    if (uploading) {
      message.warning('正在上传中，请稍候...')
      return
    }
    
    // 如果正在连接WebSocket，禁止关闭
    if (isConnectingWebSocket) {
      message.warning('正在建立连接，请稍候...')
      return
    }
    
    // 如果有活跃的连接，提示用户
    if (isConnected && currentJobId) {
      antdMessage.info('WebSocket 连接将在后台继续运行，进度消息会显示在聊天区域')
    }
    
    // 清理定时器
    if (progressInterval) {
      clearInterval(progressInterval)
      setProgressInterval(null)
    }
    
    // 重置上传相关状态，但保留连接
    setFiles([])
    onClose()
  }



  return (
    <Modal
      title={
        <Flex align="center" gap={8}>
          <CloudUploadOutlined style={{ color: token.colorPrimary }} />
          <span>上传CAD文件</span>
        </Flex>
      }
      open={visible}
      onCancel={isConnectingWebSocket ? undefined : handleCancel}
      footer={[
        <Button key="cancel" onClick={handleCancel} disabled={uploading || isConnectingWebSocket}>
          取消
        </Button>,
        <Button 
          key="upload" 
          type="primary" 
          onClick={handleUpload}
          loading={uploading}
          disabled={files.length === 0 || !!currentJobId}
          style={{
            background: token.colorPrimary,
            borderColor: token.colorPrimary,
          }}
        >
          {uploading ? '上传中...' : (isConnectingWebSocket ? '连接中...' : (currentJobId ? '已上传' : '开始上传'))}
        </Button>,
      ]}
      width={700}
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }} size={24}>
        {/* 上传区域 */}
        <div style={{ position: 'relative' }}>
          <div
            {...(uploading ? {} : getRootProps())}
            style={{
              position: 'relative',
              cursor: uploading ? 'not-allowed' : 'pointer',
              outline: 'none', // 移除焦点轮廓
            }}
          >
            {!uploading && <input {...getInputProps()} />}
            <Card
              style={{
                border: `2px dashed ${
                  uploading 
                    ? token.colorBorderSecondary 
                    : (isDragActive || globalDragActive ? token.colorPrimary : token.colorBorder)
                }`,
                borderRadius: token.borderRadius,
                background: uploading 
                  ? token.colorFillQuaternary 
                  : (isDragActive || globalDragActive ? `${token.colorPrimary}08` : token.colorFillAlter),
                transition: 'all 0.3s ease',
                opacity: uploading ? 0.6 : 1,
                pointerEvents: uploading ? 'none' : 'auto',
                transform: (isDragActive || globalDragActive) && !uploading ? 'scale(1.02)' : 'scale(1)',
                boxShadow: (isDragActive || globalDragActive) && !uploading 
                  ? `0 8px 32px ${token.colorPrimary}20, 0 0 0 4px ${token.colorPrimary}10`
                  : '0 2px 8px rgba(0,0,0,0.06)',
                minHeight: '200px',
              }}
              styles={{ body: { padding: 40 } }}
              className={`${(isDragActive || globalDragActive) && !uploading ? 'dragover-active' : ''} ${uploading ? 'upload-disabled' : ''}`}
            >
              <Flex vertical align="center" gap={16}>
                <div style={{
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <InboxOutlined 
                    style={{ 
                      fontSize: 64, 
                      color: uploading 
                        ? token.colorTextDisabled 
                        : ((isDragActive || globalDragActive) ? token.colorPrimary : token.colorTextTertiary),
                      transition: 'all 0.3s ease',
                      transform: (isDragActive || globalDragActive) && !uploading ? 'scale(1.1) translateY(-4px)' : 'scale(1)',
                      filter: (isDragActive || globalDragActive) && !uploading ? 'drop-shadow(0 4px 12px rgba(22, 119, 255, 0.3))' : 'none',
                    }} 
                  />
                  {(isDragActive || globalDragActive) && !uploading && (
                    <div style={{
                      position: 'absolute',
                      inset: -8,
                      borderRadius: '50%',
                      background: `linear-gradient(45deg, ${token.colorPrimary}20, ${token.colorPrimary}10)`,
                      animation: 'pulse 1.5s ease-in-out infinite',
                    }} />
                  )}
                </div>
                <div style={{ textAlign: 'center' }}>
                  <Title level={4} style={{ 
                    margin: 0, 
                    marginBottom: 8,
                    color: uploading 
                      ? token.colorTextDisabled 
                      : ((isDragActive || globalDragActive) ? token.colorPrimary : undefined),
                    transition: 'all 0.3s ease',
                    transform: (isDragActive || globalDragActive) && !uploading ? 'translateY(-2px)' : 'translateY(0)',
                    fontWeight: (isDragActive || globalDragActive) && !uploading ? 600 : 500,
                  }}>
                    {uploading 
                      ? '正在上传中，请稍候...' 
                      : ((isDragActive || globalDragActive) ? '🎯 释放文件到此处' : '拖拽文件到此处，或点击选择文件')
                    }
                  </Title>
                  <Text type="secondary" style={{
                    color: uploading 
                      ? token.colorTextDisabled 
                      : ((isDragActive || globalDragActive) ? token.colorPrimary : undefined),
                    transition: 'all 0.3s ease',
                    opacity: (isDragActive || globalDragActive) && !uploading ? 0.8 : 1,
                  }}>
                    {uploading 
                      ? '上传完成后可以选择新文件'
                      : ((isDragActive || globalDragActive)
                        ? '支持 DWG、PRT 格式文件'
                        : '支持 DWG、PRT 格式，最多上传2个文件（1个DWG + 1个PRT 或 1个DWG）'
                      )
                    }
                  </Text>
                </div>
              </Flex>
            </Card>
          </div>
        </div>

        {/* 文件列表 */}
        {files.length > 0 && (
          <div>
            <Title level={5} style={{ marginBottom: 16 }}>
              已选择文件 ({files.length})
            </Title>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              {files.map(file => (
                <Card
                  key={file.id}
                  size="small"
                  style={{
                    border: `1px solid ${file.status === 'error' ? token.colorError : token.colorBorder}`,
                    borderRadius: token.borderRadius,
                    background: file.status === 'error' ? token.colorErrorBg : token.colorBgContainer,
                  }}
                >
                  <Flex align="center" gap={12}>
                    <FileOutlined 
                      style={{ 
                        fontSize: 20, 
                        color: file.status === 'error' ? token.colorError : token.colorTextSecondary,
                      }} 
                    />
                    
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ 
                        fontSize: 14, 
                        fontWeight: 500,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        marginBottom: 4,
                      }}>
                        {file.name}
                      </div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {formatFileSize(file.size)}
                      </Text>
                      
                      {file.status === 'uploading' && (
                        <Progress 
                          percent={Math.round(file.progress)} 
                          size="small" 
                          style={{ marginTop: 8 }}
                          strokeColor={token.colorPrimary}
                        />
                      )}
                      
                      {file.status === 'success' && (
                        <Progress 
                          percent={100} 
                          size="small" 
                          style={{ marginTop: 8 }}
                          strokeColor={token.colorSuccess}
                          status="success"
                        />
                      )}
                      
                      {file.status === 'error' && (
                        <div style={{ marginTop: 4 }}>
                          <Text type="danger" style={{ fontSize: 12, display: 'block' }}>
                            {file.errorMessage}
                          </Text>
                          <Button
                            type="link"
                            size="small"
                            onClick={handleUpload}
                            disabled={uploading}
                            style={{ 
                              padding: 0, 
                              height: 'auto', 
                              fontSize: 12,
                              color: token.colorPrimary 
                            }}
                          >
                            重新上传
                          </Button>
                        </div>
                      )}
                    </div>

                    {!uploading && (
                      <Button
                        type="text"
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={() => removeFile(file.id)}
                        style={{ color: token.colorTextTertiary }}
                        disabled={uploading}
                      />
                    )}
                  </Flex>
                </Card>
              ))}
            </Space>
          </div>
        )}
      </Space>
      
      <style>{`
        @keyframes pulse {
          0%, 100% { 
            transform: scale(1); 
            opacity: 0.6; 
          }
          50% { 
            transform: scale(1.05); 
            opacity: 0.3; 
          }
        }
        
        @keyframes bounce {
          0%, 20%, 50%, 80%, 100% {
            transform: translateY(0);
          }
          40% {
            transform: translateY(-4px);
          }
          60% {
            transform: translateY(-2px);
          }
        }
        
        @keyframes fadeIn {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }
        
        @keyframes scaleIn {
          from {
            transform: scale(0.9);
            opacity: 0;
          }
          to {
            transform: scale(1);
            opacity: 1;
          }
        }
        
        .dragover {
          animation: bounce 0.6s ease-in-out;
        }
        
        .upload-disabled {
          user-select: none;
        }
        
        /* 拖拽时的边框动画 */
        .dragover::before {
          content: '';
          position: absolute;
          inset: -2px;
          border-radius: inherit;
          background: linear-gradient(45deg, ${token.colorPrimary}, ${token.colorPrimary}80, ${token.colorPrimary});
          background-size: 200% 200%;
          animation: borderGlow 2s ease-in-out infinite;
          z-index: -1;
        }
        
        @keyframes borderGlow {
          0%, 100% {
            background-position: 0% 50%;
          }
          50% {
            background-position: 100% 50%;
          }
        }
        
        /* 区分不同拖拽状态的样式 */
        .dragover-active {
          animation: dragActive 0.6s ease-in-out;
        }
        
        .dragover-global {
          animation: dragGlobal 0.4s ease-in-out;
        }
        
        @keyframes dragActive {
          0%, 100% {
            transform: scale(1.02);
          }
          50% {
            transform: scale(1.04);
          }
        }
        
        @keyframes dragGlobal {
          0%, 100% {
            transform: scale(1.01);
          }
          50% {
            transform: scale(1.02);
          }
        }
      `}</style>
    </Modal>
  )
}

export default FileUpload

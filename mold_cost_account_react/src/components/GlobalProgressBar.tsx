import React, { useMemo, useState, useEffect, useRef } from 'react'
import { Progress, Typography, theme, Tooltip } from 'antd'
import { 
  CheckCircleOutlined, 
  LoadingOutlined, 
  CloseCircleOutlined,
  ScissorOutlined,
  SearchOutlined,
  CalculatorOutlined,
  ClockCircleOutlined,
  PlayCircleOutlined,
  SyncOutlined,
  FileTextOutlined,
  ToolOutlined,
  BarChartOutlined,
  ExclamationCircleOutlined,
  RocketOutlined,
  QuestionCircleOutlined,
  MinusCircleOutlined
} from '@ant-design/icons'

const { Text } = Typography

interface GlobalProgressBarProps {
  messages: any[]
  currentJobId?: string
  isTyping: boolean
}

const GlobalProgressBar: React.FC<GlobalProgressBarProps> = ({ 
  messages, 
  currentJobId,
  isTyping 
}) => {
  const { token } = theme.useToken()
  const [completedJobs, setCompletedJobs] = useState<Set<string>>(new Set())
  const hideTimerRef = useRef<NodeJS.Timeout | null>(null)
  // 记录每个任务的最大进度值，确保进度只能增加不能减少
  const maxProgressRef = useRef<Map<string, number>>(new Map())
  
  // 数字滚动动画状态
  const [displayProgress, setDisplayProgress] = useState(0)
  const animationFrameRef = useRef<number | null>(null)

  // 根据进度消息阶段获取对应图标（与 MessageList 保持一致）
  const getProgressIcon = (stage: string, progress: number, message: string, isFailed: boolean, isCompleted: boolean) => {
    const safeStage = stage || ''
    const safeMessage = (typeof message === 'string' ? message : '') || ''
    
    const iconStyle = { 
      fontSize: 16,
      color: isFailed ? token.colorError : isCompleted ? token.colorSuccess : token.colorPrimary 
    }

    // 优先处理失败状态
    if (isFailed) {
      return <ExclamationCircleOutlined style={{ ...iconStyle, color: token.colorError }} />
    }

    // 特殊处理：awaiting_confirm 阶段显示问号图标
    if (safeStage === 'awaiting_confirm' || safeMessage.includes('请检查结果并确认') || safeMessage.includes('等待确认')) {
      return <QuestionCircleOutlined style={{ ...iconStyle, color: token.colorWarning }} />
    }

    // 特殊处理：拆图阶段
    if (safeStage === 'cad_split_started' || 
        (safeMessage.includes('拆图') && safeMessage.includes('开始'))) {
      return <ScissorOutlined style={iconStyle} />
    }
    
    if (safeStage === 'cad_split_completed' || 
        (safeMessage.includes('拆图完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }
    
    // 特殊处理：特征识别阶段
    if (safeStage === 'feature_recognition_started' || 
        (safeMessage.includes('特征识别') && safeMessage.includes('开始'))) {
      return <SearchOutlined style={iconStyle} />
    }
    
    if (safeStage === 'feature_recognition_completed' || 
        (safeMessage.includes('特征识别完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }

    // 特殊处理：continuing 阶段（用户确认完成，继续执行）
    if (safeStage === 'continuing' || safeMessage.includes('用户确认完成') || safeMessage.includes('继续执行')) {
      return <PlayCircleOutlined style={iconStyle} />
    }

    // 特殊处理：价格计算阶段
    if (safeStage === 'pricing_started' || 
        (safeMessage.includes('计算价格') && safeMessage.includes('开始'))) {
      return <CalculatorOutlined style={iconStyle} />
    }
    
    if (safeStage === 'pricing_completed' || 
        (safeMessage.includes('价格计算完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }

    // 特殊处理：NC 时间计算阶段
    if (safeStage === 'nc_calculation_started' || 
        (safeMessage.includes('NC') && safeMessage.includes('时间计算') && safeMessage.includes('开始'))) {
      return <ClockCircleOutlined style={iconStyle} />
    }
    
    if (safeStage === 'nc_calculation_completed' || 
        (safeMessage.includes('NC') && safeMessage.includes('时间计算完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }

    // 特殊处理：跳过 NC 时间计算
    if (safeStage === 'nc_calculation_skipped' || 
        (safeMessage.includes('跳过') && safeMessage.includes('NC'))) {
      return <MinusCircleOutlined style={{ ...iconStyle, color: token.colorWarning }} />
    }

    // 根据消息内容判断
    if (safeMessage.includes('任务初始化') || safeMessage.includes('初始化') || safeStage === 'initializing') {
      return <RocketOutlined style={iconStyle} />
    }
    
    if (safeMessage.includes('计算价格') || safeMessage.includes('成本计算') || safeMessage.includes('价格')) {
      if (safeMessage.includes('完成')) {
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      }
      return <CalculatorOutlined style={iconStyle} />
    }
    
    if (safeMessage.includes('报表') || safeMessage.includes('生成')) {
      return <BarChartOutlined style={iconStyle} />
    }

    // 基于英文stage的判断
    switch (safeStage) {
      case 'initializing':
        return <RocketOutlined style={iconStyle} />
      case 'file_uploaded':
      case 'file_processing':
        return <FileTextOutlined style={iconStyle} />
      case 'cad_split_started':
        return <ScissorOutlined style={iconStyle} />
      case 'cad_split_completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      case 'feature_recognition_started':
        return <SearchOutlined style={iconStyle} />
      case 'feature_recognition_completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      case 'process_planning_started':
        return <ToolOutlined style={iconStyle} />
      case 'process_planning_completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      case 'pricing_started':
      case 'cost_calculation_started':
        return <CalculatorOutlined style={iconStyle} />
      case 'pricing_completed':
      case 'cost_calculation_completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      case 'report_generation_started':
        return <BarChartOutlined style={iconStyle} />
      case 'report_generation_completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      case 'completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      case 'error':
      case 'failed':
        return <ExclamationCircleOutlined style={{ ...iconStyle, color: token.colorError }} />
      default:
        return <LoadingOutlined style={iconStyle} />
    }
  }

  // 计算全局进度
  const globalProgress = useMemo(() => {
    // 只考虑当前任务的进度消息，并且必须有 progress 字段
    const progressMessages = messages.filter(
      msg => msg.type === 'progress' && 
             msg.jobId === currentJobId && 
             msg.progressData &&
             typeof msg.progressData.progress === 'number' // 必须有 progress 字段
    )

    if (progressMessages.length === 0) {
      return null
    }

    // console.log('🔍 GlobalProgressBar - 计算进度:', {
    //   currentJobId,
    //   totalMessages: messages.length,
    //   progressMessagesCount: progressMessages.length,
    //   progressValues: progressMessages.map(m => ({
    //     stage: m.progressData?.stage,
    //     progress: m.progressData?.progress,
    //     message: m.progressData?.message
    //   }))
    // })

    // 获取该任务的历史最大进度
    const maxProgress = maxProgressRef.current.get(currentJobId || '') || 0
    
    // 策略：优先使用最新的消息，但进度值使用历史最大值（确保进度条不回退）
    // 这样可以确保文字显示最新状态，但进度条保持递增
    const latestMessage = progressMessages[progressMessages.length - 1]
    const latestProgress = latestMessage.progressData?.progress || 0
    
    // 进度值：取最新进度和历史最大进度的较大值
    let progress = Math.max(latestProgress, maxProgress)
    
    // 特殊处理：检查是否有明确的完成标记
    // 如果有 stage 为 'completed' 或 progress 为 100 的消息，强制设置为 100%
    const hasCompletedStage = progressMessages.some(msg => 
      msg.progressData?.stage === 'completed' || 
      msg.progressData?.progress === 100
    )
    
    if (hasCompletedStage) {
      // console.log('✅ 检测到任务已完成，强制设置进度为 100%')
      progress = 100
      // 如果检测到完成状态，使用完成消息
      const completedMessage = progressMessages.find(msg => 
        msg.progressData?.stage === 'completed' || 
        msg.progressData?.progress === 100
      )
      if (completedMessage) {
        // 使用完成消息替换最新消息
        const finalStage = completedMessage.progressData?.stage || ''
        const finalMessage = completedMessage.progressData?.message || completedMessage.content || '处理中...'
        
        return {
          progress: 100,
          stage: finalStage,
          message: finalMessage,
          isCompleted: true,
          isFailed: false
        }
      }
    }
    
    // 更新最大进度
    if (currentJobId && progress > maxProgress) {
      maxProgressRef.current.set(currentJobId, progress)
    }

    // 使用最新消息的数据（文字内容）
    const finalStage = latestMessage.progressData?.stage || ''
    const finalMessage = latestMessage.progressData?.message || latestMessage.content || '处理中...'
    
    // 判断是否失败 - 更严格的判断，排除"失败0个"这种成功情况
    const isFailed = 
      // 阶段包含失败关键词
      finalStage?.toLowerCase().includes('failed') || 
      finalStage?.toLowerCase().includes('error') ||
      (finalStage?.includes('失败') && !finalStage?.includes('失败0个')) ||
      // 消息明确表示失败（排除"失败0个"、"失败: 0"等成功情况）
      (finalMessage?.includes('处理失败') && !finalMessage?.includes('失败0个') && !finalMessage?.includes('失败: 0')) || 
      (finalMessage?.includes('识别失败') && !finalMessage?.includes('失败0个') && !finalMessage?.includes('失败: 0')) || 
      (finalMessage?.includes('计算失败') && !finalMessage?.includes('失败0个') && !finalMessage?.includes('失败: 0')) ||
      (finalMessage?.includes('上传失败') && !finalMessage?.includes('失败0个') && !finalMessage?.includes('失败: 0')) ||
      (finalMessage?.includes('核算失败') && !finalMessage?.includes('失败0个') && !finalMessage?.includes('失败: 0')) ||
      finalMessage?.startsWith('错误：') ||
      finalMessage?.startsWith('失败：') ||
      finalMessage?.includes('Error:') ||
      finalMessage?.includes('Failed:')

    // 判断是否完成 - 只有进度达到 100 才算完成
    const isCompleted = progress >= 100

    return {
      progress: Math.min(progress, 100),
      stage: finalStage,
      message: finalMessage, // 使用最新消息的内容
      isCompleted,
      isFailed
    }
  }, [messages, currentJobId])

  // 数字滚动动画效果
  useEffect(() => {
    if (!globalProgress) {
      setDisplayProgress(0)
      return
    }

    const targetProgress = globalProgress.progress
    const startProgress = displayProgress
    const duration = 800 // 动画持续时间（毫秒）
    const startTime = Date.now()

    const animate = () => {
      const currentTime = Date.now()
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)

      // 使用缓动函数（easeOutCubic）
      const easeProgress = 1 - Math.pow(1 - progress, 3)
      const currentValue = startProgress + (targetProgress - startProgress) * easeProgress

      setDisplayProgress(currentValue)

      if (progress < 1) {
        animationFrameRef.current = requestAnimationFrame(animate)
      } else {
        setDisplayProgress(targetProgress)
      }
    }

    // 取消之前的动画
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current)
    }

    // 开始新动画
    animationFrameRef.current = requestAnimationFrame(animate)

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current)
      }
    }
  }, [globalProgress?.progress])

  // 处理完成后的自动隐藏 - 已禁用，进度条不再自动隐藏
  useEffect(() => {
    if (globalProgress && currentJobId) {
      // 清除之前的定时器
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current)
      }
      
      // 注释掉自动隐藏逻辑 - 进度条到100%后不自动消失
      // if (globalProgress.isCompleted && globalProgress.progress >= 100) {
      //   console.log('✅ 进度达到100%，2秒后隐藏进度条')
      //   hideTimerRef.current = setTimeout(() => {
      //     setCompletedJobs(prev => new Set(prev).add(currentJobId))
      //     // 清理该任务的最大进度记录
      //     maxProgressRef.current.delete(currentJobId)
      //     console.log('🧹 清理任务进度记录:', currentJobId)
      //   }, 2000)
      // }
      // 失败时不自动隐藏，继续显示失败状态
      // else if (globalProgress.isFailed) {
      //   console.log('🔴 检测到失败，但保持显示进度条')
      // }
    }
    
    return () => {
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current)
      }
    }
  }, [globalProgress, currentJobId])

  // 如果没有进度数据，不显示
  if (!globalProgress) {
    return null
  }

  // 只有在进度达到100%时才会通过 completedJobs 隐藏
  // 失败状态会一直显示，不会自动隐藏

  return (
    <Tooltip 
      title={globalProgress.message || '处理中...'}
      placement="bottomRight"
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          position: 'relative',
        }}
      >
        <Progress
          type="circle"
          percent={displayProgress}
          status={
            globalProgress.isFailed 
              ? 'exception' 
              : globalProgress.isCompleted 
                ? 'success' 
                : 'active'
          }
          strokeColor={
            globalProgress.isFailed
              ? token.colorError
              : globalProgress.isCompleted 
                ? token.colorSuccess 
                : {
                    '0%': token.colorPrimary,
                    '100%': token.colorPrimaryActive,
                  }
          }
          size={36}
          strokeWidth={6}
          format={(percent) => (
            <span 
              style={{ 
                fontSize: 10, 
                fontWeight: 600,
                color: globalProgress.isFailed ? token.colorError : token.colorText,
                display: 'inline-block',
                transition: 'transform 0.2s ease',
              }}
              className="progress-number"
            >
              {Math.round(percent || 0)}%
            </span>
          )}
        />
      </div>
    </Tooltip>
  )
}

export default GlobalProgressBar

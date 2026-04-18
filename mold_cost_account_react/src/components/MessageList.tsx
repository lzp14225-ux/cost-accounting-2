import React, { useEffect, useRef, useState, useCallback } from 'react'
import { Card, Typography, Space, theme, Tag, Button, message as antdMessage } from 'antd'
import { 
  LoadingOutlined, 
  CheckCircleOutlined, 
  SyncOutlined, 
  ExclamationCircleOutlined,
  FileTextOutlined,
  ToolOutlined,
  DollarOutlined,
  BarChartOutlined,
  PlayCircleOutlined,
  ScissorOutlined,
  SearchOutlined,
  CalculatorOutlined,
  ClockCircleOutlined,
  RocketOutlined,
  QuestionCircleOutlined,
  MinusCircleOutlined,
  SoundOutlined,
  PauseCircleOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Message } from '../store/useAppStore'
import FileAttachmentDisplay from './FileAttachmentDisplay'
import AIAvatar from './AIAvatar'
import ReviewInterface from './ReviewInterface'
import ModificationCard from './ModificationCard'
import ReviewDataList from './ReviewDataList'
import MissingFieldsCard from './MissingFieldsCard'
import MessageDrawingViewer from './MessageDrawingViewer'
import { chatService } from '../services/chatService'
import { speechSynthesisService } from '../services/speechSynthesisService'
import { useAppStore } from '../store/useAppStore'
import { useCountdown } from '../hooks/useCountdown'
import { hasDrawingContent } from '../utils/drawingUtils'

const { Text } = Typography

// 语音播放按钮组件
interface VoicePlayButtonProps {
  messageId: string
  content: string
  isPlaying: boolean
  onPlay: () => void
  onStop: () => void
}

const VoicePlayButton: React.FC<VoicePlayButtonProps> = ({
  messageId,
  content,
  isPlaying,
  onPlay,
  onStop,
}) => {
  const { token } = theme.useToken()

  return (
    <Button
      type="text"
      size="small"
      icon={isPlaying ? <PauseCircleOutlined /> : <SoundOutlined />}
      onClick={isPlaying ? onStop : onPlay}
      style={{
        color: isPlaying ? token.colorPrimary : token.colorTextSecondary,
        padding: '4px 8px',
        height: 28,
        fontSize: 14,
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        transition: 'all 0.2s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = token.colorPrimary
        e.currentTarget.style.background = token.colorFillQuaternary
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = isPlaying ? token.colorPrimary : token.colorTextSecondary
        e.currentTarget.style.background = 'transparent'
      }}
    >
      {isPlaying ? '停止播放' : '语音播放'}
    </Button>
  )
}

// 带倒计时的确认按钮组件
interface CountdownConfirmButtonProps {
  messageId: string
  messageTimestamp: number
  loading: boolean
  onConfirm: () => Promise<void> | void // 支持异步和同步
  children: React.ReactNode
  style?: React.CSSProperties
}

const CountdownConfirmButton: React.FC<CountdownConfirmButtonProps> = ({
  messageId,
  messageTimestamp,
  loading,
  onConfirm,
  children,
  style
}) => {
  const { token } = theme.useToken()
  
  // 计算消息创建后经过的时间
  const elapsedTime = Math.floor((Date.now() - messageTimestamp) / 1000)
  const remainingTime = Math.max(0, 300 - elapsedTime) // 5分钟 = 300秒
  
  const { timeLeft, isExpired, formatTime, pause, resume } = useCountdown({
    initialTime: remainingTime,
    onExpired: () => {
      console.log(`确认按钮已过期: ${messageId}`)
    }
  })

  // 处理点击事件
  const handleClick = async () => {
    pause() // 暂停倒计时
    
    try {
      await onConfirm()
      // 确认成功，不需要恢复倒计时
    } catch (error) {
      // 请求失败，恢复倒计时
      resume()
      throw error // 重新抛出错误，让外部处理
    }
  }

  // 如果已过期，不渲染按钮
  if (isExpired) {
    return (
      <div style={{ 
        padding: '8px 12px',
        background: token.colorFillQuaternary,
        borderRadius: 6,
        textAlign: 'center'
      }}>
        <Space>
          <ClockCircleOutlined style={{ color: token.colorTextTertiary }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            确认时间已过期
          </Text>
        </Space>
      </div>
    )
  }

  return (
    <Button
      type="primary"
      size="middle"
      loading={loading}
      onClick={handleClick}
      style={{
        borderRadius: 6,
        fontWeight: 500,
        height: 36,
        padding: '0 24px',
        ...style
      }}
    >
      <Space size={8}>
        <span>{children}</span>
        <span style={{ 
          fontSize: 12, 
          opacity: 0.8,
          fontWeight: 400
        }}>
          ({formatTime(timeLeft)})
        </span>
      </Space>
    </Button>
  )
}

interface MessageListProps {
  messages: Message[]
  isTyping: boolean
  scrollContainerRef?: React.RefObject<HTMLDivElement>
}

const MessageList: React.FC<MessageListProps> = ({ messages, isTyping, scrollContainerRef: externalScrollRef }) => {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = externalScrollRef || useRef<HTMLDivElement>(null)
  const [isInitialLoad, setIsInitialLoad] = useState(true)
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true)
  const lastMessageCountRef = useRef(0)
  const initializedRef = useRef(false) // 添加初始化标记
  const lastScrollTimeRef = useRef(0) // 添加滚动时间戳，用于节流
  const lastJobIdRef = useRef<string | undefined>() // 添加 jobId 追踪，用于检测会话切换
  const { token } = theme.useToken()
  const {
    setMessages,
    addMessage,
    setIsCalculating,
    setIsTyping,
    setIsRefreshing,
    setIsReprocessing,
    setIsWaitingForReply,
  } = useAppStore()
  const [confirmingMessageId, setConfirmingMessageId] = useState<string | null>(null)
  const [playingMessageId, setPlayingMessageId] = useState<string | null>(null) // 当前正在播放语音的消息ID

  // 检测会话切换或消息列表完全替换（如加载历史消息）
  useEffect(() => {
    // 获取当前消息列表的第一条消息的 jobId
    const currentJobId = messages.length > 0 ? messages[0]?.jobId : undefined
    
    // 如果 jobId 发生变化，说明切换了会话，需要重置初始化状态
    if (currentJobId !== lastJobIdRef.current) {
      // console.log('🔄 检测到会话切换，重置滚动状态', {
      //   oldJobId: lastJobIdRef.current,
      //   newJobId: currentJobId,
      //   messageCount: messages.length
      // })
      
      lastJobIdRef.current = currentJobId
      initializedRef.current = false
      setIsInitialLoad(true)
      lastMessageCountRef.current = 0
    }
  }, [messages])

  // 处理确认操作
  const handleConfirm = async (messageId: string, jobId?: string, intent?: string) => {
    if (!jobId) {
      antdMessage.error('缺少任务ID');
      return;
    }

    setConfirmingMessageId(messageId);

    // 如果是重新识别或重新计算，立即禁用发送按钮
    if (
      intent === 'FEATURE_RECOGNITION' ||
      intent === 'PRICE_CALCULATION' ||
      intent === 'WEIGHT_PRICE_CALCULATION'
    ) {
      setIsReprocessing(true);
    }

    try {
      // 调用确认接口，传递 comment 参数
      const result = await chatService.confirmModification(jobId, '确认操作');
      
      // 更新消息状态，标记为已确认，并添加确认状态
      setMessages((prevMessages) => {
        const currentMessages = Array.isArray(prevMessages) ? prevMessages : [];
        return currentMessages.map((msg) => {
          const isCurrentMessage = msg.id === messageId;
          const isSamePendingIntent =
            !!jobId &&
            msg.jobId === jobId &&
            !msg.id.startsWith('history-') &&
            msg.requiresConfirmation === true &&
            !msg.confirmationStatus &&
            ((intent === 'DATA_MODIFICATION' && ((msg as any).modificationData || msg.intent === 'DATA_MODIFICATION')) ||
              (intent !== 'DATA_MODIFICATION' && msg.intent === intent));

          if (!isCurrentMessage && !isSamePendingIntent) {
            return msg;
          }

          return {
            ...msg,
            requiresConfirmation: false,
            confirmationStatus: 'confirmed' as const
          };
        });
      });

      // 不再添加确认成功的系统消息，等待 WebSocket 推送
      // WebSocket 会推送相关的状态消息

      // 根据意图类型决定是否立即调用 refresh 接口
      // FEATURE_RECOGNITION 和 PRICE_CALCULATION 需要等待 WebSocket 完成消息
      // DATA_MODIFICATION 由后端确认成功后自动 refresh，只有自动刷新失败才补手动 refresh
      if (intent === 'DATA_MODIFICATION') {
        try {
          setIsWaitingForReply(false);

          const autoRefreshStatus = result?.data?.auto_refresh_status;
          if (autoRefreshStatus !== 'ok') {
            setIsRefreshing(true);
            await chatService.refreshReview(jobId);
            // WebSocket 会自动推送数据（review_display_view 或 completion_request）
          }
        } catch (refreshError) {
          console.error('❌ 刷新数据失败:', refreshError);
          // 刷新失败不影响主流程，只记录错误
        } finally {
          setIsRefreshing(false);
        }
      } else if (intent === 'FEATURE_RECOGNITION') {
        console.log('⏳ 特征识别确认成功，等待 WebSocket 返回 feature_recognition_completed 消息后再刷新');
        // 不立即调用 refresh，等待 WebSocket 推送 feature_recognition_completed
      } else if (intent === 'PRICE_CALCULATION') {
        console.log('⏳ 价格计算确认成功，等待 WebSocket 返回 pricing_completed 消息后再刷新');
        // 不立即调用 refresh，等待 WebSocket 推送 pricing_completed
      } else if (intent === 'WEIGHT_PRICE_CALCULATION') {
        try {
          const autoRefreshStatus = result?.data?.auto_refresh_status;
          if (autoRefreshStatus !== 'ok') {
            setIsRefreshing(true);
            await chatService.refreshReview(jobId);
          }
        } catch (refreshError) {
          console.error('按重量计算后刷新审核数据失败:', refreshError);
        } finally {
          setIsRefreshing(false);
          setIsReprocessing(false);
        }
      }

      // 所有类型的确认操作都不显示 AI 头像和旋转等待图标
      setIsTyping(false);

      antdMessage.success('操作已确认');

    } catch (error: any) {
      console.error('确认操作失败:', error);
      
      // 如果是重新识别或重新计算，确认失败时恢复发送按钮
      if (
        intent === 'FEATURE_RECOGNITION' ||
        intent === 'PRICE_CALCULATION' ||
        intent === 'WEIGHT_PRICE_CALCULATION'
      ) {
        setIsReprocessing(false);
        console.log('🔓 确认失败，恢复发送按钮');
      }
      
      // 如果不是 Network Error，则显示错误消息
      if (error.message !== 'Network Error') {
        antdMessage.error(error.message || '确认操作失败');
      }
      // 确认失败时也要重置 typing 状态
      setIsTyping(false);
      // 重新抛出错误，让CountdownConfirmButton的handleClick能够捕获并恢复倒计时
      throw error;
    } finally {
      setConfirmingMessageId(null);
    }
  };

  // 处理语音播放
  const handleVoicePlay = useCallback(async (messageId: string, content: string) => {
    // 如果当前消息正在播放，则停止
    if (playingMessageId === messageId) {
      speechSynthesisService.stopPlayback()
      setPlayingMessageId(null)
      return
    }

    // 停止之前正在播放的语音
    if (playingMessageId) {
      speechSynthesisService.stopPlayback()
    }

    // 开始播放新的语音
    setPlayingMessageId(messageId)

    try {
      await speechSynthesisService.startSynthesis(content, {
        onStart: () => {
          console.log('🔊 开始语音合成:', messageId)
        },
        onComplete: () => {
          console.log('✅ 语音合成完成:', messageId)
          // 播放完成后重置状态，恢复按钮为"语音播放"
          setPlayingMessageId(null)
        },
        onError: (error) => {
          console.error('❌ 语音合成失败:', error)
          antdMessage.error(`语音播放失败: ${error}`)
          setPlayingMessageId(null)
        },
      })
    } catch (error: any) {
      console.error('❌ 语音播放失败:', error)
      setPlayingMessageId(null)
    }
  }, [playingMessageId])

  // 处理停止语音播放
  const handleVoiceStop = useCallback(() => {
    speechSynthesisService.stopPlayback()
    setPlayingMessageId(null)
  }, [])

  // 组件卸载时停止播放
  useEffect(() => {
    return () => {
      speechSynthesisService.stopPlayback()
    }
  }, [])

  // 监听新的 assistant 消息，自动播放语音
  const lastAssistantMessageIdRef = useRef<string | null>(null)
  
  useEffect(() => {
    // 如果没有消息，直接返回
    if (messages.length === 0) return

    // 获取最后一条消息
    const lastMessage = messages[messages.length - 1]

    // 检查是否是新的 assistant 消息
    if (
      lastMessage.type === 'assistant' &&
      lastMessage.content &&
      lastMessage.content.trim() &&
      lastMessage.id !== lastAssistantMessageIdRef.current && // 确保是新消息
      !playingMessageId // 当前没有正在播放的语音
    ) {
      // 更新最后一条 assistant 消息的 ID
      lastAssistantMessageIdRef.current = lastMessage.id

      // 延迟一小段时间后自动播放，确保消息已经渲染
      const timer = setTimeout(() => {
        handleVoicePlay(lastMessage.id, lastMessage.content)
      }, 300) // 300ms 延迟，确保消息渲染完成

      return () => clearTimeout(timer)
    }
  }, [messages, playingMessageId, handleVoicePlay]) // 依赖 messages、playingMessageId 和 handleVoicePlay

  // 根据进度消息阶段获取对应图标
  const getProgressIcon = (stage: string, progress: number, message: string, allMessages: Message[], currentIndex: number) => {
    // 添加安全检查
    const safeStage = stage || ''
    const safeMessage = (typeof message === 'string' ? message : '') || ''
    
    // 判断是否为完成状态：阶段名包含"completed"或进度为100%
    const isCompleted = safeStage.includes('completed') || progress === 100
    
    // 判断是否为失败状态：阶段名包含"failed"，但排除"失败0个"这种成功的情况
    const isFailed = safeStage.includes('failed') || 
                     (safeMessage.includes('失败') && 
                      !safeMessage.includes('失败0个') && 
                      !safeMessage.includes('失败: 0') &&
                      !safeMessage.match(/失败\s*0\s*个/))
    
    // 检查是否有后续的进度消息，如果有则说明当前步骤已完成
    const hasLaterProgress = allMessages.slice(currentIndex + 1).some(msg => 
      msg.type === 'progress' && msg.progressData
    )
    
    // 基础图标样式（不根据完成状态改变颜色，保持原始颜色）
    const iconStyle = { 
      fontSize: 14, 
      marginRight: 8,
      color: token.colorPrimary 
    }

    // 优先处理失败状态：如果是失败状态，直接返回错误图标
    if (isFailed) {
      return <ExclamationCircleOutlined style={{ ...iconStyle, color: token.colorError }} />
    }

    // 特殊处理：awaiting_confirm 阶段显示问号图标，表示等待用户确认
    if (safeStage === 'awaiting_confirm' || safeMessage.includes('请检查结果并确认') || safeMessage.includes('等待确认')) {
      return <QuestionCircleOutlined style={{ ...iconStyle, color: token.colorWarning }} />
    }

    // 特殊处理：拆图和特征识别的 started 阶段使用语义图标
    if (safeStage === 'cad_split_started' || 
        (safeMessage.includes('拆图') && safeMessage.includes('开始'))) {
      // 拆图进行中：显示剪刀图标（不旋转）
      return <ScissorOutlined style={iconStyle} />
    }
    
    // 拆图完成：显示对号图标
    if (safeStage === 'cad_split_completed' || 
        (safeMessage.includes('拆图完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }
    
    if (safeStage === 'feature_recognition_started' || 
        (safeMessage.includes('特征识别') && safeMessage.includes('开始'))) {
      // 特征识别进行中：显示搜索图标（不旋转）
      return <SearchOutlined style={iconStyle} />
    }
    
    // 特征识别完成：显示对号图标
    if (safeStage === 'feature_recognition_completed' || 
        (safeMessage.includes('特征识别完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }

    // 特殊处理：continuing 阶段（用户确认完成，继续执行）
    if (safeStage === 'continuing' || safeMessage.includes('用户确认完成') || safeMessage.includes('继续执行')) {
      return <PlayCircleOutlined style={iconStyle} />  // 继续执行：播放图标
    }

    // 特殊处理：pricing_started 阶段（正在计算价格）
    if (safeStage === 'pricing_started' || 
        (safeMessage.includes('计算价格') && safeMessage.includes('开始'))) {
      // 价格计算进行中：显示计算器图标（不旋转）
      return <CalculatorOutlined style={iconStyle} />
    }
    
    // 价格计算完成：显示对号图标
    if (safeStage === 'pricing_completed' || 
        (safeMessage.includes('价格计算完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }

    // 特殊处理：nc_calculation_started 阶段（NC 时间计算开始）
    if (safeStage === 'nc_calculation_started' || 
        (safeMessage.includes('NC') && safeMessage.includes('时间计算') && safeMessage.includes('开始'))) {
      // NC 时间计算进行中：显示时钟图标（不旋转）
      return <ClockCircleOutlined style={iconStyle} />
    }
    
    // NC 时间计算完成：显示对号图标
    if (safeStage === 'nc_calculation_completed' || 
        (safeMessage.includes('NC') && safeMessage.includes('时间计算完成'))) {
      return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
    }

    // 特殊处理：nc_calculation_skipped 阶段（跳过 NC 时间计算）
    if (safeStage === 'nc_calculation_skipped' || 
        (safeMessage.includes('跳过') && safeMessage.includes('NC'))) {
      // 跳过 NC 时间计算：显示减号圆圈图标，使用警告色
      return <MinusCircleOutlined style={{ ...iconStyle, color: token.colorWarning }} />
    }

    // 根据消息内容判断当前进行中的图标类型
    if (safeMessage.includes('任务初始化') || safeMessage.includes('初始化') || safeStage === 'initializing') {
      // 初始化阶段：始终显示火箭图标（不旋转，不变化）
      return <RocketOutlined style={iconStyle} />
    }
    
    
    if (safeMessage.includes('计算价格') || safeMessage.includes('成本计算') || safeMessage.includes('价格')) {
      // 检查是否完成
      if (safeMessage.includes('完成')) {
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />
      }
      // 显示计算器图标（不旋转）
      return <CalculatorOutlined style={iconStyle} />
    }
    
    if (safeMessage.includes('报表') || safeMessage.includes('生成')) {
      return <BarChartOutlined style={iconStyle} />
    }

    // 基于英文stage的判断（保留原有逻辑作为备用）
    switch (safeStage) {
      case 'initializing':
        return <RocketOutlined style={iconStyle} />  // 初始化：火箭图标（静态）
      case 'file_uploaded':
      case 'file_processing':
        return <FileTextOutlined style={iconStyle} />
      case 'cad_split_started':
        return <ScissorOutlined style={iconStyle} />  // 拆图进行中：剪刀图标（静态）
      case 'cad_split_completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />  // 拆图完成：对号图标
      case 'feature_recognition_started':
        return <SearchOutlined style={iconStyle} />  // 特征识别进行中：搜索图标（静态）
      case 'feature_recognition_completed':
        return <CheckCircleOutlined style={{ ...iconStyle, color: token.colorSuccess }} />  // 特征识别完成：对号图标
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
        // 对于未知阶段，显示默认的加载图标
        return <LoadingOutlined style={iconStyle} />
    }
  }

  // 检查是否接近底部
  const isNearBottom = useCallback(() => {
    if (!scrollContainerRef.current) return true
    
    const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current
    const threshold = 100 // 100px阈值
    return scrollHeight - scrollTop - clientHeight < threshold
  }, [])

  // 平滑滚动到底部
  const scrollToBottom = useCallback((smooth = true) => {
    if (!messagesEndRef.current) {
      console.log('❌ messagesEndRef.current 不存在')
      return
    }
    
    // 检查是否真的需要滚动
    if (scrollContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 10
      
      // 如果已经在底部附近，不需要滚动
      if (isAtBottom && smooth) {
        return
      }
    }
    
    // 使用 scrollTop 直接滚动到底部，确保完全贴底
    if (scrollContainerRef.current) {
      const container = scrollContainerRef.current
      if (smooth) {
        container.scrollTo({
          top: container.scrollHeight,
          behavior: 'smooth'
        })
      } else {
        container.scrollTop = container.scrollHeight
      }
    }
  }, [])

  // 处理滚动事件
  const handleScroll = useCallback(() => {
    setShouldAutoScroll(isNearBottom())
  }, [isNearBottom])

  // 初始化时不使用动画滚动到底部
  useEffect(() => {
    if (isInitialLoad && messages.length > 0 && !initializedRef.current) {
      initializedRef.current = true
      
      // 使用 requestAnimationFrame 确保 DOM 已渲染
      requestAnimationFrame(() => {
        scrollToBottom(false) // 初始加载时不使用动画
        // 延迟设置 isInitialLoad，确保初始滚动完成
        setTimeout(() => {
          setIsInitialLoad(false)
          // 初始化完成后，更新 lastMessageCountRef，避免触发新消息滚动
          lastMessageCountRef.current = messages.length
        }, 100)
      })
    }
  }, [messages.length, isInitialLoad, scrollToBottom])

  // 新消息时的自动滚动
  useEffect(() => {
    // 只有在非初始加载且有新消息时才自动滚动
    if (!isInitialLoad && messages.length > lastMessageCountRef.current) {
      // 检查最后一条消息是否是用户消息
      const lastMessage = messages[messages.length - 1]
      const isUserMessage = lastMessage?.type === 'user'
      const isProgressMessage = lastMessage?.type === 'progress'
      
      // 用户发送消息时强制滚动到底部，其他情况只在底部附近时滚动
      if (isUserMessage || shouldAutoScroll) {
        // 检查是否是包含表格的进度消息（需要更长的渲染时间）
        const hasTable = isProgressMessage && lastMessage.progressData?.type === 'review_display_view'
        const delay = hasTable ? 300 : 150 // 表格需要更长的延迟
        
        // 使用 requestAnimationFrame + setTimeout 确保 DOM 完全渲染
        requestAnimationFrame(() => {
          setTimeout(() => {
            scrollToBottom(true) // 新消息时使用平滑滚动
          }, delay)
        })
      } else {
        console.log('❌ 不滚动 - 用户不在底部')
      }
    }
    lastMessageCountRef.current = messages.length
  }, [messages, isTyping, isInitialLoad, shouldAutoScroll, scrollToBottom])

  // AI 流式回复时的自动滚动（带节流）
  useEffect(() => {
    // 当 AI 正在打字且用户在底部附近时，持续滚动
    if (isTyping && !isInitialLoad && shouldAutoScroll) {
      const now = Date.now()
      // 节流：每 100ms 最多滚动一次
      if (now - lastScrollTimeRef.current > 100) {
        lastScrollTimeRef.current = now
        requestAnimationFrame(() => {
          scrollToBottom(true)
        })
      }
    }
  }, [messages, isTyping, isInitialLoad, shouldAutoScroll, scrollToBottom])

  // AI 回复完成后确保滚动到底部
  useEffect(() => {
    // 当 isTyping 从 true 变为 false 时（AI 回复完成），强制滚动到底部
    // 但只有在非初始加载且有真正的新消息时才滚动
    if (!isTyping && !isInitialLoad && messages.length > 0 && messages.length > lastMessageCountRef.current) {
      const lastMessage = messages[messages.length - 1]
      // 如果最后一条消息是 AI 消息，确保滚动到底部
      if (lastMessage?.type === 'assistant' || lastMessage?.type === 'progress') {
        // 检查是否包含表格或复杂内容
        const hasTable = lastMessage.type === 'progress' && 
                        lastMessage.progressData?.type === 'review_display_view'
        const hasMissingFields = lastMessage.type === 'assistant' && 
                                lastMessage.missingFieldsData
        const delay = (hasTable || hasMissingFields) ? 400 : 200 // 复杂内容需要更长延迟
        
        requestAnimationFrame(() => {
          setTimeout(() => {
            scrollToBottom(true)
            
            // 额外的保险机制：再次检查并滚动（针对复杂内容）
            if (hasTable || hasMissingFields) {
              setTimeout(() => {
                if (scrollContainerRef.current) {
                  const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current
                  const distanceFromBottom = scrollHeight - scrollTop - clientHeight
                  
                  // 如果距离底部超过 50px，再次滚动
                  if (distanceFromBottom > 50) {
                    scrollToBottom(true)
                  }
                }
              }, 200) // 再等待 200ms 后检查
            }
          }, delay)
        })
      }
    }
  }, [isTyping, isInitialLoad, messages, scrollToBottom])

  // 添加滚动监听
  useEffect(() => {
    const container = scrollContainerRef.current
    if (container) {
      container.addEventListener('scroll', handleScroll, { passive: true })
      return () => container.removeEventListener('scroll', handleScroll)
    }
  }, [handleScroll])

  const renderMessage = (message: Message, index: number) => {
    const isUser = message.type === 'user'
    const isSystem = message.type === 'system'
    const isProgress = message.type === 'progress'
    const isAssistant = message.type === 'assistant'
    const laterMessages = messages.slice(index + 1)
    const hasLaterStartedOrCompletedStageForSameJob = laterMessages.some(nextMessage => {
      if (nextMessage.jobId !== message.jobId || nextMessage.type !== 'progress') {
        return false
      }

      const nextStage = nextMessage.progressData?.stage

      if (message.intent === 'PRICE_CALCULATION') {
        return nextStage === 'pricing_started' || nextStage === 'pricing_completed' || nextStage === 'completed'
      }

      if (message.intent === 'FEATURE_RECOGNITION') {
        return nextStage === 'feature_recognition_started' || nextStage === 'feature_recognition_completed' || nextStage === 'awaiting_confirm' || nextStage === 'completed'
      }

      if (message.intent === 'WEIGHT_PRICE_CALCULATION') {
        return nextStage === 'cost_calculation_started' || nextStage === 'cost_calculation_completed' || nextStage === 'completed'
      }

      return false
    })
    
    // 检查是否是最新的 AI 消息 - 需要考虑正在打字的状态
    const isLatestAIMessage = (isAssistant || isProgress) && (
      index === messages.length - 1 || // 是最后一条消息
      (isTyping && index === messages.length - 1) // 或者正在打字且是最后一条AI消息
    )
    
    // 检查是否应该显示头像
    let showAvatar = false
    if (isAssistant || isProgress) {
      // 如果消息包含缺少必填字段数据，不显示头像
      if (message.missingFieldsData) {
        showAvatar = false
      } else if (isProgress) {
        // 对于进度消息，检查是否是特定的重要阶段
        const stage = message.progressData?.stage || ''
        
        // 检查是否是 continuing 或 pricing_started
        if (stage === 'continuing') {
          // continuing 始终显示头像
          showAvatar = true
        } else if (stage === 'pricing_started') {
          // pricing_started 始终不显示头像（重新计算场景）
          showAvatar = false
        } else {
          // 其他进度消息使用默认逻辑
          if (index > 0) {
            const prevMessage = messages[index - 1]
            showAvatar = prevMessage.type === 'user' || prevMessage.type === 'system'
          } else {
            showAvatar = true
          }
        }
      } else if (isAssistant) {
        // 助手消息：只在AI消息序列的第一条显示
        if (index > 0) {
          const prevMessage = messages[index - 1]
          showAvatar = prevMessage.type === 'user' || prevMessage.type === 'system'
        } else {
          showAvatar = true
        }
      }
    }

    // 进度消息的特殊渲染
    if (isProgress && message.progressData) {
      const stage = message.progressData.stage || 'processing'
      const progress = message.progressData.progress || 0
      let progressMessage = message.progressData.message || message.content || '处理中...'
      
      // 对于失败消息，只显示简洁的错误信息，不显示技术细节
      if (stage.includes('_failed')) {
        // 提取冒号前的简洁错误描述
        const colonIndex = progressMessage.indexOf(':')
        if (colonIndex > 0) {
          progressMessage = progressMessage.substring(0, colonIndex)
        }
      }
      
      // 检查是否是审核数据展示类型
      const isReviewDisplayView = (message.progressData as any).type === 'review_display_view'
      const reviewData = isReviewDisplayView ? (message.progressData as any).data : null

      // 如果当前只是单独的 awaiting_confirm 提示，且相邻位置已经有审核表格消息，则隐藏这条重复提示。
      if (stage === 'awaiting_confirm' && !isReviewDisplayView) {
        const hasAnyReviewTable = messages.some(candidateMessage =>
          (candidateMessage.type === 'progress' && candidateMessage.progressData?.type === 'review_display_view') ||
          (candidateMessage.type === 'system' && Array.isArray(candidateMessage.reviewData))
        )

        if (hasAnyReviewTable) {
          return null
        }
      }
      
      // 检查是否是阶段的开始（started）或完成（completed）
      const isStageStart = stage.includes('_started')
      const isStageComplete = stage.includes('_completed')
      
      // 检查下一条消息是否是不同阶段的开始（需要添加分隔线）
      const nextMessage = messages[index + 1]
      const shouldShowDivider = nextMessage && 
        nextMessage.type === 'progress' && 
        nextMessage.progressData &&
        (nextMessage.progressData.stage || '').includes('_started') &&
        isStageComplete
      
      return (
        <div 
          key={message.id} 
          style={{ 
            marginBottom: shouldShowDivider ? 0 : 8,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'flex-start',
          }}
        >
          <div style={{ 
            display: 'flex',
            justifyContent: 'flex-start',
          }}>
            <div style={{ 
              maxWidth: isReviewDisplayView ? '100%' : '85%',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 12,
            }}>
              {showAvatar && (
                <div style={{ marginTop: -16 }}>
                  <AIAvatar 
                    size={32} 
                    isTyping={isTyping && isLatestAIMessage} 
                    isLatest={isLatestAIMessage}
                  />
                </div>
              )}
              
              {/* 当不显示头像时，添加占位空间以保持对齐 */}
              {!showAvatar && (
                <div style={{ width: 48, flexShrink: 0 }} />
              )}
              
              <div style={{ 
                flex: 1, 
                minWidth: 0,
                padding: '8px 0',
              }}>
                {!isReviewDisplayView ? (
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    fontSize: 14,
                    color: token.colorText,
                  }}>
                    {getProgressIcon(stage, progress, progressMessage, messages, index)}
                    <Text style={{ color: token.colorText }}>
                      {progressMessage}
                    </Text>
                  </div>
                ) : (
                  <>
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      fontSize: 14,
                      color: token.colorText,
                      marginBottom: 12,
                    }}>
                      {getProgressIcon(stage, progress, progressMessage, messages, index)}
                      <Text style={{ color: token.colorText }}>
                        {progressMessage}
                      </Text>
                    </div>
                    {reviewData && Array.isArray(reviewData) && (
                      <ReviewDataList data={reviewData} jobId={message.jobId || ''} />
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
          
          {/* 阶段分隔线 */}
          {(shouldShowDivider || stage === 'feature_recognition_completed' || stage === 'cad_split_completed' || stage === 'nc_calculation_skipped' || stage === 'nc_calculation_started' || stage === 'nc_calculation_completed') && (
            <div style={{ 
              display: 'flex',
              alignItems: 'center',
              margin: '12px 0',
              paddingLeft: 44, // 与消息内容对齐
            }}>
              <hr style={{
                flex: 1,
                border: 'none',
                borderTop: `1px solid ${token.colorBorderSecondary}`,
                margin: 0,
              }} />
            </div>
          )}
        </div>
      )
    }

    // 审核数据展示消息（从历史记录加载）
    if (message.type === 'system' && message.reviewData && Array.isArray(message.reviewData)) {
      return (
        <div 
          key={message.id} 
          style={{ 
            marginBottom: 12,
            display: 'flex',
            justifyContent: 'flex-start',
          }}
        >
          <div style={{ 
            maxWidth: '100%',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
          }}>
            {showAvatar && (
              <div style={{ marginTop: -16 }}>
                <AIAvatar 
                  size={32} 
                  isTyping={isTyping && isLatestAIMessage} 
                  isLatest={isLatestAIMessage}
                />
              </div>
            )}
            
            {!showAvatar && (
              <div style={{ width: 48, flexShrink: 0 }} />
            )}
            
            <div style={{ 
              flex: 1, 
              minWidth: 0,
              padding: '8px 0',
            }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                fontSize: 14,
                color: token.colorText,
                marginBottom: 12,
              }}>
                <QuestionCircleOutlined style={{ fontSize: 14, marginRight: 8, color: token.colorWarning }} />
                <Text style={{ color: token.colorText }}>
                  请检查结果并确认
                </Text>
              </div>
              <ReviewDataList data={message.reviewData} jobId={message.jobId || ''} />
            </div>
          </div>
        </div>
      )
    }

    // 审核数据消息的特殊渲染
    if (message.type === 'system' && message.content && message.content.includes('特征识别完成！审核流程已启动')) {
      return (
        <div 
          key={message.id} 
          style={{ 
            marginBottom: 12,
            display: 'flex',
            justifyContent: 'flex-start',
          }}
        >
          <div style={{ 
            maxWidth: '100%',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
          }}>
            {showAvatar && (
              <div style={{ marginTop: -16 }}>
                <AIAvatar 
                  size={32} 
                  isTyping={isTyping && isLatestAIMessage} 
                  isLatest={isLatestAIMessage}
                />
              </div>
            )}
            
            {!showAvatar && (
              <div style={{ width: 48, flexShrink: 0 }} />
            )}
            
            <div style={{ flex: 1, minWidth: 0 }}>
              <Card
                size="small"
                style={{
                  background: token.colorInfoBg,
                  border: `1px solid ${token.colorInfoBorder}`,
                  borderRadius: token.borderRadius,
                  marginBottom: 16,
                }}
                styles={{ body: { padding: '8px 12px' } }}
              >
                <Text style={{ 
                  fontSize: 13,
                  color: token.colorInfo,
                  fontStyle: 'italic',
                }}>
                  {message.content}
                </Text>
              </Card>
              
              {/* 显示审核界面 */}
              {message.jobId && (
                <ReviewInterface
                  jobId={message.jobId}
                  onModificationSubmitted={(changes) => {
                    console.log('修改已提交:', changes)
                  }}
                  onReviewCompleted={() => {
                    console.log('审核已完成')
                  }}
                />
              )}
            </div>
          </div>
        </div>
      )
    }

    // 修改确认消息的特殊渲染（历史消息中不显示）
    if (
      message.type === 'system' &&
      (message as any).modificationData &&
      !message.id.startsWith('history-') &&
      message.confirmationStatus !== 'confirmed'
    ) {
      const modificationData = (message as any).modificationData
      
      return (
        <div 
          key={message.id} 
          style={{ 
            marginBottom: 12,
            display: 'flex',
            justifyContent: 'flex-start',
          }}
        >
          <div style={{ 
            maxWidth: '100%',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
          }}>
            {showAvatar && (
              <div style={{ marginTop: -16 }}>
                <AIAvatar 
                  size={32} 
                  isTyping={isTyping && isLatestAIMessage} 
                  isLatest={isLatestAIMessage}
                />
              </div>
            )}
            
            {!showAvatar && (
              <div style={{ width: 48, flexShrink: 0 }} />
            )}
            
            <div style={{ flex: 1, minWidth: 0 }}>
              <ModificationCard
                modificationId={modificationData.modification_id}
                changes={modificationData.parsed_changes}
                onConfirm={async () => {
                  if (message.jobId) {
                    await handleConfirm(message.id, message.jobId, 'DATA_MODIFICATION')
                  }
                }}
              />
            </div>
          </div>
        </div>
      )
    }

    return (
      <div 
        key={message.id} 
        style={{ 
          marginBottom: isUser ? 12 : 40, // AI消息40px下边距，用户消息12px
          marginTop: isUser ? 0 : 30, // AI消息添加30px上边距
          display: 'flex',
          justifyContent: isUser ? 'flex-end' : 'flex-start',
        }}
      >
        <div style={{ 
          maxWidth: isUser ? '80%' : '100%', // AI消息100%，用户消息80%
          display: 'flex',
          flexDirection: isUser ? 'row-reverse' : 'row',
          alignItems: 'flex-start',
          gap: 12,
        }}>
          {showAvatar && (
            <div style={{ marginTop: -16 }}>
              <AIAvatar 
                size={32} 
                isTyping={isTyping && isLatestAIMessage} 
                isLatest={isLatestAIMessage}
              />
            </div>
          )}
          
          {/* 当AI消息或系统消息不显示头像时，添加占位空间以保持对齐 */}
          {(isAssistant || isSystem) && !showAvatar && (
            <div style={{ width: 48, flexShrink: 0 }} />
          )}
          
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* 用户消息的文件附件 - 显示在文字上方，不使用Card */}
            {isUser && message.attachments && message.attachments.length > 0 && (
              <div style={{ marginBottom: message.content.trim() ? 8 : 0 }}>
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {message.attachments.map((file) => (
                    <FileAttachmentDisplay key={file.id} file={file} />
                  ))}
                </Space>
              </div>
            )}
            
            {/* 只有在有内容时才显示消息卡片 */}
            {/* 排除"请确认以下修改："这类应该由ModificationCard显示的内容 */}
            {message.content.trim() && !message.content.includes('请确认以下修改') && (
              <>
                {isSystem ? (
                  <Card
                    size="small"
                    style={{
                      background: token.colorInfoBg,
                      border: `1px solid ${token.colorInfoBorder}`,
                      borderRadius: token.borderRadius,
                    }}
                    styles={{ body: { padding: '8px 12px' } }}
                  >
                    <Text style={{ 
                      fontSize: 13,
                      color: token.colorInfo,
                      fontStyle: 'italic',
                    }}>
                      {message.content}
                    </Text>
                  </Card>
                ) : isUser ? (
                  <Card
                    size="small"
                    style={{
                      background: '#F5F5F5',
                      border: 'none',
                      borderRadius: token.borderRadius,
                      boxShadow: 'none',
                    }}
                    styles={{ body: { padding: '10px 12px' } }}
                  >
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code({ className, children }) {
                          const match = /language-(\w+)/.exec(className || '')
                          const isInline = !match
                          
                          return isInline ? (
                            <Tag
                              style={{
                                background: token.colorFillSecondary,
                                color: token.colorText,
                                border: 'none',
                                borderRadius: 4,
                                fontSize: '0.9em',
                                fontFamily: 'monospace',
                              }}
                            >
                              {children}
                            </Tag>
                          ) : (
                            <div style={{ margin: '8px 0' }}>
                              <SyntaxHighlighter
                                style={oneLight as any}
                                language={match[1]}
                                PreTag="div"
                                customStyle={{
                                  borderRadius: token.borderRadius,
                                  fontSize: '13px',
                                }}
                              >
                                {String(children).replace(/\n$/, '')}
                              </SyntaxHighlighter>
                            </div>
                          )
                        },
                        p: ({ children }) => (
                          <div style={{ 
                            marginBottom: 0,
                            color: token.colorText,
                            fontSize: 16,
                            fontWeight: 400,
                            lineHeight: '26px',
                            whiteSpace: 'pre-wrap', // 保留换行符和空格
                          }}>
                            {children}
                          </div>
                        ),
                        ul: ({ children }) => (
                          <ul style={{ 
                            marginLeft: 16, 
                            marginBottom: 8,
                            color: token.colorText,
                          }}>
                            {children}
                          </ul>
                        ),
                        ol: ({ children }) => (
                          <ol style={{ 
                            marginLeft: 16, 
                            marginBottom: 8,
                            color: token.colorText,
                          }}>
                            {children}
                          </ol>
                        ),
                        li: ({ children }) => (
                          <li style={{ marginBottom: 4 }}>{children}</li>
                        ),
                        h1: ({ children }) => (
                          <h1 style={{ 
                            fontSize: '1.5em', 
                            fontWeight: 'bold', 
                            marginBottom: 8,
                            color: token.colorText,
                          }}>
                            {children}
                          </h1>
                        ),
                        h2: ({ children }) => (
                          <h2 style={{ 
                            fontSize: '1.3em', 
                            fontWeight: 'bold', 
                            marginBottom: 8,
                            color: token.colorText,
                          }}>
                            {children}
                          </h2>
                        ),
                        h3: ({ children }) => (
                          <h3 style={{ 
                            fontSize: '1.1em', 
                            fontWeight: 'bold', 
                            marginBottom: 8,
                            color: token.colorText,
                          }}>
                            {children}
                          </h3>
                        ),
                        blockquote: ({ children }) => (
                          <blockquote style={{
                            borderLeft: `4px solid ${token.colorBorderSecondary}`,
                            paddingLeft: 12,
                            margin: '8px 0',
                            fontStyle: 'italic',
                            color: token.colorTextSecondary,
                          }}>
                            {children}
                          </blockquote>
                        ),
                        hr: () => (
                          <div style={{ 
                            display: 'flex',
                            alignItems: 'center',
                            margin: '12px 0',
                          }}>
                            <hr style={{
                              flex: '1 1 0%',
                              borderTop: '1px solid rgba(0, 0, 0, .13)',
                              borderRight: 'none',
                              borderBottom: 'none',
                              borderLeft: 'none',
                              borderImage: 'initial',
                              margin: 0,
                            }} />
                          </div>
                        ),
                        table: ({ children }) => (
                          <div style={{ 
                            overflowX: 'auto',
                            margin: '12px 0',
                          }}>
                            <table className="markdown-table" style={{
                              width: '100%',
                              borderCollapse: 'separate',
                              borderSpacing: 0,
                              fontSize: 14,
                              border: `1px solid ${token.colorBorder}`,
                              borderRadius: '8px',
                            }}>
                              {children}
                            </table>
                          </div>
                        ),
                        thead: ({ children }) => (
                          <thead style={{
                            background: token.colorFillQuaternary,
                          }}>
                            {children}
                          </thead>
                        ),
                        tbody: ({ children }) => (
                          <tbody>
                            {children}
                          </tbody>
                        ),
                        tr: ({ children }) => (
                          <tr style={{
                            borderBottom: `1px solid ${token.colorBorder}`,
                          }}>
                            {children}
                          </tr>
                        ),
                        th: ({ children, style }) => (
                          <th style={{
                            padding: '10px 12px',
                            textAlign: 'left',
                            fontWeight: 600,
                            color: token.colorText,
                            ...style,
                          }}>
                            {children}
                          </th>
                        ),
                        td: ({ children, style }) => (
                          <td style={{
                            padding: '10px 12px',
                            color: token.colorText,
                            ...style,
                          }}>
                            {children}
                          </td>
                        ),
                      }}
                    >
                      {message.content}
                    </ReactMarkdown>
                  </Card>
                ) : (
                  <div style={{ 
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 8,
                  }}>
                    {/* 当正在打字且是最新AI消息时，显示旋转图标 */}
                    {isTyping && isLatestAIMessage && (
                      <LoadingOutlined style={{ 
                        color: '#000000', 
                        fontSize: 16,
                        marginTop: 4, // 与文字对齐
                      }} />
                    )}
                    
                    <div style={{ flex: 1, minWidth: 0 }}>
                      {/* 显示消息内容（除非有缺失字段数据） */}
                      {!message.missingFieldsData && (
                        <>
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              code({ className, children }) {
                                const match = /language-(\w+)/.exec(className || '')
                                const isInline = !match
                                
                                return isInline ? (
                                  <Tag
                                    style={{
                                      background: token.colorFillSecondary,
                                      color: token.colorText,
                                      border: 'none',
                                      borderRadius: 4,
                                      fontSize: '0.9em',
                                      fontFamily: 'monospace',
                                    }}
                                  >
                                    {children}
                                  </Tag>
                                ) : (
                                  <div style={{ margin: '8px 0' }}>
                                    <SyntaxHighlighter
                                      style={oneLight as any}
                                      language={match[1]}
                                      PreTag="div"
                                      customStyle={{
                                        borderRadius: token.borderRadius,
                                        fontSize: '13px',
                                      }}
                                    >
                                      {String(children).replace(/\n$/, '')}
                                    </SyntaxHighlighter>
                                  </div>
                                )
                              },
                              p: ({ children }) => (
                                <div style={{ 
                                  marginBottom: 8,
                                  color: token.colorText,
                                  fontSize: 16,
                                  lineHeight: 1.6,
                                }}>
                                  {children}
                                </div>
                              ),
                              ul: ({ children }) => (
                                <ul style={{ 
                                  marginLeft: 16, 
                                  marginBottom: 8,
                                  color: token.colorText,
                                  fontSize: 16,
                                }}>
                                  {children}
                                </ul>
                              ),
                              ol: ({ children }) => (
                                <ol style={{ 
                                  marginLeft: 16, 
                                  marginBottom: 8,
                                  color: token.colorText,
                                  fontSize: 16,
                                }}>
                                  {children}
                                </ol>
                              ),
                              li: ({ children }) => (
                                <li style={{ marginBottom: 4 }}>{children}</li>
                              ),
                              h1: ({ children }) => (
                                <h1 style={{ 
                                  fontSize: '1.5em', 
                                  fontWeight: 'bold', 
                                  marginBottom: 8,
                                  color: token.colorText,
                                }}>
                                  {children}
                                </h1>
                              ),
                              h2: ({ children }) => (
                                <h2 style={{ 
                                  fontSize: '1.3em', 
                                  fontWeight: 'bold', 
                                  marginBottom: 8,
                                  color: token.colorText,
                                }}>
                                  {children}
                                </h2>
                              ),
                              h3: ({ children }) => (
                                <h3 style={{ 
                                  fontSize: '1.1em', 
                                  fontWeight: 'bold', 
                                  marginBottom: 8,
                                  color: token.colorText,
                                }}>
                                  {children}
                                </h3>
                              ),
                              blockquote: ({ children }) => (
                                <blockquote style={{
                                  borderLeft: `4px solid ${token.colorBorderSecondary}`,
                                  paddingLeft: 12,
                                  margin: '8px 0',
                                  fontStyle: 'italic',
                                  color: token.colorTextSecondary,
                                }}>
                                  {children}
                                </blockquote>
                              ),
                              hr: () => (
                                <div style={{ 
                                  display: 'flex',
                                  alignItems: 'center',
                                  margin: '12px 0',
                                }}>
                                  <hr style={{
                                    flex: '1 1 0%',
                                    borderTop: '1px solid rgba(0, 0, 0, .13)',
                                    borderRight: 'none',
                                    borderBottom: 'none',
                                    borderLeft: 'none',
                                    borderImage: 'initial',
                                    margin: 0,
                                  }} />
                                </div>
                              ),
                              table: ({ children }) => (
                                <div style={{ 
                                  overflowX: 'auto',
                                  margin: '12px 0',
                                }}>
                                  <table className="markdown-table" style={{
                                    width: '100%',
                                    borderCollapse: 'separate',
                                    borderSpacing: 0,
                                    fontSize: 14,
                                    border: `1px solid ${token.colorBorder}`,
                                    borderRadius: '8px',
                                  }}>
                                    {children}
                                  </table>
                                </div>
                              ),
                              thead: ({ children }) => (
                                <thead style={{
                                  background: token.colorFillQuaternary,
                                }}>
                                  {children}
                                </thead>
                              ),
                              tbody: ({ children }) => (
                                <tbody>
                                  {children}
                                </tbody>
                              ),
                              tr: ({ children }) => (
                                <tr style={{
                                  borderBottom: `1px solid ${token.colorBorder}`,
                                }}>
                                  {children}
                                </tr>
                              ),
                              th: ({ children, style }) => (
                                <th style={{
                                  padding: '10px 12px',
                                  textAlign: 'left',
                                  fontWeight: 600,
                                  color: token.colorText,
                                  ...style,
                                }}>
                                  {children}
                                </th>
                              ),
                              td: ({ children, style }) => (
                                <td style={{
                                  padding: '10px 12px',
                                  color: token.colorText,
                                  ...style,
                                }}>
                                  {children}
                                </td>
                              ),
                            }}
                          >
                            {message.content}
                          </ReactMarkdown>
                          
                          {/* 语音播放按钮 - 只在 assistant 消息且有内容时显示 */}
                          {message.type === 'assistant' && message.content && message.content.trim() && (
                            <div style={{ marginTop: 8 }}>
                              <VoicePlayButton
                                messageId={message.id}
                                content={message.content}
                                isPlaying={playingMessageId === message.id}
                                onPlay={() => handleVoicePlay(message.id, message.content)}
                                onStop={handleVoiceStop}
                              />
                            </div>
                          )}
                          
                          {/* 显示确认状态标签 */}
                          {message.confirmationStatus && (
                            <div style={{ marginTop: 8 }}>
                              {message.confirmationStatus === 'confirmed' ? (
                                <Tag color="success" icon={<CheckCircleOutlined />}>
                                  已确认
                                </Tag>
                              ) : (
                                <Tag color="default" icon={<ExclamationCircleOutlined />}>
                                  已取消
                                </Tag>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    
                    {/* AI消息的文件附件 */}
                    {message.attachments && message.attachments.length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <Space direction="vertical" size={8} style={{ width: '100%' }}>
                          {message.attachments.map((file) => (
                            <FileAttachmentDisplay key={file.id} file={file} />
                          ))}
                        </Space>
                      </div>
                    )}
                    
                    {/* 图纸查看器 - 当消息包含图纸信息时显示 */}
                    {(hasDrawingContent(message.content) || (message.progressData?.type === 'review_display_view')) && (
                      <MessageDrawingViewer
                        content={message.content}
                        progressData={message.progressData}
                      />
                    )}
                    
                    {/* 缺失字段卡片 - 当有缺失字段数据时显示 */}
                    {message.missingFieldsData && (
                      <div style={{ marginTop: message.content ? 12 : 0 }}>
                        <MissingFieldsCard
                          message={message.missingFieldsData.message}
                          summary={message.missingFieldsData.summary}
                          missingFields={message.missingFieldsData.missing_fields}
                          ncFailedItems={message.missingFieldsData.nc_failed_items || []}
                        />
                      </div>
                    )}
                    
                    {/* 确认按钮 - 当需要确认时显示（历史消息不显示） */}
                    {/* 历史消息：隐藏所有确认卡片和ModificationCard */}
                    {message.requiresConfirmation && message.intent && !message.id.startsWith('history-') && !hasLaterStartedOrCompletedStageForSameJob && (
                      <div style={{ marginTop: message.content ? 0 : 0 }}>
                        {/* 数据修改：使用 ModificationCard 显示详细表格（仅非历史消息） */}
                        {message.intent === 'DATA_MODIFICATION' && message.intentData?.parsed_changes && (
                          <ModificationCard
                            modificationId={message.intentData.modification_id || message.id}
                            changes={message.intentData.parsed_changes}
                            displayView={message.intentData.display_view}
                            messageTimestamp={message.timestamp instanceof Date ? message.timestamp.getTime() : message.timestamp}
                            onConfirm={async () => {
                              if (message.jobId) {
                                await handleConfirm(message.id, message.jobId, message.intent)
                              }
                            }}
                            loading={confirmingMessageId === message.id}
                          />
                        )}
                        
                        {/* 其他意图类型：使用简单的确认卡片 */}
                        {message.intent !== 'DATA_MODIFICATION' && (
                          <div
                            style={{
                              background: message.intent === 'FEATURE_RECOGNITION'
                                ? 'linear-gradient(135deg, #f6f8ff 0%, #faf7ff 100%)'
                                : message.intent === 'PRICE_CALCULATION'
                                ? 'linear-gradient(135deg, #fff5fc 0%, #fff0f6 100%)'
                                : '#f8f9fa',
                              borderRadius: 10,
                              padding: '18px 20px',
                              borderLeft: message.intent === 'FEATURE_RECOGNITION'
                                ? '4px solid #667eea'
                                : message.intent === 'PRICE_CALCULATION'
                                ? '4px solid #f093fb'
                                : `4px solid ${token.colorPrimary}`,
                              boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
                              transition: 'all 0.2s ease',
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.08)'
                              e.currentTarget.style.transform = 'translateY(-1px)'
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.05)'
                              e.currentTarget.style.transform = 'translateY(0)'
                            }}
                          >
                            <Space direction="vertical" size={14} style={{ width: '100%' }}>
                              {/* 内容区域 */}
                              {message.content && (
                                <div>
                                  <Text style={{ 
                                    fontSize: 14, 
                                    color: '#1f1f1f',
                                    lineHeight: 1.7,
                                  }}>
                                    {message.content}
                                  </Text>
                                </div>
                              )}
                              
                              {/* 按钮区域 */}
                              <div style={{ 
                                display: 'flex', 
                                justifyContent: 'flex-end',
                              }}>
                                <CountdownConfirmButton
                                  messageId={message.id}
                                  messageTimestamp={message.timestamp instanceof Date ? message.timestamp.getTime() : message.timestamp}
                                  loading={confirmingMessageId === message.id}
                                  onConfirm={() => handleConfirm(message.id, message.jobId, message.intent)}
                                >
                                  确认执行
                                </CountdownConfirmButton>
                              </div>
                            </Space>
                          </div>
                        )}
                      </div>
                    )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      {messages.map((message, index) => renderMessage(message, index))}
      
      {/* 打字指示器 - 只在没有AI消息或最后一条不是AI消息时显示 */}
      {isTyping && (() => {
        const lastMessage = messages[messages.length - 1]
        const lastIsAI = lastMessage && (lastMessage.type === 'assistant' || lastMessage.type === 'progress')
        
        // 如果最后一条消息不是AI消息，显示完整的打字指示器
        if (!lastIsAI) {
          return (
            <div style={{ 
              marginBottom: 12,
              display: 'flex',
              justifyContent: 'flex-start',
            }}>
              <div style={{ 
                display: 'flex',
                alignItems: 'center',
                gap: 12,
              }}>
                <AIAvatar size={32} isTyping={true} />
                <LoadingOutlined style={{ color: '#000000', fontSize: 16 }} />
              </div>
            </div>
          )
        }
        return null
      })()}
      
      <div ref={messagesEndRef} />
    </div>
  )
}

export default React.memo(MessageList, (prevProps, nextProps) => {
  // 只有当 messages、isTyping 或 scrollContainerRef 真正改变时才重新渲染
  return (
    prevProps.messages === nextProps.messages &&
    prevProps.isTyping === nextProps.isTyping &&
    prevProps.scrollContainerRef === nextProps.scrollContainerRef
  );
});

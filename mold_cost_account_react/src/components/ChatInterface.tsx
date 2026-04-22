import React, { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { Button, Input, Flex, Typography, theme, Dropdown, Modal, message, Space, Skeleton } from "antd";
import {
    SendOutlined,
    PaperClipOutlined,
    MenuOutlined,
    EditOutlined,
    DeleteOutlined,
    LoginOutlined,
    DownOutlined,
    LoadingOutlined,
    DownloadOutlined,
    ExclamationCircleOutlined,
    SyncOutlined,
    AudioOutlined,
} from "@ant-design/icons";
import { useAppStore } from "../store/useAppStore";
import MessageList from "./MessageList";
import FileUpload from "./FileUpload";
import InteractionCards from "./InteractionCards";
import AIAvatar from "./AIAvatar";
import WelcomeAIAvatar from "./WelcomeAIAvatar";
import GlobalProgressBar from "./GlobalProgressBar";
import Fireworks from "./Fireworks";
import { chatService } from "../services/chatService";
import { sessionService } from "../services/sessionService";
import { speechRecognitionService } from "../services/speechRecognitionService";
import LoginModal from "./LoginModal";
import { getValidToken } from "../utils/auth";
import { AUTH_STORAGE_KEYS } from "../constants/auth";

const { TextArea } = Input;
const { Text } = Typography;

// 同步检查登录状态的函数
const checkAuthSync = () => {
  const loggedIn = localStorage.getItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN) === 'true'
  const userInfoStr = localStorage.getItem(AUTH_STORAGE_KEYS.USER_INFO)
  const validToken = getValidToken()
  return loggedIn && !!userInfoStr && !!validToken
}

const ChatInterface: React.FC = () => {
    const [inputValue, setInputValue] = useState("");
    const [showFileUpload, setShowFileUpload] = useState(false);
    const [textareaInitialized, setTextareaInitialized] = useState(false);
    const [showLoginModal, setShowLoginModal] = useState(false);
    const [showFireworks, setShowFireworks] = useState(false);
    const [extraFireworkTrigger, setExtraFireworkTrigger] = useState(0);
    // 使用同步方式初始化登录状态，避免闪动
    const [isLoggedIn, setIsLoggedIn] = useState(() => checkAuthSync());
    const [hasStartedCalculation, setHasStartedCalculation] = useState(false); // 新增：标记是否已开始核算
    const [renameModalVisible, setRenameModalVisible] = useState(false); // 新增：重命名弹窗状态
    const [renameInputValue, setRenameInputValue] = useState(''); // 新增：重命名输入值
    const [renamingLoading, setRenamingLoading] = useState(false); // 新增：重命名加载状态
    const [isExporting, setIsExporting] = useState(false); // 新增：导出Excel加载状态
    const [isRecording, setIsRecording] = useState(false); // 新增：语音录音状态
    const [isRecognizing, setIsRecognizing] = useState(false); // 新增：语音识别中状态
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const { token } = theme.useToken();
    const loadedSessionRef = useRef<string | null>(null); // 记录已加载的sessionId，避免重复加载
    const historyLoadedSessionRef = useRef<string | null>(null); // 仅标记真正完成历史消息加载的会话
    const reviewFallbackStartedRef = useRef<Set<string>>(new Set()); // 避免同一会话重复补调 /review/start

    const {
        messages,
        isTyping,
        currentJobId,
        interactionCards,
        addMessage,
        setMessages,
        setIsTyping,
        isMobile,
        setMobileDrawerVisible,
        jobs,
        updateJob,
        deleteJob,
        setCurrentView,
        loadHistoryMessages,
        isLoadingHistory,  // 新增：获取加载历史消息状态
        historyLoadError,  // 新增：获取历史消息加载错误
        setHistoryLoadError,  // 新增：设置历史消息加载错误
        isNewSession,  // 新增：获取是否为新会话标记
        setIsNewSession,  // 新增：设置是否为新会话
        isCalculating,  // 新增：获取是否正在核算
        setIsCalculating,  // 新增：设置是否正在核算
        isStartingReview,  // 新增：获取是否正在启动审核
        isRefreshing,  // 新增：获取是否正在刷新审核数据
        reviewStarted,  // 新增：获取审核是否已启动完成
        setReviewStarted,  // 新增：设置审核是否已启动完成
        isReprocessing,  // 新增：获取是否正在重新处理
        setIsWaitingForReply,  // 新增：设置是否正在等待AI回复
    } = useAppStore();

    // 获取当前任务
    const currentJob = currentJobId ? jobs.find(job => job.id === currentJobId) : null;
    
    // // 添加日志监控currentJob
    // useEffect(() => {
    //     console.log('📋 ChatInterface - currentJob 状态:', {
    //         currentJobId,
    //         currentJob,
    //         jobsCount: jobs.length,
    //         jobs: jobs.map(j => ({ id: j.id, title: j.title }))
    //     })
    // }, [currentJobId, currentJob, jobs])
    
    // 检查是否已上传CAD文件
    const hasUploadedFiles = currentJob && (currentJob.dwgFile || currentJob.prtFile);
    
    // 检查当前会话是否有消息历史（只检查当前jobId的消息）
    // 添加安全检查，确保messages是数组
    const currentJobMessages = Array.isArray(messages) 
        ? messages.filter(msg => msg.jobId === currentJobId) 
        : [];
    const hasMessages = currentJobMessages.length > 0;
    
    // 计算当前进度（用于判断是否可以发送消息）
    const currentProgress = useMemo(() => {
        const progressMessages = currentJobMessages.filter(
            msg => msg.type === 'progress' && 
                   msg.progressData &&
                   typeof msg.progressData.progress === 'number'
        );
        
        if (progressMessages.length === 0) {
            return 0;
        }
        
        // 获取最新的进度值
        const latestProgress = progressMessages[progressMessages.length - 1];
        return latestProgress.progressData?.progress || 0;
    }, [currentJobMessages]);
    
    // 检查是否收到了 awaiting_confirm 阶段（特征识别完成，等待用户确认）
    // 只有在收到 awaiting_confirm 时才允许发送消息
    const hasReachedMinProgress = currentJobMessages.some(msg => 
        msg.type === 'progress' && msg.progressData?.stage === 'awaiting_confirm'
    );

    const canSendAfterWorkflowReady = useMemo(() => {
        const hasPricingOrCompletedStage = currentJobMessages.some(msg =>
            msg.type === 'progress' &&
            (
                msg.progressData?.stage === 'pricing_started' ||
                msg.progressData?.stage === 'pricing_completed' ||
                msg.progressData?.stage === 'cost_calculation_started' ||
                msg.progressData?.stage === 'cost_calculation_completed' ||
                msg.progressData?.stage === 'completed'
            )
        );

        // 历史消息经过过滤后，awaiting_confirm 可能不存在。
        // 只要已经进入报价或任务完成，就应该允许继续发送追问。
        return hasReachedMinProgress || hasPricingOrCompletedStage;
    }, [currentJobMessages, hasReachedMinProgress]);
    
    // 检查是否正在进行重新处理（重新识别特征或重新计算价格）
    const isReprocessingInHistory = useMemo(() => {
        // 获取最新的进度消息
        const progressMessages = currentJobMessages.filter(
            msg => msg.type === 'progress' && msg.progressData
        );
        
        if (progressMessages.length === 0) {
            return false;
        }
        
        const latestProgress = progressMessages[progressMessages.length - 1];
        const stage = latestProgress.progressData?.stage || '';
        const details = latestProgress.progressData?.details;
        
        // 检查是否是重新识别特征（feature_recognition_started 且 type 为 reprocess）
        const isReprocessingFeature = stage === 'feature_recognition_started' && 
                                      details?.type === 'reprocess';
        
        // 检查是否正在计算价格（pricing_started）
        const isPricing = stage === 'pricing_started';
        
        return isReprocessingFeature || isPricing;
    }, [currentJobMessages]);
    
    // 检查是否显示了审核数据表格（特征识别完成）
    // 检查三种情况：
    // 1. progress 类型且有 review_display_view
    // 2. system 类型且有 reviewData
    // 3. progress 类型且 stage 为 awaiting_confirm（等待确认状态，表示特征识别已完成）
    // 检查是否收到了 awaiting_confirm 阶段（特征识别完成，等待用户确认）
    const hasAwaitingConfirm = currentJobMessages.some(msg => 
        msg.type === 'progress' && msg.progressData?.stage === 'awaiting_confirm'
    );

    const hasReviewTable = currentJobMessages.some(msg =>
        (msg.type === 'progress' && msg.progressData?.type === 'review_display_view' && Array.isArray(msg.progressData?.data)) ||
        (msg.type === 'system' && Array.isArray(msg.reviewData))
    );

    const hasFeatureRecognitionReady = currentJobMessages.some(msg =>
        msg.type === 'progress' &&
        (
            msg.progressData?.stage === 'feature_recognition_completed' ||
            msg.progressData?.stage === 'awaiting_confirm'
        )
    );
    
    // 检查是否已经开始核算（通过检测是否有价格计算相关的消息）
    const hasPricingMessages = currentJobMessages.some(msg =>
        msg.type === 'progress' &&
        (msg.progressData?.stage === 'pricing_started' ||
         msg.progressData?.stage === 'pricing_completed' ||
         msg.progressData?.stage === 'cost_calculation_started' ||
         msg.progressData?.stage === 'cost_calculation_completed')
    );
    
    // 检查任务是否已完成
    const isTaskCompleted = currentJobMessages.some(msg =>
        msg.type === 'progress' &&
        msg.progressData?.stage === 'completed' &&
        msg.progressData?.progress === 100
    );
    
    // // 调试日志：监控开始核算按钮显示条件
    // useEffect(() => {
    //     if (currentJobId && currentJobMessages.length > 0) {
    //         console.log('🔍 开始核算卡片显示条件:', {
    //             hasAwaitingConfirm,
    //             hasPricingMessages,
    //             isTaskCompleted,
    //             isCalculating,
    //             shouldShow: hasAwaitingConfirm && !hasPricingMessages && !isTaskCompleted && !isCalculating,
    //             currentJobMessages: currentJobMessages.map(m => ({
    //                 type: m.type,
    //                 stage: m.progressData?.stage,
    //                 hasReviewData: m.reviewData ? 'yes' : 'no',
    //                 progressType: m.progressData?.type
    //             }))
    //         });
    //     }
    // }, [hasAwaitingConfirm, hasPricingMessages, isTaskCompleted, isCalculating, currentJobId, currentJobMessages]);
    
    // 只有在已上传文件或当前会话有消息时才显示聊天界面
    // 如果正在加载历史消息，也显示聊天界面（显示骨架屏）
    // 如果有currentJobId（选中了会话），也显示聊天界面
    // 但如果未登录，则强制显示新建对话页面
    const shouldShowChatInterface = isLoggedIn && (hasUploadedFiles || hasMessages || isLoadingHistory || !!currentJobId);
    
    // // 添加调试日志 - 监控关键状态变化
    // useEffect(() => {
    //     // 如果突然显示欢迎卡片，打印警告
    //     if (!shouldShowChatInterface && (Array.isArray(messages) && messages.length > 0)) {
    //         console.warn('⚠️⚠️⚠️ 警告：有消息但显示欢迎卡片！', {
    //             messagesCount: messages.length,
    //             currentJobId,
    //             currentJobMessagesCount: currentJobMessages.length,
    //             messagesJobIds: messages.map(m => m.jobId)
    //         });
    //     }
    // }, [messages, currentJobId, shouldShowChatInterface]);

    // 检查登录状态
    useEffect(() => {
        const checkAuth = () => {
            const newAuthState = checkAuthSync()
            setIsLoggedIn(newAuthState)
            
            // 如果检测到未登录状态，确保清理可能残留的数据
            if (!newAuthState) {
                const hasLoggedInFlag = localStorage.getItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN) === 'true'
                const hasUserInfo = !!localStorage.getItem(AUTH_STORAGE_KEYS.USER_INFO)
                const hasValidToken = !!getValidToken()
                
                // 如果有登录标记但 token 无效，清理数据
                if ((hasLoggedInFlag || hasUserInfo) && !hasValidToken) {
                    localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
                    localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
                    localStorage.removeItem(AUTH_STORAGE_KEYS.TOKEN)
                }
            }
        }

        // 初始检查
        checkAuth()

        // 监听登录状态变化
        const handleLoginStateChange = () => {
            checkAuth()
        }

        window.addEventListener('loginStateChange', handleLoginStateChange)
        window.addEventListener('storage', handleLoginStateChange)
        
        // 定期检查 token 有效性（每30秒检查一次）
        const intervalId = setInterval(() => {
            checkAuth()
        }, 30000)

        return () => {
            window.removeEventListener('loginStateChange', handleLoginStateChange)
            window.removeEventListener('storage', handleLoginStateChange)
            clearInterval(intervalId)
        }
    }, [])

    // 获取任务标题
    const getJobTitle = () => {
        if (!currentJob) return '新对话';
        return currentJob.title || currentJob.dwgFile?.name || currentJob.prtFile?.name || `任务 ${currentJob.id.slice(0, 8)}`;
    };

    // 处理重命名 - 打开弹窗
    const handleRename = () => {
        if (!currentJob) return;
        const currentTitle = getJobTitle();
        setRenameInputValue(currentTitle);
        setRenameModalVisible(true);
    };

    // 保存重命名
    const handleSaveRename = async () => {
        if (!currentJob || !renameInputValue.trim()) {
            return;
        }

        try {
            setRenamingLoading(true); // 开始加载
            
            // 调用重命名接口
            await sessionService.renameSession(currentJob.id, renameInputValue.trim());
            
            // 更新本地状态
            updateJob(currentJob.id, { title: renameInputValue.trim() });
            
            message.success('重命名成功');
            setRenameModalVisible(false);
            setRenameInputValue('');
        } catch (error) {
            console.error('重命名失败:', error);
            message.error('重命名失败');
        } finally {
            setRenamingLoading(false); // 结束加载
        }
    };

    // 取消重命名
    const handleCancelRename = () => {
        setRenameModalVisible(false);
        setRenameInputValue('');
    };

    // 处理删除
    const handleDelete = () => {
        if (!currentJob) return;
        const jobTitle = getJobTitle();
        Modal.confirm({
            title: '删除对话',
            content: `确定要删除对话"${jobTitle}"吗？此操作不可恢复。`,
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: () => {
                deleteJob(currentJob.id);
                message.success('删除成功');
                setCurrentView('chat');
            },
        });
    };

    // 任务操作菜单
    const taskMenuItems = currentJob ? [
        {
            key: 'rename',
            label: '重命名',
            icon: <EditOutlined />,
            onClick: handleRename,
        },
        {
            type: 'divider' as const,
        },
        {
            key: 'delete',
            label: '删除',
            icon: <DeleteOutlined />,
            danger: true,
            onClick: handleDelete,
        },
    ] : [];

    // 延迟初始化 textarea 的 autoSize，防止页面刷新时的高度跳动
    useEffect(() => {
        // 使用 requestAnimationFrame 确保在下一帧渲染时启用 autoSize
        const rafId = requestAnimationFrame(() => {
            setTextareaInitialized(true);
        });
        
        return () => cancelAnimationFrame(rafId);
    }, []);

    // 当currentJobId变化时加载历史消息
    // 使用 ref 来追踪是否已经加载过，避免在聊天过程中重复加载
    useEffect(() => {
        // 当 currentJobId 变化时，重置已开始核算标记和审核启动状态
        setHasStartedCalculation(false);
        setReviewStarted(false);
        setIsCalculating(false); // 重置核算状态，避免历史会话显示核算中
        reviewFallbackStartedRef.current.delete(currentJobId || '');
        
        // 当 currentJobId 变化时，无论之前是否加载过，都重新加载
        // 但如果是新会话（刚上传文件），则跳过加载历史消息
        if (currentJobId && isLoggedIn) {
            // 如果是新会话，跳过加载历史消息
            if (isNewSession) {
                loadedSessionRef.current = currentJobId; // 标记为已处理
                historyLoadedSessionRef.current = null; // 新上传流程，不应触发“历史补调”审核启动
                setIsNewSession(false); // 重置标记
                return;
            }
            
            // 检查是否需要加载（与上次加载的不同）
            if (loadedSessionRef.current !== currentJobId) {
                loadedSessionRef.current = currentJobId; // 标记为已加载
                
                // 使用sessionId（通常与jobId相同）加载历史消息
                // loadHistoryMessages 内部已经有防止竞态条件的逻辑
                loadHistoryMessages(currentJobId).catch(error => {
                    console.error('❌ 加载历史消息失败:', error);
                    historyLoadedSessionRef.current = null;
                    // 加载失败时，只有当前仍然是这个会话时才清除标记
                    if (loadedSessionRef.current === currentJobId) {
                        loadedSessionRef.current = null; // 加载失败，清除标记以便重试
                    }
                });
                historyLoadedSessionRef.current = currentJobId;
            } else {
                // console.log('⏭️ 跳过加载 - 已经加载过该会话:', currentJobId);
            }
        } else if (!currentJobId) {
            // 当 currentJobId 为空时（新建对话），重置加载标记
            loadedSessionRef.current = null;
            historyLoadedSessionRef.current = null;
            setIsNewSession(false); // 重置新会话标记
        }
    }, [currentJobId, isLoggedIn, isNewSession, loadHistoryMessages, setIsNewSession]);

    // 历史会话切回后，如果没有审核表格，则补调一次 /review/start 以恢复表格
    useEffect(() => {
        if (!currentJobId || !isLoggedIn || isNewSession || isLoadingHistory || historyLoadError) {
            return;
        }

        // 只允许“真正从历史加载完成”的会话触发补调，避免新上传流程在清理完成前提前启动审核。
        if (historyLoadedSessionRef.current !== currentJobId) {
            return;
        }

        if (!hasMessages || hasReviewTable || hasPricingMessages || isTaskCompleted || !hasFeatureRecognitionReady) {
            return;
        }

        if (reviewFallbackStartedRef.current.has(currentJobId)) {
            return;
        }

        reviewFallbackStartedRef.current.add(currentJobId);

        (async () => {
            try {
                await chatService.startReview(currentJobId);
                setReviewStarted(true);
            } catch (error) {
                console.error('❌ 补调 /review/start 失败:', error);
                reviewFallbackStartedRef.current.delete(currentJobId);
            }
        })();
    }, [
        currentJobId,
        isLoggedIn,
        isNewSession,
        isLoadingHistory,
        historyLoadError,
        hasMessages,
        hasReviewTable,
        hasPricingMessages,
        isTaskCompleted,
        hasFeatureRecognitionReady,
        setReviewStarted,
    ]);

    const handleSendMessage = useCallback(async () => {
        if (!inputValue.trim()) return;

        // 检查是否登录
        if (!isLoggedIn) {
            setShowLoginModal(true);
            return;
        }

        const userMessage = inputValue.trim();
        setInputValue("");

        // 在发送新消息前，隐藏所有未确认的消息的确认按钮
        // 注意：
        // - 确认修改（DATA_MODIFICATION）：不标记为"已取消"，因为这些修改会被后端缓存
        // - 重新识别特征（FEATURE_RECOGNITION）和重新计算（PRICE_CALCULATION）：标记为"已取消"
        setMessages((prevMessages) => {
            const currentMessages = Array.isArray(prevMessages) ? prevMessages : [];
            return currentMessages.map((msg) => {
                // 如果消息需要确认且还没有确认状态
                if (msg.requiresConfirmation && !msg.confirmationStatus) {
                    // 重新识别特征和重新计算：标记为已取消
                    if (msg.intent === 'FEATURE_RECOGNITION' || msg.intent === 'PRICE_CALCULATION' || msg.intent === 'WEIGHT_PRICE_CALCULATION') {
                        return { 
                            ...msg, 
                            requiresConfirmation: false,
                            confirmationStatus: 'cancelled' as const  // 标记为已取消
                        };
                    }
                    // 确认修改：不标记为已取消（后端会缓存这些修改）
                    else if (msg.intent === 'DATA_MODIFICATION') {
                        return { 
                            ...msg, 
                            requiresConfirmation: false,
                            // 不设置 confirmationStatus，这样就不会显示"已取消"标签
                        };
                    }
                }
                return msg;
            });
        });

        // 添加用户消息
        addMessage({
            type: "user",
            content: userMessage,
            jobId: currentJobId,
        });

        // 检查是否有当前任务ID
        if (!currentJobId) {
            addMessage({
                type: "assistant",
                content: "请先上传CAD文件开始分析，然后我们可以进行对话。",
            });
            return;
        }

        // 使用新的 /review/${jobId}/modify 接口
        setIsTyping(true);
        setIsWaitingForReply(true);  // 设置等待回复标记
        
        try {
            // 保存当前的 jobId，用于后续验证
            const requestJobId = currentJobId;
            
            // 调用意图识别接口
            const response = await chatService.submitModification(currentJobId, userMessage);
            
            // 检查当前页面的 job_id 是否与请求时的 job_id 相同
            // 如果用户在请求期间切换了会话，则不渲染返回的数据
            if (requestJobId !== useAppStore.getState().currentJobId) {
                setIsTyping(false);
                setIsWaitingForReply(false);  // 清除等待回复标记
                return;
            }
            
            // 添加AI回复消息，包含意图信息
            addMessage({
                type: "assistant",
                content: response.message,
                jobId: currentJobId,
                intent: response.intent,
                requiresConfirmation: response.requires_confirmation,
                intentData: response.data,
            });

            setIsTyping(false);
            
            // 延迟清除等待回复标记，确保 WebSocket 消息已经被忽略
            // 给 WebSocket 消息处理留出时间
            setTimeout(() => {
                setIsWaitingForReply(false);
            }, 2000);  // 2秒后清除标记

        } catch (error: any) {
            console.error("发送消息失败:", error);
            
            // 检查当前页面的 job_id 是否仍然是请求时的 job_id
            if (currentJobId === useAppStore.getState().currentJobId) {
                addMessage({
                    type: "assistant",
                    content: error.message || "抱歉，发送消息时出现错误，请重试。",
                    jobId: currentJobId,
                });
            }
            setIsTyping(false);
            
            // 延迟清除等待回复标记
            setTimeout(() => {
                setIsWaitingForReply(false);
            }, 2000);  // 2秒后清除标记
        }
    }, [inputValue, isLoggedIn, currentJobId, setShowLoginModal, setMessages, addMessage, setIsTyping, setIsWaitingForReply]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            // 检查是否满足发送条件（与发送按钮的禁用条件保持一致）
            // 从历史会话进入时，如果进度未达到50%，禁用发送
            // 如果正在重新处理（重新识别特征或重新计算价格），禁用发送
            const canSend = inputValue.trim() && 
                           !isTyping && 
                           !isStartingReview && 
                           !isRefreshing && 
                           !isCalculating && 
                           !isReprocessing && 
                           canSendAfterWorkflowReady && 
                           !isReprocessingInHistory;
            if (canSend) {
                handleSendMessage();
            }
        }
    }, [inputValue, isTyping, isStartingReview, isRefreshing, isCalculating, isReprocessing, canSendAfterWorkflowReady, isReprocessingInHistory, handleSendMessage]);

    const handleFileUpload = () => {
        // 检查是否登录
        if (!isLoggedIn) {
            setShowLoginModal(true);
            return;
        }
        setShowFileUpload(true);
    };

    const handleLoginSuccess = () => {
        // 触发登录状态变化事件
        window.dispatchEvent(new Event('loginStateChange'));
        message.success('登录成功！');
    };

    // 处理语音识别
    const handleVoiceRecognition = async () => {
        if (isRecording) {
            // 停止录音
            speechRecognitionService.stopRecognition();
            setIsRecording(false);
            // 开始识别，显示等待效果
            setIsRecognizing(true);
        } else {
            // 开始录音前先检查麦克风权限
            try {
                // 检查浏览器是否支持麦克风
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    message.error('您的浏览器不支持麦克风功能');
                    return;
                }

                // 检查麦克风权限状态
                if (navigator.permissions && navigator.permissions.query) {
                    try {
                        const permissionStatus = await navigator.permissions.query({ name: 'microphone' as PermissionName });
                        
                        if (permissionStatus.state === 'denied') {
                            Modal.warning({
                                title: '需要麦克风权限',
                                content: '请在浏览器设置中允许访问麦克风，然后刷新页面重试。',
                                okText: '我知道了',
                            });
                            return;
                        }
                    } catch (error) {
                        // 某些浏览器可能不支持 permissions.query，继续尝试获取麦克风
                        console.warn('无法查询麦克风权限状态:', error);
                    }
                }

                // 尝试获取麦克风权限（测试性请求）
                try {
                    const testStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    // 立即停止测试流
                    testStream.getTracks().forEach(track => track.stop());
                } catch (error: any) {
                    console.error('❌ 麦克风权限被拒绝:', error);
                    
                    if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
                        Modal.warning({
                            title: '需要麦克风权限',
                            content: '请允许浏览器访问麦克风，以便使用语音输入功能。',
                            okText: '我知道了',
                        });
                    } else if (error.name === 'NotFoundError') {
                        message.error('未检测到麦克风设备');
                    } else {
                        message.error('无法访问麦克风，请检查设备连接');
                    }
                    return;
                }

                // 权限检查通过，开始录音
                setIsRecording(true);
                
                speechRecognitionService.startRecognition({
                    onStart: () => {
                        message.info('开始录音...');
                    },
                    onResult: (text, isFinal) => {
                        // 只在最终结果时更新输入框
                        if (isFinal) {
                            setInputValue(prev => {
                                const newValue = prev ? `${prev} ${text}` : text;
                                return newValue.trim();
                            });
                        }
                    },
                    onEnd: () => {
                        setIsRecording(false);
                        setIsRecognizing(false);
                        message.success('识别完成');
                    },
                    onError: (error) => {
                        console.error('❌ 录音错误:', error);
                        setIsRecording(false);
                        setIsRecognizing(false);
                        message.error(`录音失败: ${error}`);
                    },
                });
            } catch (error: any) {
                console.error('❌ 启动语音识别失败:', error);
                message.error('启动语音识别失败');
                setIsRecording(false);
                setIsRecognizing(false);
            }
        }
    };

    // 处理导出报价单Excel
    const handleExportExcel = async () => {
        if (!currentJobId) {
            message.error('缺少任务ID');
            return;
        }

        try {
            setIsExporting(true);
            
            // 构建导出URL - 使用 CONTINUE_API_URL（包含 /api/v1 前缀）
            const exportUrl = `${chatService.getContinueApiUrl()}/reports/${currentJobId}/export`;
            
            // 获取token
            const token = getValidToken();
            if (!token) {
                message.error('请先登录');
                setShowLoginModal(true);
                return;
            }
            
            // 使用fetch下载文件
            const response = await fetch(exportUrl, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                },
            });
            
            if (!response.ok) {
                throw new Error('导出失败');
            }
            
            // 获取文件名（从响应头）/*  */
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = ''; // 默认为空，让浏览器自动处理
            
            if (contentDisposition) {
                // 尝试匹配 filename*=UTF-8''encoded-filename 格式（RFC 5987）
                const filenameStarMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
                if (filenameStarMatch && filenameStarMatch[1]) {
                    try {
                        filename = decodeURIComponent(filenameStarMatch[1]);
                    } catch (e) {
                        console.warn('文件名解码失败:', e);
                    }
                } else {
                    // 尝试匹配 filename="name" 或 filename=name 格式
                    const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
                    if (filenameMatch && filenameMatch[1]) {
                        filename = filenameMatch[1].replace(/['"]/g, '');
                        // 尝试解码URL编码的文件名
                        try {
                            filename = decodeURIComponent(filename);
                        } catch (e) {
                            // 如果解码失败，使用原始文件名
                            console.warn('文件名解码失败，使用原始文件名:', e);
                        }
                    }
                }
            }
            
            // 创建Blob并下载
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            
            // 只有在有文件名时才设置 download 属性
            if (filename) {
                a.download = filename;
            }
            
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            message.success('报价单导出成功！');
        } catch (error: any) {
            console.error('导出报价单失败:', error);
            message.error(error.message || '导出报价单失败');
        } finally {
            setIsExporting(false);
        }
    };

    return (
        <Flex
            vertical
            style={{
                height: "100vh",
                background: "#ffffff",
            }}
        >
            {/* 聊天头部 */}
            <div
                style={{
                    padding: "0 24px",
                    height: 50,
                    display: 'flex',
                    alignItems: 'center',
                    background: token.colorBgContainer,
                }}
            >
                <Flex align="center" justify="space-between" style={{ width: '100%' }}>
                    {/* 左侧：移动端菜单按钮 + 标题/Logo + 下拉菜单 */}
                    <Flex align="center" gap={12}>
                        {isMobile && isLoggedIn && (
                            <Button
                                type="text"
                                icon={<MenuOutlined />}
                                onClick={() => setMobileDrawerVisible(true)}
                                style={{
                                    color: token.colorTextSecondary,
                                    padding: "4px 8px",
                                    height: 32,
                                    width: 32,
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                }}
                            />
                        )}
                        
                        {/* 未登录时显示Logo，登录后显示任务标题 */}
                        {!isLoggedIn ? (
                            <Flex align="center" gap={12}>
                                <div style={{ 
                                    width: 32, 
                                    height: 32, 
                                    display: 'flex', 
                                    alignItems: 'center', 
                                    justifyContent: 'center',
                                    flexShrink: 0,
                                }}>
                                    <img 
                                        src="/logo.svg" 
                                        alt="Logo" 
                                        style={{ 
                                            height: 32,
                                            width: 32,
                                            objectFit: 'contain',
                                        }} 
                                    />
                                </div>
                                <Text strong style={{ fontSize: 18 }}>
                                    九章智核
                                </Text>
                            </Flex>
                        ) : currentJob ? (
                            <Dropdown
                                menu={{ items: taskMenuItems }}
                                trigger={['click']}
                                placement="bottomRight"
                                overlayStyle={{ width: 128, minWidth: 'none' }}
                            >
                                <Flex 
                                    align="center" 
                                    gap={8} 
                                    style={{ 
                                        cursor: 'pointer',
                                        padding: '4px 12px',
                                        height: 32,
                                        borderRadius: 6,
                                        transition: 'background 0.2s',
                                    }}
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.background = '#F7F7F7'
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.background = 'transparent'
                                    }}
                                >
                                    <Text strong style={{ fontSize: 16 }}>
                                        {getJobTitle()}
                                    </Text>
                                    <DownOutlined style={{ fontSize: 10, opacity: 0.45 }} />
                                </Flex>
                            </Dropdown>
                        ) : null}
                    </Flex>

                    {/* 右侧：全局进度条（登录后显示）或登录按钮（未登录时显示） */}
                    {!isLoggedIn ? (
                        <Button
                            type="primary"
                            icon={<LoginOutlined />}
                            onClick={() => setShowLoginModal(true)}
                            size="large"
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                height: 40,
                                padding: '0 20px',
                                borderRadius: 20,
                                fontSize: 15,
                                fontWeight: 500,
                                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                                border: 'none',
                                boxShadow: '0 2px 8px rgba(102, 126, 234, 0.3)',
                                transition: 'all 0.3s ease',
                                flexShrink: 0,
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.transform = 'translateY(-2px)'
                                e.currentTarget.style.boxShadow = '0 4px 12px rgba(102, 126, 234, 0.4)'
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.transform = 'translateY(0)'
                                e.currentTarget.style.boxShadow = '0 2px 8px rgba(102, 126, 234, 0.3)'
                            }}
                        >
                            登录
                        </Button>
                    ) : (
                        <div style={{ flexShrink: 0 }}>
                            <GlobalProgressBar 
                                messages={messages}
                                currentJobId={currentJobId}
                                isTyping={isTyping}
                            />
                        </div>
                    )}
                </Flex>
            </div>

            {/* 消息区域 */}
            <div
                style={{
                    flex: 1,
                    overflow: "hidden",
                    position: "relative",
                    // 使用 contain 优化渲染性能
                    contain: "layout style paint",
                }}
            >
                {/* 消息列表 */}
                <div
                    ref={scrollContainerRef}
                    style={{
                        height: "100%",
                        overflow: "auto",
                        // padding: "20px 24px 24px", // 调整底部padding与新的渐变高度匹配
                        padding: "0 24px 24px",
                        // 使用 GPU 加速滚动
                        willChange: "scroll-position",
                        // 优化滚动性能
                        WebkitOverflowScrolling: "touch",
                    }}
                >
                    {/* 消息容器 - 与输入框宽度保持一致 */}
                    <div
                        style={{
                            maxWidth: 768,
                            margin: "0 auto",
                            paddingTop: '20px'
                        }}
                    >
                        {/* 如果正在加载历史消息，显示骨架屏 */}
                        {isLoadingHistory ? (
                            <div style={{ padding: '20px 0' }}>
                                <Space direction="vertical" size={24} style={{ width: '100%' }}>
                                    {/* 模拟3条消息的骨架屏 */}
                                    {[1, 2, 3].map((item) => (
                                        <div key={item} style={{ 
                                            display: 'flex',
                                            gap: 12,
                                            alignItems: 'flex-start',
                                        }}>
                                            <Skeleton.Avatar active size={32} />
                                            <div style={{ flex: 1 }}>
                                                <Skeleton active paragraph={{ rows: 2 }} />
                                            </div>
                                        </div>
                                    ))}
                                </Space>
                            </div>
                        ) : historyLoadError ? (
                            /* 如果加载历史消息失败，显示错误提示和重试按钮 */
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                minHeight: 'calc(100vh - 300px)',
                                padding: '40px 20px',
                            }}>
                                <div style={{
                                    maxWidth: 480,
                                    width: '100%',
                                    textAlign: 'center',
                                }}>
                                    <Space direction="vertical" size={24} style={{ width: '100%' }}>
                                        {/* 错误图标 */}
                                        <div style={{
                                            width: 80,
                                            height: 80,
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            margin: '0 auto',
                                            background: `${token.colorErrorBg}`,
                                            borderRadius: '50%',
                                            padding: 8,
                                        }}>
                                            <ExclamationCircleOutlined style={{ 
                                                fontSize: 48, 
                                                color: token.colorError 
                                            }} />
                                        </div>

                                        {/* 错误信息 */}
                                        <div>
                                            <Typography.Title level={4} style={{ 
                                                margin: 0, 
                                                marginBottom: 12,
                                                color: token.colorText,
                                            }}>
                                                加载历史消息失败
                                            </Typography.Title>
                                            <Text style={{ 
                                                fontSize: 15,
                                                color: token.colorTextSecondary,
                                                lineHeight: 1.6,
                                            }}>
                                                {historyLoadError}
                                            </Text>
                                        </div>

                                        {/* 重试按钮 */}
                                        <Button
                                            type="primary"
                                            size="large"
                                            icon={<SyncOutlined />}
                                            onClick={() => {
                                                if (currentJobId) {
                                                    setHistoryLoadError(null)
                                                    loadHistoryMessages(currentJobId)
                                                }
                                            }}
                                            style={{
                                                height: 48,
                                                fontSize: 16,
                                                fontWeight: 500,
                                                borderRadius: 24,
                                                padding: '0 32px',
                                            }}
                                        >
                                            重新加载
                                        </Button>
                                    </Space>
                                </div>
                            </div>
                        ) : shouldShowChatInterface && messages.length === 0 ? (
                            /* 如果进入历史会话但消息为空，显示 AI 头像和等待图标 */
                            <div style={{ 
                                // padding: '20px 0',
                                marginBottom: 12,
                                display: 'flex',
                                justifyContent: 'flex-start',
                            }}>
                                {/* <div style={{ 
                                    display: 'flex',
                                    alignItems: 'flex-start',
                                    gap: 12,
                                }}>
                                    <div style={{ marginTop: -16 }}>
                                        <AIAvatar 
                                            size={32} 
                                            isTyping={true} 
                                            isLatest={false}
                                        />
                                    </div>
                                    <LoadingOutlined style={{ 
                                        color: '#000000', 
                                        fontSize: 16,
                                        marginTop: 4,
                                    }} />
                                </div> */}
                                <div style={{ 
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 12,
                                }}>
                                    <AIAvatar size={32} isTyping={true} />
                                    <LoadingOutlined style={{ color: '#000000', fontSize: 16 }} />
                                </div>
                            </div>
                        ) : !shouldShowChatInterface ? (
                            /* 如果没有上传文件且当前会话没有消息历史，显示欢迎卡片 */
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                minHeight: 'calc(100vh - 200px)',
                                padding: '40px 20px',
                            }}>
                                <div style={{
                                    maxWidth: 680,
                                    width: '100%',
                                    textAlign: 'center',
                                }}>
                                    <Space direction="vertical" size={40} style={{ width: '100%' }}>
                                        {/* AI头像 */}
                                        <div style={{
                                            width: 96,
                                            height: 96,
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            margin: '0 auto',
                                            background: `linear-gradient(135deg, ${token.colorPrimary}10 0%, ${token.colorPrimary}20 100%)`,
                                            borderRadius: '50%',
                                            padding: 8,
                                            transition: 'all 0.3s ease',
                                        }}
                                        className="welcome-avatar-container"
                                        >
                                            <WelcomeAIAvatar 
                                                size={80} 
                                                onClick={() => {
                                                    if (showFireworks) {
                                                        // 烟花进行中，发射额外的1个烟花
                                                        setExtraFireworkTrigger(prev => prev + 1)
                                                    } else {
                                                        // 没有烟花，开始新的烟花秀（5个）
                                                        setShowFireworks(true)
                                                        setExtraFireworkTrigger(0)
                                                    }
                                                }}
                                            />
                                        </div>

                                        {/* 标题和描述 */}
                                        <div>
                                            <Typography.Title level={2} style={{ 
                                                margin: 0, 
                                                marginBottom: 16,
                                                fontSize: 32,
                                                fontWeight: 600,
                                                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                                                WebkitBackgroundClip: 'text',
                                                WebkitTextFillColor: 'transparent',
                                                backgroundClip: 'text',
                                            }}>
                                                欢迎使用九章智核
                                            </Typography.Title>
                                            <Text style={{ 
                                                fontSize: 17,
                                                color: token.colorTextSecondary,
                                                lineHeight: 1.6,
                                            }}>
                                                我是您的AI助手，可以帮您进行专业的模具成本分析
                                            </Text>
                                        </div>

                                        {/* 功能列表 */}
                                        <div style={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                                            gap: 16,
                                            width: '100%',
                                            textAlign: 'left',
                                        }}>
                                            {[
                                                { icon: '📄', title: '解析CAD文件', desc: '支持DWG和PRT格式' },
                                                { icon: '🔍', title: '特征识别', desc: '自动识别加工特征' },
                                                { icon: '⚙️', title: '工艺推荐', desc: '智能推荐工艺方案' },
                                                { icon: '💰', title: '成本计算', desc: '精确计算成本明细' },
                                                { icon: '📊', title: '报表生成', desc: '生成专业核算报表' },
                                            ].map((item, index) => (
                                                <div
                                                    key={index}
                                                    style={{
                                                        padding: '20px',
                                                        background: token.colorBgContainer,
                                                        border: `1px solid ${token.colorBorderSecondary}`,
                                                        borderRadius: 12,
                                                        transition: 'all 0.3s ease',
                                                        cursor: 'default',
                                                    }}
                                                    onMouseEnter={(e) => {
                                                        e.currentTarget.style.borderColor = token.colorPrimary
                                                        e.currentTarget.style.boxShadow = `0 4px 12px ${token.colorPrimary}20`
                                                        e.currentTarget.style.transform = 'translateY(-2px)'
                                                    }}
                                                    onMouseLeave={(e) => {
                                                        e.currentTarget.style.borderColor = token.colorBorderSecondary
                                                        e.currentTarget.style.boxShadow = 'none'
                                                        e.currentTarget.style.transform = 'translateY(0)'
                                                    }}
                                                >
                                                    <div style={{ fontSize: 32, marginBottom: 12 }}>{item.icon}</div>
                                                    <div style={{ 
                                                        fontSize: 15, 
                                                        fontWeight: 600,
                                                        color: token.colorText,
                                                        marginBottom: 6,
                                                    }}>
                                                        {item.title}
                                                    </div>
                                                    <div style={{ 
                                                        fontSize: 13, 
                                                        color: token.colorTextSecondary,
                                                        lineHeight: 1.5,
                                                    }}>
                                                        {item.desc}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>

                                        {/* 上传按钮 */}
                                        <Button
                                            type="primary"
                                            size="large"
                                            icon={<PaperClipOutlined />}
                                            onClick={handleFileUpload}
                                            style={{
                                                height: 56,
                                                fontSize: 16,
                                                fontWeight: 500,
                                                borderRadius: 28,
                                                padding: '0 40px',
                                                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                                                border: 'none',
                                                boxShadow: '0 4px 16px rgba(102, 126, 234, 0.3)',
                                                transition: 'all 0.3s ease',
                                            }}
                                            onMouseEnter={(e) => {
                                                e.currentTarget.style.transform = 'translateY(-2px)'
                                                e.currentTarget.style.boxShadow = '0 6px 20px rgba(102, 126, 234, 0.4)'
                                            }}
                                            onMouseLeave={(e) => {
                                                e.currentTarget.style.transform = 'translateY(0)'
                                                e.currentTarget.style.boxShadow = '0 4px 16px rgba(102, 126, 234, 0.3)'
                                            }}
                                        >
                                            上传CAD文件开始分析
                                        </Button>
                                    </Space>
                                </div>
                            </div>
                        ) : (
                            <>
                                <MessageList 
                                    messages={messages} 
                                    isTyping={isTyping}
                                    scrollContainerRef={scrollContainerRef}
                                />

                                {/* 交互卡片 */}
                                {interactionCards.length > 0 && (
                                    <InteractionCards cards={interactionCards} />
                                )}
                            </>
                        )}
                    </div>
                </div>

                {/* 透明渐变遮罩 */}
                <div
                    style={{
                        position: "absolute",
                        bottom: 0,
                        left: 0,
                        right: 0,
                        height: "24px", // 进一步减小渐变高度从40px到24px
                        background: `linear-gradient(to top, 
                            #ffffffCC 0%, 
                            #ffffff80 50%, 
                            transparent 100%)`,
                        pointerEvents: "none",
                        zIndex: 1,
                    }}
                />
            </div>

            {/* 输入区域 - 只在已上传文件或当前会话有消息历史时显示 */}
            {shouldShowChatInterface && (
                <div
                    style={{
                        padding: "0 24px 24px", // 移除上内边距，只保留左右和下内边距
                        background: "#ffffff",
                        position: "relative",
                        // 使用 contain 隔离输入区域，防止消息区域影响
                        contain: "layout style",
                        // 确保输入区域始终在最上层
                        zIndex: 10,
                    }}
                >
                {/* 开始核算按钮 - 当收到 awaiting_confirm 阶段且未开始核算且任务未完成时显示 */}
                {hasAwaitingConfirm && !hasPricingMessages && !isTaskCompleted && !isCalculating && (
                    <div
                        style={{
                            maxWidth: 768,
                            margin: "0 auto 10px",
                            padding: "8px 12px",
                            background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                            borderRadius: 12,
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            boxShadow: "0 2px 8px rgba(102, 126, 234, 0.25)",
                            animation: "slideDown 0.3s ease-out",
                            position: "relative",
                            overflow: "hidden",
                        }}
                    >
                        {/* 背景装饰 - 进一步缩小 */}
                        <div
                            style={{
                                position: "absolute",
                                top: -10,
                                right: -10,
                                width: 40,
                                height: 40,
                                background: "rgba(255, 255, 255, 0.1)",
                                borderRadius: "50%",
                                pointerEvents: "none",
                            }}
                        />
                        
                        {/* 图标 - 进一步缩小 */}
                        <div
                            style={{
                                width: 28,
                                height: 28,
                                background: "rgba(255, 255, 255, 0.2)",
                                borderRadius: 8,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: 16,
                                flexShrink: 0,
                            }}
                        >
                            💰
                        </div>
                        
                        {/* 文字内容 - 单行紧凑 */}
                        <div style={{ flex: 1, position: "relative", zIndex: 1 }}>
                            <Text 
                                style={{ 
                                    fontSize: 14, 
                                    color: "#ffffff",
                                    fontWeight: 500,
                                    lineHeight: 1.2,
                                }}
                            >
                                数据审核完成，可开始核算
                            </Text>
                        </div>
                        
                        {/* 按钮 - 进一步缩小 */}
                        <Button
                            type="primary"
                            size="small"
                            onClick={async () => {
                                if (!currentJobId) return;
                                
                                try {
                                    setIsCalculating(true);
                                    
                                    // 调用继续核算 API
                                    await chatService.continueCalculation(currentJobId);
                                    
                                    // 接口成功返回后，保持 isCalculating 为 true
                                    // 不要立即设置为 false，等待 WebSocket 推送价格计算消息
                                    // setIsCalculating(false) 会在收到 pricing_started 或 pricing_completed 消息时自动设置
                                    
                                    message.success('核算已开始，请等待结果...');
                                } catch (error: any) {
                                    console.error('开始核算失败:', error);
                                    message.error(error.message || '开始核算失败');
                                    setIsCalculating(false);
                                }
                            }}
                            style={{
                                minWidth: 80,
                                height: 28,
                                fontSize: 13,
                                fontWeight: 600,
                                background: "rgba(255, 255, 255, 0.25)",
                                color: "#ffffff",
                                border: "1px solid rgba(255, 255, 255, 0.3)",
                                borderRadius: 8,
                                boxShadow: "0 1px 4px rgba(0, 0, 0, 0.1)",
                                position: "relative",
                                zIndex: 1,
                                transition: "all 0.2s ease",
                                padding: "0 12px",
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = "rgba(255, 255, 255, 0.35)";
                                e.currentTarget.style.color = "#ffffff";
                                e.currentTarget.style.transform = "translateY(-1px)";
                                e.currentTarget.style.boxShadow = "0 2px 6px rgba(0, 0, 0, 0.15)";
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = "rgba(255, 255, 255, 0.25)";
                                e.currentTarget.style.color = "#ffffff";
                                e.currentTarget.style.transform = "translateY(0)";
                                e.currentTarget.style.boxShadow = "0 1px 4px rgba(0, 0, 0, 0.1)";
                            }}
                        >
                            开始核算
                        </Button>
                    </div>
                )}
                
                {/* 核算中悬浮提示 */}
                {isCalculating && (
                    <div
                        style={{
                            maxWidth: 768,
                            margin: "0 auto 10px",
                            padding: "8px 12px",
                            background: "linear-gradient(135deg, #52c41a 0%, #389e0d 100%)",
                            borderRadius: 12,
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            boxShadow: "0 2px 8px rgba(82, 196, 26, 0.25)",
                            animation: "slideDown 0.3s ease-out",
                            position: "relative",
                            overflow: "hidden",
                        }}
                    >
                        {/* 背景装饰 - 进一步缩小 */}
                        <div
                            style={{
                                position: "absolute",
                                top: -10,
                                right: -10,
                                width: 40,
                                height: 40,
                                background: "rgba(255, 255, 255, 0.1)",
                                borderRadius: "50%",
                                pointerEvents: "none",
                            }}
                        />
                        
                        {/* 加载图标 - 进一步缩小 */}
                        <div
                            style={{
                                width: 28,
                                height: 28,
                                background: "rgba(255, 255, 255, 0.2)",
                                borderRadius: 8,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                flexShrink: 0,
                            }}
                        >
                            <LoadingOutlined 
                                style={{ 
                                    fontSize: 16, 
                                    color: "#ffffff",
                                }} 
                                spin 
                            />
                        </div>
                        
                        {/* 文字内容 - 单行紧凑 */}
                        <div style={{ flex: 1, position: "relative", zIndex: 1 }}>
                            <Text 
                                style={{ 
                                    fontSize: 14, 
                                    color: "#ffffff",
                                    fontWeight: 500,
                                    lineHeight: 1.2,
                                }}
                            >
                                正在核算成本，请稍候...
                            </Text>
                        </div>
                    </div>
                )}
                
                {/* 任务完成 - 导出报价单按钮 */}
                {isTaskCompleted && (
                    <div
                        style={{
                            maxWidth: 768,
                            margin: "0 auto 10px",
                            padding: "8px 12px",
                            background: "linear-gradient(135deg, #13c2c2 0%, #08979c 100%)",
                            borderRadius: 12,
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            boxShadow: "0 2px 8px rgba(19, 194, 194, 0.25)",
                            animation: "slideDown 0.3s ease-out",
                            position: "relative",
                            overflow: "hidden",
                        }}
                    >
                        {/* 背景装饰 */}
                        <div
                            style={{
                                position: "absolute",
                                top: -10,
                                right: -10,
                                width: 40,
                                height: 40,
                                background: "rgba(255, 255, 255, 0.1)",
                                borderRadius: "50%",
                                pointerEvents: "none",
                            }}
                        />
                        
                        {/* 图标 */}
                        <div
                            style={{
                                width: 28,
                                height: 28,
                                background: "rgba(255, 255, 255, 0.2)",
                                borderRadius: 8,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: 16,
                                flexShrink: 0,
                            }}
                        >
                            ✅
                        </div>
                        
                        {/* 文字内容 */}
                        <div style={{ flex: 1, position: "relative", zIndex: 1 }}>
                            <Text 
                                style={{ 
                                    fontSize: 14, 
                                    color: "#ffffff",
                                    fontWeight: 500,
                                    lineHeight: 1.2,
                                }}
                            >
                                任务完成！可以导出报价单
                            </Text>
                        </div>
                        
                        {/* 导出按钮 */}
                        <Button
                            type="primary"
                            size="small"
                            icon={<DownloadOutlined />}
                            loading={isExporting}
                            onClick={handleExportExcel}
                            style={{
                                minWidth: 100,
                                height: 28,
                                fontSize: 13,
                                fontWeight: 600,
                                background: "rgba(255, 255, 255, 0.25)",
                                color: "#ffffff",
                                border: "1px solid rgba(255, 255, 255, 0.3)",
                                borderRadius: 8,
                                boxShadow: "0 1px 4px rgba(0, 0, 0, 0.1)",
                                position: "relative",
                                zIndex: 1,
                                transition: "all 0.2s ease",
                                padding: "0 12px",
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = "rgba(255, 255, 255, 0.35)";
                                e.currentTarget.style.color = "#ffffff";
                                e.currentTarget.style.transform = "translateY(-1px)";
                                e.currentTarget.style.boxShadow = "0 2px 6px rgba(0, 0, 0, 0.15)";
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = "rgba(255, 255, 255, 0.25)";
                                e.currentTarget.style.color = "#ffffff";
                                e.currentTarget.style.transform = "translateY(0)";
                                e.currentTarget.style.boxShadow = "0 1px 4px rgba(0, 0, 0, 0.1)";
                            }}
                        >
                            导出核价单
                        </Button>
                    </div>
                )}
                
                <div
                    style={{
                        maxWidth: 768,
                        margin: "0 auto",
                    }}
                >
                    {/* 主输入框 */}
                    <div
                        style={{
                            background: token.colorBgContainer,
                            borderRadius: 24,
                            border: `1px solid ${token.colorBorderSecondary}`,
                            boxShadow: "0 2px 6px rgba(0, 0, 0, 0.06)",
                            transition: "all 0.2s ease",
                            position: "relative",
                        }}
                        className="gemini-input-container"
                    >
                        {/* 输入区域 */}
                        <div
                            style={{
                                display: "flex",
                                alignItems: "flex-end",
                                padding: "12px 16px",
                                gap: 12,
                            }}
                        >
                            {/* 文本输入 */}
                            <TextArea
                                placeholder="输入您的问题，或上传CAD文件进行成本分析..."
                                value={inputValue}
                                onChange={(e) => setInputValue(e.target.value)}
                                onKeyDown={handleKeyDown}
                                autoSize={textareaInitialized ? { minRows: 2, maxRows: 8 } : false}
                                variant="borderless"
                                style={{
                                    flex: 1,
                                    fontSize: 16,
                                    lineHeight: "24px",
                                    padding: "8px 0",
                                    resize: "none",
                                    minHeight: "40px", // 设置为一行文本的实际高度（24px + 8px*2 padding）
                                    height: textareaInitialized ? "auto" : "48px", // 初始化前固定高度
                                    transition: textareaInitialized ? "height 0.2s ease" : "none", // 只在初始化后才有过渡动画
                                    // 优化输入性能
                                    transform: "translateZ(0)", // 启用 GPU 加速
                                    willChange: "height", // 提示浏览器优化高度变化
                                }}
                                maxLength={2000}
                            />
                        </div>

                        {/* 工具栏 */}
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                padding: "8px 16px 12px",
                                // borderTop: `1px solid ${token.colorBorderSecondary}`,
                            }}
                        >
                            {/* 左侧工具按钮 */}
                            <div
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 4,
                                }}
                            >
                                {/* <Button
                                    type="text"
                                    size="small"
                                    style={{
                                        height: 32,
                                        padding: "0 12px",
                                        borderRadius: 16,
                                        fontSize: 13,
                                        color: token.colorTextSecondary,
                                        background: token.colorFillQuaternary,
                                        border: "none",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 6,
                                    }}
                                    onClick={handleFileUpload}
                                >
                                    <PaperClipOutlined
                                        style={{ fontSize: 12 }}
                                    />
                                    上传文件
                                </Button> */}


                            </div>

                            {/* 发送按钮或语音按钮 */}
                            {/* 录音状态时始终显示语音按钮，不显示发送按钮 */}
                            {isRecording ? (
                                <Button
                                    type="primary"
                                    icon={<AudioOutlined />}
                                    onClick={handleVoiceRecognition}
                                    style={{
                                        width: 40,
                                        height: 40,
                                        borderRadius: 20,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        background: "#ff4d4f",
                                        borderColor: "#ff4d4f",
                                        color: "white",
                                        transition: "all 0.2s ease",
                                        animation: "pulse 1.5s ease-in-out infinite",
                                    }}
                                    className="voice-btn"
                                />
                            ) : isRecognizing ? (
                                <Button
                                    type="primary"
                                    icon={<LoadingOutlined />}
                                    disabled
                                    style={{
                                        width: 40,
                                        height: 40,
                                        borderRadius: 20,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        background: token.colorPrimary,
                                        borderColor: token.colorPrimary,
                                        color: "white",
                                        transition: "all 0.2s ease",
                                        opacity: 0.8,
                                    }}
                                    className="recognizing-btn"
                                />
                            ) : inputValue.trim() ? (
                                <Button
                                    type="primary"
                                    icon={<SendOutlined />}
                                    onClick={handleSendMessage}
                                    disabled={!inputValue.trim() || isTyping || isStartingReview || isRefreshing || isCalculating || isReprocessing || !canSendAfterWorkflowReady || isReprocessingInHistory}
                                    style={{
                                        width: 40,
                                        height: 40,
                                        borderRadius: 20,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        background: token.colorPrimary,
                                        borderColor: token.colorPrimary,
                                        color: "white",
                                        transition: "all 0.2s ease",
                                    }}
                                    className="send-btn"
                                />
                            ) : (
                                <Button
                                    type="text"
                                    icon={<AudioOutlined />}
                                    onClick={handleVoiceRecognition}
                                    disabled={isTyping || isStartingReview || isRefreshing || isCalculating || isReprocessing}
                                    style={{
                                        width: 40,
                                        height: 40,
                                        borderRadius: 20,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        background: "transparent",
                                        borderColor: "transparent",
                                        color: token.colorTextSecondary,
                                        transition: "all 0.2s ease",
                                    }}
                                    className="voice-btn"
                                />
                            )}
                        </div>
                    </div>

                </div>
            </div>
            )}

            {/* 文件上传模态框 */}
            <FileUpload
                visible={showFileUpload}
                onClose={() => setShowFileUpload(false)}
            />

            {/* 登录弹窗 */}
            <LoginModal
                visible={showLoginModal}
                onClose={() => setShowLoginModal(false)}
                onLoginSuccess={handleLoginSuccess}
            />

            {/* 重命名弹窗 */}
            <Modal
                title="重命名会话"
                open={renameModalVisible}
                onOk={handleSaveRename}
                onCancel={handleCancelRename}
                okText="确定"
                cancelText="取消"
                width={400}
                confirmLoading={renamingLoading}
            >
                <Input
                    value={renameInputValue}
                    onChange={(e) => setRenameInputValue(e.target.value)}
                    onPressEnter={handleSaveRename}
                    placeholder="请输入新的会话名称"
                    autoFocus
                    maxLength={50}
                    disabled={renamingLoading}
                    style={{
                        fontSize: 14,
                    }}
                />
            </Modal>

            {/* 烟花效果 */}
            <Fireworks 
                active={showFireworks}
                extraTrigger={extraFireworkTrigger}
                onComplete={() => setShowFireworks(false)}
            />
        </Flex>
    );
};

export default ChatInterface;

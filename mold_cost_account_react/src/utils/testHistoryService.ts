// 测试历史消息服务的工具函数
import { historyService, HistoryMessage } from '../services/historyService'

// 模拟历史消息数据
export const mockHistoryMessages: HistoryMessage[] = [
  {
    message_id: 1,
    role: 'system',
    content: '审核已启动，共查询到 10 条子图数据',
    timestamp: '2026-01-16T10:00:00',
    metadata: {
      action: 'start_review',
      data_summary: {
        features: 10,
        subgraphs: 2
      }
    }
  },
  {
    message_id: 2,
    role: 'assistant',
    content: '任务初始化...',
    timestamp: '2026-01-16T10:01:00',
    metadata: {
      stage: 'initialization',
      progress: 0
    }
  },
  {
    message_id: 3,
    role: 'assistant',
    content: '正在拆图...',
    timestamp: '2026-01-16T10:02:00',
    metadata: {
      stage: 'file_processing',
      progress: 25
    }
  },
  {
    message_id: 4,
    role: 'assistant',
    content: '正在识别特征...',
    timestamp: '2026-01-16T10:03:00',
    metadata: {
      stage: 'feature_recognition',
      progress: 50
    }
  },
  {
    message_id: 5,
    role: 'assistant',
    content: '正在计算价格...',
    timestamp: '2026-01-16T10:04:00',
    metadata: {
      stage: 'cost_calculation',
      progress: 75
    }
  },
  {
    message_id: 6,
    role: 'user',
    content: '将 UP01 的材质改为 718',
    timestamp: '2026-01-16T10:05:00',
    metadata: {
      user_id: 'a63b7863-5faf-4b00-9ec3-758495b0fb66'
    }
  },
  {
    message_id: 7,
    role: 'assistant',
    content: '修改已应用，请确认',
    timestamp: '2026-01-16T10:05:01',
    metadata: {
      modification_id: 'mod-uuid-xxx',
      parsed_changes: []
    }
  }
]

// 测试消息转换功能
export function testMessageConversion() {
  const convertedMessages = historyService.convertToAppMessages(mockHistoryMessages)
  
  convertedMessages.forEach((msg, index) => {
    const original = mockHistoryMessages[index]
    // console.log(`📋 消息 ${index + 1}:`)
    // console.log(`   原始: ${original.role} - ${original.content}`)
    // console.log(`   转换: ${msg.type} - ${msg.content}`)
    if (msg.progressData) {
      // console.log(`   进度: ${msg.progressData.stage} (${msg.progressData.progress}%)`)
    }
  })
  
  return convertedMessages
}

// 在浏览器控制台中运行测试
if (typeof window !== 'undefined') {
  (window as any).testHistoryService = testMessageConversion
  // console.log('💡 在控制台运行 testHistoryService() 来测试历史消息转换')
}
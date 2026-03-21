import React, { useRef, useEffect } from 'react'
import { Card, List, Typography, Tag, Space, Button } from 'antd'
import { ClearOutlined, DownloadOutlined } from '@ant-design/icons'
import { WebSocketMessage } from '../services/websocketService'

const { Text } = Typography

interface WebSocketLogProps {
  messages: WebSocketMessage[]
  onClear?: () => void
  maxHeight?: number
}

const WebSocketLog: React.FC<WebSocketLogProps> = ({
  messages,
  onClear,
  maxHeight = 300,
}) => {
  const listRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages])

  const getMessageTypeColor = (type: string) => {
    switch (type) {
      case 'connected':
        return 'green'
      case 'progress':
        return 'blue'
      case 'need_user_input':
        return 'orange'
      case 'interaction_response_received':
        return 'cyan'
      case 'error':
        return 'red'
      case 'pong':
        return 'gray'
      default:
        return 'default'
    }
  }

  const formatMessage = (message: WebSocketMessage) => {
    const timestamp = new Date().toLocaleTimeString()
    
    switch (message.type) {
      case 'connected':
        return `[${timestamp}] 连接成功: ${message.message}`
      case 'progress':
        return `[${timestamp}] 进度更新: ${message.data?.stage} - ${message.data?.progress}%`
      case 'need_user_input':
        return `[${timestamp}] 需要用户输入: ${message.data?.title}`
      case 'interaction_response_received':
        return `[${timestamp}] 响应已接收: ${message.message}`
      case 'error':
        return `[${timestamp}] 错误: ${message.error}`
      case 'pong':
        return `[${timestamp}] 心跳响应`
      default:
        return `[${timestamp}] ${message.type}: ${JSON.stringify(message)}`
    }
  }

  const exportLogs = () => {
    const logs = messages.map(formatMessage).join('\n')
    const blob = new Blob([logs], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `websocket-logs-${new Date().toISOString().slice(0, 19)}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <Card
      title="WebSocket 消息日志"
      size="small"
      extra={
        <Space>
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            onClick={exportLogs}
            disabled={messages.length === 0}
          >
            导出
          </Button>
          <Button
            type="text"
            size="small"
            icon={<ClearOutlined />}
            onClick={onClear}
            disabled={messages.length === 0}
          >
            清空
          </Button>
        </Space>
      }
      style={{ marginBottom: 16 }}
    >
      <div
        ref={listRef}
        style={{
          maxHeight,
          overflowY: 'auto',
          border: '1px solid #f0f0f0',
          borderRadius: 4,
          padding: 8,
          backgroundColor: '#fafafa',
        }}
      >
        {messages.length === 0 ? (
          <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: 20 }}>
            暂无消息
          </Text>
        ) : (
          <List
            size="small"
            dataSource={messages}
            renderItem={(message, index) => (
              <List.Item style={{ padding: '4px 0', borderBottom: 'none' }}>
                <Space size={8} style={{ width: '100%' }}>
                  <Tag color={getMessageTypeColor(message.type)} style={{ minWidth: 60, textAlign: 'center' }}>
                    {message.type}
                  </Tag>
                  <Text
                    style={{
                      fontSize: 12,
                      fontFamily: 'monospace',
                      flex: 1,
                      wordBreak: 'break-all',
                    }}
                  >
                    {formatMessage(message)}
                  </Text>
                </Space>
              </List.Item>
            )}
          />
        )}
      </div>
    </Card>
  )
}

export default WebSocketLog
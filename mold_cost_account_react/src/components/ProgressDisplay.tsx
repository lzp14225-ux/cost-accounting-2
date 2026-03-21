import React from 'react'
import { Card, Progress, Typography, Space, Tag } from 'antd'
import { LoadingOutlined, CheckCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { ProgressData } from '../services/websocketService'
import { ConnectionStatus } from '../services/websocketService'

const { Title, Text } = Typography

interface ProgressDisplayProps {
  progressData: ProgressData | null
  connectionStatus: ConnectionStatus
  jobId?: string
}

const ProgressDisplay: React.FC<ProgressDisplayProps> = ({
  progressData,
  connectionStatus,
  jobId,
}) => {
  const getStatusIcon = () => {
    switch (connectionStatus) {
      case 'connected':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />
      case 'connecting':
        return <LoadingOutlined style={{ color: '#1890ff' }} />
      case 'error':
        return <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
      default:
        return <ExclamationCircleOutlined style={{ color: '#d9d9d9' }} />
    }
  }

  const getStatusText = () => {
    switch (connectionStatus) {
      case 'connected':
        return '已连接'
      case 'connecting':
        return '连接中...'
      case 'disconnected':
        return '未连接'
      case 'error':
        return '连接错误'
      default:
        return '未知状态'
    }
  }

  const getStatusColor = () => {
    switch (connectionStatus) {
      case 'connected':
        return 'success'
      case 'connecting':
        return 'processing'
      case 'error':
        return 'error'
      default:
        return 'default'
    }
  }

  return (
    <Card
      title={
        <Space>
          <span>任务进度</span>
          {jobId && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              ID: {jobId.substring(0, 8)}...
            </Text>
          )}
        </Space>
      }
      extra={
        <Space>
          {getStatusIcon()}
          <Tag color={getStatusColor()}>{getStatusText()}</Tag>
        </Space>
      }
      style={{ marginBottom: 16 }}
    >
      {progressData ? (
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <div>
            <div style={{ marginBottom: 8 }}>
              <Text strong>{progressData.stage}</Text>
            </div>
            <Progress
              percent={progressData.progress}
              status={progressData.progress === 100 ? 'success' : 'active'}
              strokeColor={{
                '0%': '#108ee9',
                '100%': '#87d068',
              }}
            />
          </div>
          
          {progressData.message && (
            <div>
              <Text type="secondary">{progressData.message}</Text>
            </div>
          )}
        </Space>
      ) : (
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <Text type="secondary">
            {connectionStatus === 'connected' ? '等待任务开始...' : '请先建立连接'}
          </Text>
        </div>
      )}
    </Card>
  )
}

export default ProgressDisplay
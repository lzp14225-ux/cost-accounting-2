import React from 'react'
import { 
  Progress, 
  Card, 
  Typography, 
  Space, 
  Tag, 
  Flex, 
  Steps,
  Alert,
  theme,
} from 'antd'
import { 
  LoadingOutlined, 
  CheckCircleOutlined, 
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useAppStore } from '../store/useAppStore'

const { Text, Title } = Typography

interface ProgressIndicatorProps {
  jobId: string
}

const ProgressIndicator: React.FC<ProgressIndicatorProps> = ({ jobId }) => {
  const { jobs } = useAppStore()
  const { token } = theme.useToken()
  
  const job = jobs.find(j => j.id === jobId)
  if (!job) return null

  const getStatusIcon = () => {
    switch (job.status) {
      case 'processing':
        return <LoadingOutlined spin style={{ color: token.colorPrimary }} />
      case 'completed':
        return <CheckCircleOutlined style={{ color: token.colorSuccess }} />
      case 'failed':
        return <ExclamationCircleOutlined style={{ color: token.colorError }} />
      case 'need_user_input':
        return <ClockCircleOutlined style={{ color: token.colorWarning }} />
      default:
        return <LoadingOutlined spin style={{ color: token.colorTextSecondary }} />
    }
  }

  const getStatusColor = () => {
    switch (job.status) {
      case 'processing':
        return token.colorPrimary
      case 'completed':
        return token.colorSuccess
      case 'failed':
        return token.colorError
      case 'need_user_input':
        return token.colorWarning
      default:
        return token.colorTextSecondary
    }
  }

  const getStatusText = () => {
    switch (job.status) {
      case 'pending':
        return '等待处理'
      case 'processing':
        return '处理中'
      case 'need_user_input':
        return '等待用户输入'
      case 'completed':
        return '已完成'
      case 'failed':
        return '处理失败'
      case 'archived':
        return '已归档'
      default:
        return job.status
    }
  }

  const stages = [
    { key: 'initializing', label: '初始化', icon: <LoadingOutlined /> },
    { key: 'cad_parsing', label: 'CAD解析', icon: <FileTextOutlined /> },
    { key: 'feature_recognition', label: '特征识别', icon: <LoadingOutlined /> },
    { key: 'waiting_input', label: '等待输入', icon: <ClockCircleOutlined /> },
    { key: 'decision', label: '工艺决策', icon: <LoadingOutlined /> },
    { key: 'pricing', label: '价格计算', icon: <LoadingOutlined /> },
    { key: 'report_generation', label: '报表生成', icon: <FileTextOutlined /> },
    { key: 'completed', label: '完成', icon: <CheckCircleOutlined /> },
  ]

  const currentStageIndex = stages.findIndex(s => s.key === job.stage || s.label === job.stage)
  const progressPercent = Math.max(job.progress, 0)

  return (
    <Card 
      style={{ 
        margin: '16px 0',
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
        background: token.colorBgContainer,
      }}
      styles={{ body: { padding: 20 } }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        {/* 头部信息 */}
        <Flex justify="space-between" align="center">
          <Flex align="center" gap={12}>
            {getStatusIcon()}
            <div>
              <Title level={5} style={{ margin: 0, color: token.colorText }}>
                任务进度
              </Title>
              <Text type="secondary" style={{ fontSize: 12 }}>
                任务ID: {job.id.slice(0, 8)}...
              </Text>
            </div>
          </Flex>
          <Tag color={getStatusColor()} style={{ borderRadius: token.borderRadius }}>
            {getStatusText()}
          </Tag>
        </Flex>

        {/* 进度条 */}
        <div>
          <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
            <Text style={{ fontSize: 13, color: token.colorTextSecondary }}>
              当前阶段: {stages.find(s => s.key === job.stage || s.label === job.stage)?.label || job.stage}
            </Text>
            <Text style={{ fontSize: 13, fontWeight: 500, color: token.colorText }}>
              {progressPercent}%
            </Text>
          </Flex>
          
          <Progress
            percent={progressPercent}
            strokeColor={{
              '0%': token.colorPrimary,
              '100%': token.colorSuccess,
            }}
            trailColor={token.colorFillSecondary}
            showInfo={false}
            strokeWidth={8}
          />
        </div>

        {/* 阶段步骤 */}
        <Steps
          current={currentStageIndex}
          size="small"
          items={stages.slice(0, 7).map((stage, index) => ({
            title: stage.label,
            icon: index === currentStageIndex ? stage.icon : undefined,
            status: index < currentStageIndex ? 'finish' : 
                   index === currentStageIndex ? 'process' : 'wait',
          }))}
          style={{ marginTop: 8 }}
        />

        {/* 详细信息 */}
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {job.subgraphsCount && (
            <Flex justify="space-between" align="center">
              <Text type="secondary" style={{ fontSize: 12 }}>
                识别子图数量
              </Text>
              <Tag>{job.subgraphsCount} 个</Tag>
            </Flex>
          )}

          {job.totalCost && (
            <Alert
              message={
                <Flex justify="space-between" align="center">
                  <Text style={{ fontSize: 14, fontWeight: 500 }}>
                    预估总成本
                  </Text>
                  <Text style={{ fontSize: 16, fontWeight: 600, color: token.colorSuccess }}>
                    ¥{job.totalCost.toFixed(2)}
                  </Text>
                </Flex>
              }
              type="success"
              showIcon={false}
              style={{
                background: token.colorSuccessBg,
                border: `1px solid ${token.colorSuccessBorder}`,
                borderRadius: token.borderRadius,
              }}
            />
          )}

          {job.errorMessage && (
            <Alert
              message="处理错误"
              description={job.errorMessage}
              type="error"
              showIcon
              style={{
                borderRadius: token.borderRadius,
              }}
            />
          )}
        </Space>
      </Space>
    </Card>
  )
}

export default ProgressIndicator
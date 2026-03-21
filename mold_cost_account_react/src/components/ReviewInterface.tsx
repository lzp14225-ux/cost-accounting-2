import React, { useState, useEffect } from 'react'
import { Card, Table, Button, Input, Modal, message, Space, Typography, Tag, Descriptions } from 'antd'
import { EditOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { ReviewStatus, ParsedChange } from '../services/reviewService'
import { chatService } from '../services/chatService'

const { TextArea } = Input
const { Text, Title } = Typography

interface ReviewInterfaceProps {
  jobId: string
  reviewStarted?: boolean  // 新增：标记审核是否已启动
  onModificationSubmitted?: (changes: ParsedChange[]) => void
  onReviewCompleted?: () => void
}

const ReviewInterface: React.FC<ReviewInterfaceProps> = ({
  jobId,
  reviewStarted = false,  // 默认为false
  onModificationSubmitted,
  onReviewCompleted,
}) => {
  const [loading, setLoading] = useState(false)
  const [reviewStatus] = useState<ReviewStatus | null>(null)  // 保留但不再使用
  const [modificationText, setModificationText] = useState('')
  const [pendingChanges, setPendingChanges] = useState<ParsedChange[]>([])
  const [showConfirmModal, setShowConfirmModal] = useState(false)
  const [confirmComment, setConfirmComment] = useState('')

  // 组件挂载时加载状态 - 已禁用
  // 根据文档，审核数据通过 WebSocket 推送，不需要主动查询
  useEffect(() => {
    console.log('ReviewInterface 已挂载，等待 WebSocket 推送审核数据')
    // 不再调用 loadReviewStatus
  }, [jobId, reviewStarted])
  const handleSubmitModification = async () => {
    if (!modificationText.trim()) {
      message.warning('请输入修改指令')
      return
    }

    setLoading(true)
    try {
      // 保存当前的 jobId，用于后续验证
      const requestJobId = jobId;
      
      const result = await chatService.submitModification(jobId, modificationText.trim())
      
      // 检查当前页面的 job_id 是否与请求时的 job_id 相同
      // 如果用户在请求期间切换了会话，则不处理返回的数据
      if (requestJobId !== jobId) {
        // console.log('⚠️ 会话已切换，忽略旧会话的响应', {
        //   requestJobId,
        //   currentJobId: jobId
        // });
        setLoading(false);
        return;
      }
      
      // 安全地处理可能为 undefined 的 parsed_changes
      const parsedChanges = result.data?.parsed_changes || []
      setPendingChanges(parsedChanges)
      setShowConfirmModal(true)
      setModificationText('')
      
      message.success('修改指令已解析，请确认修改内容')
      onModificationSubmitted?.(parsedChanges)
      
    } catch (error: any) {
      console.error('提交修改失败:', error)
      message.error(error.message || '提交修改失败')
    } finally {
      setLoading(false)
    }
  }

  // 确认修改
  const handleConfirmModification = async () => {
    setLoading(true)
    try {
      await chatService.confirmModification(jobId, confirmComment.trim() || undefined)
      
      message.success('修改已确认并保存')
      setShowConfirmModal(false)
      setPendingChanges([])
      setConfirmComment('')
      
      // 不再重新加载审核状态，等待 WebSocket 推送 review_completed 消息
      
      if (onReviewCompleted) {
        onReviewCompleted()
      }
      
    } catch (error: any) {
      console.error('确认修改失败:', error)
      message.error(error.message || '确认修改失败')
    } finally {
      setLoading(false)
    }
  }

  // 取消修改
  const handleCancelModification = () => {
    setShowConfirmModal(false)
    setPendingChanges([])
    setConfirmComment('')
  }

  // 获取状态标签
  const getStatusTag = (status: ReviewStatus['review_status']) => {
    const statusConfig = {
      'pending_completion': { color: 'orange', text: '等待补全' },
      'reviewing': { color: 'blue', text: '审核中' },
      'completed': { color: 'green', text: '已完成' },
    }
    
    const config = statusConfig[status] || { color: 'default', text: '未知' }
    return <Tag color={config.color}>{config.text}</Tag>
  }

  // 修改变更表格列
  const changeColumns = [
    {
      title: '表名',
      dataIndex: 'table',
      key: 'table',
    },
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
    },
    {
      title: '字段',
      dataIndex: 'field',
      key: 'field',
    },
    {
      title: '原值',
      dataIndex: 'old_value',
      key: 'old_value',
      render: (value: any) => <Text code>{String(value)}</Text>,
    },
    {
      title: '新值',
      dataIndex: 'new_value',
      key: 'new_value',
      render: (value: any) => <Text code type="success">{String(value)}</Text>,
    },
  ]

  // 组件挂载时加载状态 - 已禁用
  // 根据文档，审核数据通过 WebSocket 推送，不需要主动查询
  useEffect(() => {
    console.log('ReviewInterface 已挂载，等待 WebSocket 推送审核数据')
    // 不再调用 loadReviewStatus
  }, [jobId, reviewStarted])

  // 如果审核未启动，不显示组件
  if (!reviewStarted) {
    return null
  }

  if (!reviewStatus) {
    return (
      <Card title="审核状态" loading>
        <Text type="secondary">正在加载审核状态...</Text>
      </Card>
    )
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      {/* 审核状态卡片 */}
      <Card title="审核状态" size="small">
        <Descriptions column={2} size="small">
          <Descriptions.Item label="状态">
            {getStatusTag(reviewStatus.review_status)}
          </Descriptions.Item>
          <Descriptions.Item label="锁定状态">
            {reviewStatus.is_locked ? (
              <Tag color="red">🔒 已锁定</Tag>
            ) : (
              <Tag color="green">🔓 未锁定</Tag>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="修改次数">
            {reviewStatus.modifications_count}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {new Date(reviewStatus.created_at).toLocaleString()}
          </Descriptions.Item>
          {reviewStatus.last_modified_at && (
            <Descriptions.Item label="最后修改">
              {new Date(reviewStatus.last_modified_at).toLocaleString()}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {/* 修改指令输入 */}
      {reviewStatus.review_status === 'reviewing' && reviewStatus.is_locked && (
        <Card title="提交修改指令" size="small">
          <Space direction="vertical" style={{ width: '100%' }}>
            <TextArea
              placeholder="请输入修改指令，例如：将 UP01 的材质改为 718"
              value={modificationText}
              onChange={(e) => setModificationText(e.target.value)}
              rows={3}
              maxLength={500}
              showCount
            />
            <Button
              type="primary"
              icon={<EditOutlined />}
              onClick={handleSubmitModification}
              loading={loading}
              disabled={!modificationText.trim()}
            >
              提交修改
            </Button>
          </Space>
        </Card>
      )}

      {/* 修改确认模态框 */}
      <Modal
        title="确认修改"
        open={showConfirmModal}
        onOk={handleConfirmModification}
        onCancel={handleCancelModification}
        okText="确认修改"
        cancelText="取消"
        confirmLoading={loading}
        width={800}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <div>
            <Title level={5}>
              <ExclamationCircleOutlined style={{ color: '#faad14', marginRight: 8 }} />
              以下修改将被应用到数据库：
            </Title>
            
            <Table
              dataSource={pendingChanges}
              columns={changeColumns}
              rowKey={(record, index) => `${record.table}-${record.id}-${record.field}-${index}`}
              pagination={false}
              size="small"
              bordered
            />
          </div>

          <div>
            <Text strong>备注（可选）：</Text>
            <TextArea
              placeholder="请输入审核备注..."
              value={confirmComment}
              onChange={(e) => setConfirmComment(e.target.value)}
              rows={2}
              maxLength={200}
              showCount
            />
          </div>
        </Space>
      </Modal>
    </Space>
  )
}

export default ReviewInterface
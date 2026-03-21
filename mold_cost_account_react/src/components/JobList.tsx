import React, { useState } from 'react'
import { 
  Table, 
  Tag, 
  Button, 
  Space, 
  Typography, 
  Card, 
  Input, 
  Select,
  DatePicker,
  Progress,
  Tooltip,
  Modal,
  Descriptions,
  Flex,
  Badge,
  theme,
} from 'antd'
import { 
  EyeOutlined, 
  DownloadOutlined, 
  ReloadOutlined,
  SearchOutlined,
  FileTextOutlined,
  CalendarOutlined,
  FilterOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { Dayjs } from 'dayjs'
import isBetween from 'dayjs/plugin/isBetween'
import { useAppStore, Job } from '../store/useAppStore'

dayjs.extend(isBetween)

const { Title } = Typography
const { RangePicker } = DatePicker

const JobList: React.FC = () => {
  const { jobs, setCurrentJobId, setCurrentView } = useAppStore()
  const { token } = theme.useToken()
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending':
        return 'default'
      case 'processing':
        return 'processing'
      case 'need_user_input':
        return 'warning'
      case 'completed':
        return 'success'
      case 'failed':
        return 'error'
      case 'archived':
        return 'default'
      default:
        return 'default'
    }
  }

  const getStatusText = (status: string) => {
    switch (status) {
      case 'pending':
        return '等待处理'
      case 'processing':
        return '处理中'
      case 'need_user_input':
        return '等待输入'
      case 'completed':
        return '已完成'
      case 'failed':
        return '处理失败'
      case 'archived':
        return '已归档'
      default:
        return status
    }
  }

  const filteredJobs = jobs.filter(job => {
    // 文本搜索
    if (searchText) {
      const searchLower = searchText.toLowerCase()
      const matchText = 
        job.id.toLowerCase().includes(searchLower) ||
        job.dwgFile?.name.toLowerCase().includes(searchLower) ||
        job.prtFile?.name.toLowerCase().includes(searchLower) ||
        job.stage.toLowerCase().includes(searchLower)
      
      if (!matchText) return false
    }

    // 状态筛选
    if (statusFilter && job.status !== statusFilter) {
      return false
    }

    // 日期范围筛选
    if (dateRange) {
      const jobDate = dayjs(job.createdAt)
      if (!jobDate.isBetween(dateRange[0], dateRange[1], 'day', '[]')) {
        return false
      }
    }

    return true
  })

  const columns: ColumnsType<Job> = [
    {
      title: '任务ID',
      dataIndex: 'id',
      key: 'id',
      width: 120,
      render: (id: string) => (
        <Tooltip title={id}>
          <code style={{ fontSize: 12 }}>
            {id.slice(0, 8)}...
          </code>
        </Tooltip>
      ),
    },
    {
      title: '文件名',
      key: 'fileName',
      render: (_, record) => (
        <div>
          {record.dwgFile && (
            <div style={{ fontSize: 13, marginBottom: 2 }}>
              📄 {record.dwgFile.name}
            </div>
          )}
          {record.prtFile && (
            <div style={{ fontSize: 13 }}>
              🔧 {record.prtFile.name}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>
          {getStatusText(status)}
        </Tag>
      ),
    },
    {
      title: '进度',
      key: 'progress',
      width: 120,
      render: (_, record) => (
        <div>
          <Progress 
            percent={record.progress} 
            size="small" 
            showInfo={false}
            strokeColor={token.colorPrimary}
          />
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
            {record.stage}
          </div>
        </div>
      ),
    },
    {
      title: '子图数量',
      dataIndex: 'subgraphsCount',
      key: 'subgraphsCount',
      width: 80,
      render: (count: number) => count || '-',
    },
    {
      title: '总成本',
      dataIndex: 'totalCost',
      key: 'totalCost',
      width: 100,
      render: (cost: number) => 
        cost ? `¥${cost.toFixed(2)}` : '-',
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 120,
      render: (date: Date) => dayjs(date).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button
              type="text"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => {
                setSelectedJob(record)
                setDetailVisible(true)
              }}
            />
          </Tooltip>
          
          <Tooltip title="继续对话">
            <Button
              type="text"
              size="small"
              icon={<FileTextOutlined />}
              onClick={() => {
                setCurrentJobId(record.id)
                setCurrentView('chat')
              }}
            />
          </Tooltip>

          {record.status === 'completed' && (
            <Tooltip title="下载报表">
              <Button
                type="text"
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => {
                  // TODO: 实现下载功能
                }}
              />
            </Tooltip>
          )}

          {record.status === 'failed' && (
            <Tooltip title="重新处理">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => {
                  // TODO: 实现重新处理功能
                }}
              />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24, height: '100%', overflow: 'auto' }}>
      <Card
        style={{
          borderRadius: token.borderRadiusLG,
          boxShadow: token.boxShadowTertiary,
        }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={24}>
          {/* 页面标题 */}
          <Flex justify="space-between" align="center">
            <Title level={3} style={{ margin: 0 }}>
              任务列表
            </Title>
            <Badge count={jobs.length} showZero color={token.colorPrimary}>
              <Button icon={<FilterOutlined />}>
                全部任务
              </Button>
            </Badge>
          </Flex>
          
          {/* 筛选器 */}
          <Card
            size="small"
            title={
              <Flex align="center" gap={8}>
                <SearchOutlined />
                <span>筛选条件</span>
              </Flex>
            }
            style={{
              background: token.colorFillAlter,
              border: `1px solid ${token.colorBorderSecondary}`,
            }}
          >
            <Flex gap={16} wrap="wrap">
              <Input
                placeholder="搜索任务ID、文件名或阶段"
                prefix={<SearchOutlined />}
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                style={{ width: 280 }}
                allowClear
              />
              
              <Select
                placeholder="筛选状态"
                value={statusFilter}
                onChange={setStatusFilter}
                style={{ width: 150 }}
                allowClear
              >
                <Select.Option value="pending">等待处理</Select.Option>
                <Select.Option value="processing">处理中</Select.Option>
                <Select.Option value="need_user_input">等待输入</Select.Option>
                <Select.Option value="completed">已完成</Select.Option>
                <Select.Option value="failed">处理失败</Select.Option>
                <Select.Option value="archived">已归档</Select.Option>
              </Select>

              <RangePicker
                value={dateRange}
                onChange={(dates) => {
                  if (dates && dates[0] && dates[1]) {
                    setDateRange([dates[0], dates[1]])
                  } else {
                    setDateRange(null)
                  }
                }}
                style={{ width: 280 }}
                placeholder={['开始日期', '结束日期']}
                suffixIcon={<CalendarOutlined />}
              />
            </Flex>
          </Card>

          {/* 数据表格 */}
          <Table
            columns={columns}
            dataSource={filteredJobs}
            rowKey="id"
            pagination={{
              pageSize: 20,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total, range) => 
                `第 ${range[0]}-${range[1]} 条，共 ${total} 条`,
              style: { marginTop: 16 },
            }}
            scroll={{ x: 1200 }}
            style={{
              background: token.colorBgContainer,
              borderRadius: token.borderRadius,
            }}
          />
        </Space>
      </Card>

      {/* 任务详情模态框 */}
      <Modal
        title="任务详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailVisible(false)}>
            关闭
          </Button>,
          selectedJob?.status === 'completed' && (
            <Button key="download" type="primary" icon={<DownloadOutlined />}>
              下载报表
            </Button>
          ),
        ]}
        width={800}
      >
        {selectedJob && (
          <Descriptions column={2} bordered>
            <Descriptions.Item label="任务ID" span={2}>
              <code>{selectedJob.id}</code>
            </Descriptions.Item>
            
            <Descriptions.Item label="状态">
              <Tag color={getStatusColor(selectedJob.status)}>
                {getStatusText(selectedJob.status)}
              </Tag>
            </Descriptions.Item>
            
            <Descriptions.Item label="当前阶段">
              {selectedJob.stage}
            </Descriptions.Item>
            
            <Descriptions.Item label="进度">
              <Progress 
                percent={selectedJob.progress} 
                size="small"
                strokeColor="#10a37f"
              />
            </Descriptions.Item>
            
            <Descriptions.Item label="子图数量">
              {selectedJob.subgraphsCount || '-'}
            </Descriptions.Item>

            {selectedJob.dwgFile && (
              <Descriptions.Item label="DWG文件" span={2}>
                <div>
                  <div>{selectedJob.dwgFile.name}</div>
                  <div style={{ fontSize: 12, color: '#6b7280' }}>
                    {(selectedJob.dwgFile.size / 1024 / 1024).toFixed(2)} MB
                  </div>
                </div>
              </Descriptions.Item>
            )}

            {selectedJob.prtFile && (
              <Descriptions.Item label="PRT文件" span={2}>
                <div>
                  <div>{selectedJob.prtFile.name}</div>
                  <div style={{ fontSize: 12, color: '#6b7280' }}>
                    {(selectedJob.prtFile.size / 1024 / 1024).toFixed(2)} MB
                  </div>
                </div>
              </Descriptions.Item>
            )}

            {selectedJob.totalCost && (
              <Descriptions.Item label="总成本" span={2}>
                <span style={{ fontSize: 16, fontWeight: 'bold', color: '#059669' }}>
                  ¥{selectedJob.totalCost.toFixed(2)}
                </span>
              </Descriptions.Item>
            )}

            <Descriptions.Item label="创建时间">
              {dayjs(selectedJob.createdAt).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
            
            <Descriptions.Item label="更新时间">
              {dayjs(selectedJob.updatedAt).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>

            {selectedJob.errorMessage && (
              <Descriptions.Item label="错误信息" span={2}>
                <div style={{ 
                  padding: 8, 
                  background: '#fef2f2', 
                  borderRadius: 4,
                  color: '#dc2626',
                }}>
                  {selectedJob.errorMessage}
                </div>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}

export default JobList
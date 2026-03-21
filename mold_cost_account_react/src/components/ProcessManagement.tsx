import React, { useState, useEffect, useRef } from 'react'
import { 
  Typography, 
  Button, 
  Space, 
  Flex,
  theme,
  Table,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  message,
  Popconfirm,
  Tooltip,
  Pagination,
} from 'antd'
import { 
  PlusOutlined,
  ToolOutlined,
  MenuOutlined,
  EditOutlined,
  DeleteOutlined,
  SearchOutlined,
  ReloadOutlined,
  CloseOutlined,
  DownOutlined,
  UpOutlined,
} from '@ant-design/icons'
import { useAppStore } from '../store/useAppStore'

import {
  ProcessRule,
  CreateRuleParams,
  UpdateRuleParams,
  QueryRulesParams,
  FeatureType,
  FeatureTypeLabels,
  getFeatureTypeLabel,
  getProcessRules,
  createProcessRule,
  updateProcessRule,
  deleteProcessRule,
  batchDeleteProcessRules,
} from '../api/processRules'

const { Text } = Typography

// 组件外部的缓存标记，防止重复请求
let isLoadingCache = false
let lastLoadTime = 0
const LOAD_DEBOUNCE_TIME = 300 // 300ms 内的重复请求会被忽略

const ProcessManagement: React.FC = () => {
  const { token } = theme.useToken()
  const { setMobileDrawerVisible, setCurrentView } = useAppStore()
  
  const [loading, setLoading] = useState(false)
  const [rules, setRules] = useState<ProcessRule[]>([])
  const [total, setTotal] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [isSmallScreen, setIsSmallScreen] = useState(window.innerWidth < 960)
  const [collapsed, setCollapsed] = useState(true) // 搜索表单折叠状态
  const [gridCols, setGridCols] = useState(3) // Grid 列数
  
  // 筛选条件
  const [filters, setFilters] = useState<QueryRulesParams>({})
  
  // 弹窗状态
  const [modalVisible, setModalVisible] = useState(false)
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create')
  const [editingRule, setEditingRule] = useState<ProcessRule | null>(null)
  const [submitting, setSubmitting] = useState(false) // 提交状态
  
  const [form] = Form.useForm()
  
  // 用于跟踪是否是首次加载
  const isFirstLoad = useRef(true)

  // 计算 Grid 列数的函数
  const calculateGridCols = (width: number): number => {
    if (width < 767) return 1      // xs: 1列
    if (width < 1200) return 2     // sm: 2列
    return 3                        // md及以上: 3列
  }

  // 监听窗口大小变化
  useEffect(() => {
    const handleResize = () => {
      const width = window.innerWidth
      setIsSmallScreen(width < 960)
      setGridCols(calculateGridCols(width))
    }
    
    // 初始化时计算一次
    handleResize()
    
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // 加载规则列表
  const loadRules = async () => {
    // 防抖：如果距离上次加载时间小于阈值，则忽略
    const now = Date.now()
    if (isLoadingCache || (now - lastLoadTime < LOAD_DEBOUNCE_TIME)) {
      return
    }
    
    isLoadingCache = true
    lastLoadTime = now
    setLoading(true)
    
    try {
      const response = await getProcessRules({
        page: currentPage,
        page_size: pageSize,
        ...filters,
      })
      
      if (response.success && response.data) {
        // 调试：打印第一条数据的特征类型
        if (response.data.data.length > 0) {
          console.log('第一条规则的特征类型:', response.data.data[0].feature_type)
          console.log('特征类型的类型:', typeof response.data.data[0].feature_type)
          console.log('FeatureTypeLabels:', FeatureTypeLabels)
        }
        setRules(response.data.data)
        setTotal(response.data.total)
      }
    } catch (error: any) {
      message.error(error.message || '加载规则列表失败')
    } finally {
      setLoading(false)
      isLoadingCache = false
    }
  }

  // 初始加载
  useEffect(() => {
    if (isFirstLoad.current) {
      isFirstLoad.current = false
      loadRules()
    }
  }, [])
  
  // 监听分页和筛选条件变化
  useEffect(() => {
    if (!isFirstLoad.current) {
      loadRules()
    }
  }, [currentPage, pageSize, filters.feature_type]) // 添加 filters.feature_type 监听

  // 打开新增弹窗
  const handleCreate = () => {
    setModalMode('create')
    setEditingRule(null)
    form.resetFields() // 清除表单数据
    setModalVisible(true)
  }

  // 打开编辑弹窗
  const handleEdit = (record: ProcessRule) => {
    setModalMode('edit')
    setEditingRule(record)
    form.resetFields() // 清除表单数据
    form.setFieldsValue(record) // 设置编辑数据
    setModalVisible(true)
  }

  // 提交表单
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      
      setSubmitting(true)
      
      if (modalMode === 'create') {
        await createProcessRule(values as CreateRuleParams)
        message.success('规则创建成功')
      } else {
        await updateProcessRule(editingRule!.id, values as UpdateRuleParams)
        message.success('规则更新成功')
      }
      
      setModalVisible(false)
      form.resetFields()
      loadRules()
    } catch (error: any) {
      if (error.errorFields) {
        // 表单验证错误
        return
      }
      message.error(error.message || '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  // 删除单个规则
  const handleDelete = async (ruleId: string) => {
    try {
      await deleteProcessRule(ruleId)
      message.success('规则删除成功')
      loadRules()
    } catch (error: any) {
      message.error(error.message || '删除失败')
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请选择要删除的规则')
      return
    }
    
    Modal.confirm({
      title: '批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 条规则吗？`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await batchDeleteProcessRules(selectedRowKeys as string[])
          message.success(`成功删除 ${selectedRowKeys.length} 条规则`)
          setSelectedRowKeys([])
          loadRules()
        } catch (error: any) {
          message.error(error.message || '批量删除失败')
        }
      },
    })
  }

  // 表格列定义
  const columns = [
    {
      title: '规则ID',
      dataIndex: 'id',
      key: 'id',
      width: 120,
      fixed: 'left' as const,
      align: 'center' as const,
    },
    {
      title: '规则名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      align: 'center' as const,
      ellipsis: {
        showTitle: false,
      },
      render: (name: string) => (
        <Tooltip title={name} placement="top">
          <div style={{ 
            width: '100%', 
            overflow: 'hidden', 
            textOverflow: 'ellipsis', 
            whiteSpace: 'nowrap' 
          }}>
            {name}
          </div>
        </Tooltip>
      ),
    },
    {
      title: '特征类型',
      dataIndex: 'feature_type',
      key: 'feature_type',
      width: 100,
      align: 'center' as const,
      render: (type: FeatureType) => {
        const label = getFeatureTypeLabel(type)
        return <Tag color="blue">{label}</Tag>
      },
    },
    {
      title: '工艺',
      dataIndex: 'description',
      key: 'description',
      width: 200,
      align: 'center' as const,
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      align: 'center' as const,
      render: (_: any, record: ProcessRule) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这条规则吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            cancelText="取消"
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ 
      height: '100vh',
      width: '100%',
      maxWidth: '100vw',
      display: 'flex',
      flexDirection: 'column',
      background: '#ffffff',
      overflow: 'hidden',
    }}>
      {/* 顶部导航栏 */}
      <div style={{
        padding: '12px 24px',
        background: '#ffffff',
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
      }}>
        <Flex align="center" justify="space-between">
          {/* 左侧：菜单按钮（小屏幕）+ 标题 */}
          <Flex align="center" gap={12}>
            {isSmallScreen && (
              <Button
                type="text"
                icon={<MenuOutlined />}
                onClick={() => setMobileDrawerVisible(true)}
                style={{
                  color: token.colorTextSecondary,
                  padding: '4px 8px',
                  height: 32,
                  width: 32,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              />
            )}
            <ToolOutlined style={{ fontSize: 20, color: token.colorPrimary }} />
            <Text style={{ fontSize: 18, fontWeight: 600 }}>工艺管理</Text>
          </Flex>

          {/* 右侧：关闭按钮 */}
          <Button
            type="text"
            icon={<CloseOutlined />}
            onClick={() => setCurrentView('chat')}
            style={{
              color: token.colorTextSecondary,
              padding: '4px 8px',
              height: 32,
              width: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          />
        </Flex>
      </div>

      {/* 筛选区域 */}
      <div style={{
        padding: '18px 24px',
        background: '#ffffff',
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        overflow: 'hidden',
      }}>
        <div style={{ 
          display: 'grid',
          gridTemplateColumns: `repeat(${gridCols}, 1fr)`,
          gap: '20px 20px',
          width: '100%',
          alignItems: 'start',
          gridAutoFlow: 'dense'
        }}>
          {/* 规则名称 - 始终显示 */}
          <div style={{ gridColumn: 'span 1' }}>
            <Form.Item 
              label="规则名称"
              colon={true}
              style={{ marginBottom: 0 }}
            >
              <Input
                placeholder="请输入"
                allowClear
                value={filters.name}
                onChange={(e) => {
                  setFilters({ ...filters, name: e.target.value || undefined })
                }}
              />
            </Form.Item>
          </div>

          {/* 特征类型 - 根据折叠状态和列数显示 */}
          {(!collapsed || gridCols >= 3) && (
            <div style={{ gridColumn: 'span 1' }}>
              <Form.Item 
                label="特征类型"
                colon={true}
                style={{ marginBottom: 0 }}
              >
                <Select
                  placeholder="请选择"
                  style={{ width: '100%' }}
                  allowClear
                  optionLabelProp="label"
                  value={filters.feature_type}
                  onChange={(value) => {
                    setFilters({ ...filters, feature_type: value })
                    setCurrentPage(1) // 重置到第一页
                    // useEffect 会自动触发 loadRules
                  }}
                  options={[
                    { label: '线割', value: 'wire' },
                  ]}
                />
              </Form.Item>
            </div>
          )}

          {/* 操作按钮区域 - 始终在最右侧 */}
          <div style={{ 
            gridColumn: '-2 / -1',
            display: 'flex', 
            justifyContent: 'flex-end',
            alignItems: 'flex-start'
          }}>
            <Space>
              <Button 
                type="primary" 
                icon={<SearchOutlined />}
                onClick={() => {
                  setCurrentPage(1)
                  loadRules()
                }}
              >
                搜索
              </Button>
              <Button 
                icon={<ReloadOutlined />}
                onClick={async () => {
                  // 先清除筛选条件和分页
                  setFilters({})
                  setCurrentPage(1)
                  // 重置防抖标记
                  isLoadingCache = false
                  lastLoadTime = 0
                  setLoading(true)
                  
                  try {
                    const response = await getProcessRules({
                      page: 1,
                      page_size: pageSize,
                    })
                    
                    if (response.success && response.data) {
                      setRules(response.data.data)
                      setTotal(response.data.total)
                    }
                  } catch (error: any) {
                    message.error(error.message || '加载规则列表失败')
                  } finally {
                    setLoading(false)
                    isLoadingCache = false
                  }
                }}
              >
                重置
              </Button>
              {/* 当特征类型被隐藏时显示展开/合并按钮 */}
              {collapsed && gridCols < 3 && (
                <Button 
                  type="link"
                  icon={<DownOutlined />}
                  onClick={() => setCollapsed(!collapsed)}
                  style={{ color: token.colorPrimary }}
                >
                  展开
                </Button>
              )}
              {!collapsed && gridCols < 3 && (
                <Button 
                  type="link"
                  icon={<UpOutlined />}
                  onClick={() => setCollapsed(!collapsed)}
                  style={{ color: token.colorPrimary }}
                >
                  合并
                </Button>
              )}
            </Space>
          </div>
        </div>
      </div>

      {/* 内容区域 */}
      <div style={{ 
        flex: 1,
        padding: 24,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}>
        {/* 表格上方操作按钮 */}
        <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={loadRules}
              loading={loading}
            >
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreate}
              style={{
                borderRadius: 8,
              }}
            >
              新增规则
            </Button>
          </Space>
          
          {selectedRowKeys.length > 0 && (
            <Button
              danger
              icon={<DeleteOutlined />}
              onClick={handleBatchDelete}
            >
              批量删除 ({selectedRowKeys.length})
            </Button>
          )}
        </Flex>

        {/* 表格容器 */}
        <div style={{ 
          flex: 1, 
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden'
        }}>
          {/* 表格主体 - 可滚动区域 */}
          <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', position: 'relative' }}>
            <Table
              columns={columns}
              dataSource={rules}
              rowKey="id"
              loading={loading}
              scroll={{ x: 'max-content' }}
              sticky
              bordered
              rowSelection={{
                selectedRowKeys,
                onChange: setSelectedRowKeys,
              }}
              components={{
                header: {
                  cell: (props: any) => (
                    <th {...props} style={{ ...props.style, fontSize: 15 }} />
                  ),
                },
              }}
              pagination={false}
              style={{ marginBottom: 0 }}
            />
          </div>
          
          {/* 分页器 - 固定在底部 */}
          <div style={{ 
            padding: '16px 0',
            borderTop: `1px solid ${token.colorBorderSecondary}`,
            background: '#fff',
            flexShrink: 0
          }}>
            <Flex justify="flex-end">
              <Pagination
                current={currentPage}
                pageSize={pageSize}
                total={total}
                showSizeChanger
                showQuickJumper
                showTotal={(total) => `共 ${total} 条`}
                onChange={(page, size) => {
                  setCurrentPage(page)
                  setPageSize(size)
                }}
                pageSizeOptions={[10, 20, 50, 100]}
              />
            </Flex>
          </div>
        </div>
      </div>

      {/* 新增/编辑弹窗 */}
      <Modal
        title={modalMode === 'create' ? '新增规则' : '编辑规则'}
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false)
        }}
        onOk={handleSubmit}
        confirmLoading={submitting}
        width={600}
        okText="确定"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 24 }}
        >
          <Form.Item
            label="规则ID"
            name="id"
            rules={[
              { required: true, message: '请输入规则ID' },
              { pattern: /^[A-Za-z0-9_-]+$/, message: '只能包含字母、数字、下划线和横线' },
            ]}
            extra={modalMode === 'edit' ? '规则ID不可修改' : undefined}
          >
            <Input placeholder="例如: R001" disabled={modalMode === 'edit'} />
          </Form.Item>

          <Form.Item
            label="规则名称"
            name="name"
            rules={[{ required: true, message: '请输入规则名称' }]}
          >
            <Input placeholder="请输入规则名称" />
          </Form.Item>

          <Form.Item
            label="特征类型"
            name="feature_type"
            rules={[{ required: true, message: '请选择特征类型' }]}
          >
            <Select
              placeholder="请选择特征类型"
              optionLabelProp="label"
              options={[
                { label: '线割', value: 'wire' },
              ]}
            />
          </Form.Item>

          <Form.Item
            label="工艺"
            name="description"
            rules={[{ required: true, message: '请输入工艺' }]}
          >
            <Input placeholder="请输入工艺" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ProcessManagement

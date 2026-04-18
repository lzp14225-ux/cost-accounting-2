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
  DollarOutlined,
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
  PriceItem,
  CreatePriceItemParams,
  UpdatePriceItemParams,
  QueryPriceItemsParams,
  PriceCategory,
  PriceCategoryLabels,
  getPriceItems,
  createPriceItem,
  updatePriceItem,
  deletePriceItem,
  batchDeletePriceItems,
} from '../api/priceItems'

const { Text } = Typography
const { TextArea } = Input

// 组件外部的缓存标记，防止重复请求
let isLoadingCache = false
let lastLoadTime = 0
const LOAD_DEBOUNCE_TIME = 300 // 300ms 内的重复请求会被忽略

const PriceManagement: React.FC = () => {
  const { token } = theme.useToken()
  const { setMobileDrawerVisible, setCurrentView } = useAppStore()
  
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<PriceItem[]>([])
  const [total, setTotal] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [isSmallScreen, setIsSmallScreen] = useState(window.innerWidth < 960)
  const [collapsed, setCollapsed] = useState(true) // 搜索表单折叠状态
  const [gridCols, setGridCols] = useState(3) // Grid 列数
  
  // 筛选条件
  const [filters, setFilters] = useState<QueryPriceItemsParams>({})
  
  // 弹窗状态
  const [modalVisible, setModalVisible] = useState(false)
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create')
  const [editingItem, setEditingItem] = useState<PriceItem | null>(null)
  const [submitting, setSubmitting] = useState(false) // 提交状态
  
  const [form] = Form.useForm()
  
  // 用于跟踪是否是首次加载
  const isFirstLoad = useRef(true)

  // 计算 Grid 列数的函数
  const calculateGridCols = (width: number): number => {
    if (width < 767) return 1      // 小于767px: 1列
    if (width < 1200) return 2     // 小于1200px: 2列
    return 3                        // 其他: 3列
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

  // 加载价格项列表
  const loadItems = async () => {
    // 防抖：如果距离上次加载时间小于阈值，则忽略
    const now = Date.now()
    if (isLoadingCache || (now - lastLoadTime < LOAD_DEBOUNCE_TIME)) {
      return
    }
    
    isLoadingCache = true
    lastLoadTime = now
    setLoading(true)
    
    try {
      const response = await getPriceItems({
        page: currentPage,
        page_size: pageSize,
        ...filters,
      })
      
      if (response.success && response.data) {
        setItems(response.data.data)
        setTotal(response.data.total)
      }
    } catch (error: any) {
      message.error(error.message || '加载价格项列表失败')
    } finally {
      setLoading(false)
      isLoadingCache = false
    }
  }

  // 初始加载
  useEffect(() => {
    if (isFirstLoad.current) {
      isFirstLoad.current = false
      loadItems()
    }
  }, [])
  
  // 监听分页和筛选条件变化
  useEffect(() => {
    if (!isFirstLoad.current) {
      loadItems()
    }
  }, [currentPage, pageSize, filters.category]) // 添加 filters.category 监听

  // 打开新增弹窗
  const handleCreate = () => {
    setModalMode('create')
    setEditingItem(null)
    form.resetFields() // 清除表单数据
    form.setFieldsValue({
      is_active: true,
    })
    setModalVisible(true)
  }

  // 打开编辑弹窗
  const handleEdit = (record: PriceItem) => {
    setModalMode('edit')
    setEditingItem(record)
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
        await createPriceItem(values as CreatePriceItemParams)
        message.success('价格项创建成功')
      } else {
        await updatePriceItem(editingItem!.id, values as UpdatePriceItemParams)
        message.success('价格项更新成功')
      }
      
      setModalVisible(false)
      form.resetFields()
      loadItems()
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

  // 删除单个价格项
  const handleDelete = async (itemId: string) => {
    try {
      await deletePriceItem(itemId)
      message.success('价格项删除成功')
      loadItems()
    } catch (error: any) {
      message.error(error.message || '删除失败')
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请选择要删除的价格项')
      return
    }
    
    Modal.confirm({
      title: '批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 条价格项吗？`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await batchDeletePriceItems(selectedRowKeys as string[])
          message.success(`成功删除 ${selectedRowKeys.length} 条价格项`)
          setSelectedRowKeys([])
          loadItems()
        } catch (error: any) {
          message.error(error.message || '批量删除失败')
        }
      },
    })
  }

  // 表格列定义
  const columns = [
    {
      title: '价格项ID',
      dataIndex: 'id',
      key: 'id',
      width: 120,
      fixed: 'left' as const,
      align: 'center' as const,
      render: (text: string) => text || '-',
    },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      width: 120,
      align: 'center' as const,
      render: (category: PriceCategory) => {
        if (!category) return '-'
        const label = PriceCategoryLabels[category] || category
        const colorMap: Record<string, string> = {
          wire: 'blue',
          special: 'orange',
          base: 'green',
          material: 'cyan',
          heat: 'red',
          NC: 'purple',
          rule: 'magenta',
          S_water_mill: 'volcano',
          L_water_mill: 'gold',
          tooth_hole: 'lime',
          screw: 'geekblue',
          stop_screw: 'cyan',
          density: 'blue',
        }
        return <Tag color={colorMap[category] || 'default'}>{label}</Tag>
      },
    },
    {
      title: '单价',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      align: 'center' as const,
      render: (text: string) => text || '-',
    },
    {
      title: '单位',
      dataIndex: 'unit',
      key: 'unit',
      width: 100,
      align: 'center' as const,
      render: (text: string) => text || '-',
    },
    {
      title: '最低计费',
      dataIndex: 'min_num',
      key: 'min_num',
      width: 100,
      align: 'center' as const,
      render: (text: string) => text || '-',
    },
    {
      title: '备注',
      dataIndex: 'note',
      key: 'note',
      width: 150,
      align: 'center' as const,
      ellipsis: true,
      render: (text: string) => text || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      align: 'center' as const,
      render: (_: any, record: PriceItem) => (
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
            title="确定要删除这条价格项吗？"
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
            <DollarOutlined style={{ fontSize: 20, color: token.colorPrimary }} />
            <Text style={{ fontSize: 18, fontWeight: 600 }}>价格管理</Text>
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
          {/* 类别 - 始终显示 */}
          <div style={{ gridColumn: 'span 1' }}>
            <Form.Item 
              label="类别"
              colon={true}
              style={{ marginBottom: 0 }}
            >
              <Select
                placeholder="请选择"
                style={{ width: '100%' }}
                allowClear
                value={filters.category}
                onChange={(value) => {
                  setFilters({ ...filters, category: value })
                  setCurrentPage(1) // 重置到第一页
                  // useEffect 会自动触发 loadItems
                }}
                options={Object.entries(PriceCategoryLabels).map(([key, label]) => ({
                  label,
                  value: key,
                }))}
              />
            </Form.Item>
          </div>

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
                  loadItems()
                }}
              >
                搜索
              </Button>
              <Button 
                icon={<ReloadOutlined />}
                onClick={async () => {
                  setFilters({})
                  setCurrentPage(1)
                  // 重置防抖标记
                  isLoadingCache = false
                  lastLoadTime = 0
                  setLoading(true)
                  
                  try {
                    const response = await getPriceItems({
                      page: 1,
                      page_size: pageSize,
                    })
                    
                    if (response.success && response.data) {
                      setItems(response.data.data)
                      setTotal(response.data.total)
                    }
                  } catch (error: any) {
                    message.error(error.message || '加载价格项列表失败')
                  } finally {
                    setLoading(false)
                    isLoadingCache = false
                  }
                }}
              >
                重置
              </Button>
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
              onClick={loadItems}
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
              新增价格项
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
              dataSource={items}
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
        title={modalMode === 'create' ? '新增价格项' : '编辑价格项'}
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false)
          // 不在关闭时清除表单，只在打开时清除
        }}
        onOk={handleSubmit}
        confirmLoading={submitting}
        width={700}
        okText="确定"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 24 }}
        >
          <Form.Item
            label="价格项ID"
            name="id"
            rules={[
              { required: true, message: '请输入价格项ID' },
              { pattern: /^[A-Za-z0-9_-]+$/, message: '只能包含字母、数字、下划线和横线' },
            ]}
            extra={modalMode === 'edit' ? '价格项ID不可修改' : undefined}
          >
            <Input placeholder="例如: P001" disabled={modalMode === 'edit'} />
          </Form.Item>

          <Form.Item
            label="类别"
            name="category"
            rules={[{ required: true, message: '请选择类别' }]}
          >
            <Select
              placeholder="请选择类别"
              options={Object.entries(PriceCategoryLabels).map(([key, label]) => ({
                label,
                value: key,
              }))}
            />
          </Form.Item>

          {/* 子类字段只在新增时显示 */}
          {modalMode === 'create' && (
            <Form.Item
              label="子类"
              name="sub_category"
              rules={[{ required: true, message: '请输入子类' }]}
            >
              <Input placeholder="请输入子类" />
            </Form.Item>
          )}

          <Form.Item
            label="单价"
            name="price"
            rules={[
              { required: true, message: '请输入单价' }
            ]}
          >
            <Input placeholder="例如: 100.00" />
          </Form.Item>

          <Form.Item
            label="单位"
            name="unit"
            rules={[{ required: true, message: '请输入单位' }]}
          >
            <Input placeholder="例如: 元/小时" />
          </Form.Item>

          <Form.Item
            label="最低计费标准"
            name="min_num"
          >
            <Input placeholder="例如: 50" />
          </Form.Item>

          <Form.Item
            label="备注"
            name="note"
          >
            <TextArea
              rows={2}
              placeholder="请输入备注（可选）"
              maxLength={500}
              showCount
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default PriceManagement

import React, { useState } from 'react'
import { Card, Button, Space, Typography, Table, message, Tag, theme } from 'antd'
import { CheckOutlined, ExclamationCircleOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { ParsedChange } from '../services/reviewService'
import { useCountdown } from '../hooks/useCountdown'

const { Title } = Typography

interface DisplayViewItem {
  part_code: string
  part_name: string
  subgraph_file_url?: string
  material?: string | null
  length_mm?: number | string | null
  width_mm?: number | string | null
  thickness_mm?: number | string | null
  quantity?: number | null
  heat_treatment?: string | null
  weight?: number | string | null
  scrap_weight?: number | string | null
  drilling_time?: number | string | null
  nc_roughing_time?: number | string | null
  wire_length?: number | string | null
  process_code?: string | null
  process_name?: string | null
  process_description?: string | null
  process_note?: string | null
  edm_time?: number | string | null
  nc_milling_time?: number | string | null
  grinding_time?: number | string | null
  engraving_time?: number | string | null
  other_time?: number | string | null
  process_unit_price?: string | null
  material_unit_price?: string | null
  _source?: {
    subgraph_id?: string
    feature_id?: number
    process_snapshot_id?: number
    wire_price_snapshot_id?: number
    material_price_snapshot_id?: number | null
  }
  [key: string]: any // 允许其他字段
}

interface ModificationCardProps {
  modificationId: string
  changes: ParsedChange[]
  displayView?: DisplayViewItem[] // 新增：显示视图数据
  messageTimestamp?: number // 新增：消息时间戳，用于倒计时
  onConfirm: (comment?: string) => Promise<void>
  loading?: boolean
}

const ModificationCard: React.FC<ModificationCardProps> = ({
  modificationId,
  changes,
  displayView,
  messageTimestamp,
  onConfirm,
  loading = false,
}) => {
  const [confirming, setConfirming] = useState(false)
  const { token } = theme.useToken()

  // 倒计时逻辑
  const shouldShowCountdown = messageTimestamp !== undefined
  const elapsedTime = shouldShowCountdown ? Math.floor((Date.now() - messageTimestamp) / 1000) : 0
  const remainingTime = shouldShowCountdown ? Math.max(0, 300 - elapsedTime) : 300 // 5分钟 = 300秒
  
  const { timeLeft, isExpired, formatTime, pause, resume } = useCountdown({
    initialTime: remainingTime,
    onExpired: () => {
      console.log(`ModificationCard确认按钮已过期: ${modificationId}`)
    }
  })

  const handleConfirm = async () => {
    setConfirming(true)
    console.log('🔘 点击确认按钮，暂停倒计时')
    pause() // 暂停倒计时
    
    try {
      await onConfirm()
      message.success('修改已确认')
      console.log('✅ 确认成功，不恢复倒计时')
      // 确认成功，不需要恢复倒计时
    } catch (error: any) {
      console.error('❌ 确认修改失败:', error)
      // 如果不是 Network Error，则显示错误消息
      if (error.message !== 'Network Error') {
        message.error(error.message || '确认修改失败')
      }
      console.log('🔄 请求失败，恢复倒计时')
      resume() // 请求失败，恢复倒计时
    } finally {
      setConfirming(false)
    }
  }

  // 检查某个字段是否被修改
  const isFieldModified = (featureId: number, fieldName: string): boolean => {
    return changes.some(
      change => 
        change.table === 'features' && 
        change.id === featureId.toString() && 
        change.field === fieldName
    )
  }

  // 获取修改后的值
  const getModifiedValue = (featureId: number, fieldName: string): any => {
    const change = changes.find(
      change => 
        change.table === 'features' && 
        change.id === featureId.toString() && 
        change.field === fieldName
    )
    return change?.new_value
  }

  // 渲染单元格，如果被修改则高亮显示
  const renderCell = (value: any, record: DisplayViewItem, fieldName: string) => {
    const featureId = record._source?.feature_id
    if (!featureId) {
      // 对于价格字段，如果没有值则显示 '-'，有值则显示 '¥值'
      if (fieldName === 'process_unit_price' || fieldName === 'material_unit_price') {
        return value ? `¥${value}` : '-'
      }
      return value ?? '-'
    }

    const isModified = isFieldModified(featureId, fieldName)
    const modifiedValue = isModified ? getModifiedValue(featureId, fieldName) : value

    if (isModified) {
      // 对于价格字段，如果没有值则显示 '-'，有值则显示 '¥值'
      let displayValue = modifiedValue ?? '-'
      if ((fieldName === 'process_unit_price' || fieldName === 'material_unit_price') && modifiedValue) {
        displayValue = `¥${modifiedValue}`
      }
      
      return (
        <Tag color="success" style={{ margin: 0 }}>
          {displayValue}
        </Tag>
      )
    }

    // 对于价格字段，如果没有值则显示 '-'，有值则显示 '¥值'
    if (fieldName === 'process_unit_price' || fieldName === 'material_unit_price') {
      return value ? `¥${value}` : '-'
    }

    return value ?? '-'
  }

  // Display View 表格列
  const displayViewColumns = [
    {
      title: '序号',
      key: 'index',
      width: 70,
      align: 'center' as const,
      render: (_text: any, _record: DisplayViewItem, index: number) => index + 1
    },
    {
      title: '名称',
      dataIndex: 'part_name',
      key: 'part_name',
      width: 120,
      align: 'center' as const,
    },
    {
      title: '编号',
      dataIndex: 'part_code',
      key: 'part_code',
      width: 120,
      align: 'center' as const,
    },
    {
      title: '材质',
      dataIndex: 'material',
      key: 'material',
      width: 100,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'material'),
    },
    {
      title: '规格',
      key: 'specification',
      width: 150,
      align: 'center' as const,
      render: (_text: any, record: DisplayViewItem) => {
        const featureId = record._source?.feature_id
        
        // 检查三个字段是否有任何一个被修改
        const isLengthModified = featureId ? isFieldModified(featureId, 'length_mm') : false
        const isWidthModified = featureId ? isFieldModified(featureId, 'width_mm') : false
        const isThicknessModified = featureId ? isFieldModified(featureId, 'thickness_mm') : false
        const isAnyModified = isLengthModified || isWidthModified || isThicknessModified
        
        // 获取值（如果被修改则使用新值）
        const length = isLengthModified ? getModifiedValue(featureId!, 'length_mm') : record.length_mm
        const width = isWidthModified ? getModifiedValue(featureId!, 'width_mm') : record.width_mm
        const thickness = isThicknessModified ? getModifiedValue(featureId!, 'thickness_mm') : record.thickness_mm
        
        const lengthStr = (length !== null && length !== undefined) ? length : '-'
        const widthStr = (width !== null && width !== undefined) ? width : '-'
        const thicknessStr = (thickness !== null && thickness !== undefined) ? thickness : '-'
        const specValue = `${lengthStr}×${widthStr}×${thicknessStr}`
        
        if (isAnyModified) {
          return (
            <Tag color="success" style={{ margin: 0 }}>
              {specValue}
            </Tag>
          )
        }
        
        return specValue
      },
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 80,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'quantity'),
    },
    {
      title: '热处理',
      dataIndex: 'heat_treatment',
      key: 'heat_treatment',
      width: 100,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'heat_treatment'),
    },
    {
      title: '工艺',
      dataIndex: 'process_description',
      key: 'process_description',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'process_description'),
    },
    {
      title: '单重',
      dataIndex: 'weight',
      key: 'weight',
      width: 100,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'weight'),
    },
    {
      title: '废料单重',
      dataIndex: 'scrap_weight',
      key: 'scrap_weight',
      width: 100,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'scrap_weight'),
    },
    {
      title: '钻孔工时/单件',
      dataIndex: 'drilling_time',
      key: 'drilling_time',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'drilling_time'),
    },
    {
      title: '开粗工时/单件',
      dataIndex: 'nc_roughing_time',
      key: 'nc_roughing_time',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'nc_roughing_time'),
    },
    {
      title: '线割长度/单件',
      dataIndex: 'wire_length',
      key: 'wire_length',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'wire_length'),
    },
    {
      title: '线割工艺/单件',
      dataIndex: 'process_note',
      key: 'process_note',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'process_note'),
    },
    {
      title: '线割工时/单件',
      key: 'wire_time',
      width: 120,
      align: 'center' as const,
      render: (_value: any, record: DisplayViewItem) => {
        if (!record.wire_length || !record.process_note) {
          return '-'
        }
        let divisor = 0
        if (record.process_note.includes('慢丝')) {
          divisor = 80
        } else if (record.process_note.includes('中丝')) {
          divisor = 40
        } else if (record.process_note.includes('快丝')) {
          divisor = 20
        }
        if (divisor === 0) {
          return '-'
        }
        const wireLength = typeof record.wire_length === 'string' ? parseFloat(record.wire_length) : record.wire_length
        const result = (wireLength / divisor).toFixed(2)
        return result
      }
    },
    {
      title: '放电工时/单件',
      dataIndex: 'edm_time',
      key: 'edm_time',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'edm_time'),
    },
    {
      title: '精铣工时/单件',
      dataIndex: 'nc_milling_time',
      key: 'nc_milling_time',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'nc_milling_time'),
    },
    {
      title: '研磨工时/单件',
      dataIndex: 'grinding_time',
      key: 'grinding_time',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'grinding_time'),
    },
    {
      title: '雕刻工时/单件',
      dataIndex: 'engraving_time',
      key: 'engraving_time',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'engraving_time'),
    },
    {
      title: '其它工时/单件',
      dataIndex: 'other_time',
      key: 'other_time',
      width: 120,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'other_time'),
    },
    {
      title: '工艺单价',
      dataIndex: 'process_unit_price',
      key: 'process_unit_price',
      width: 100,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'process_unit_price'),
    },
    {
      title: '材质单价',
      dataIndex: 'material_unit_price',
      key: 'material_unit_price',
      width: 100,
      align: 'center' as const,
      render: (value: any, record: DisplayViewItem) => renderCell(value, record, 'material_unit_price'),
    },
  ]


  return (
    <Card
      title={
        <Space>
          <ExclamationCircleOutlined style={{ color: '#faad14' }} />
          <span>确认修改</span>
        </Space>
      }
      size="small"
      style={{
        border: '1px solid #faad14',
        borderRadius: 8,
      }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        {/* Display View 表格 */}
        {displayView && displayView.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <Title level={5} style={{ margin: 0, marginBottom: 8 }}>
              数据预览（修改后）
            </Title>
            
            <Table
              dataSource={displayView}
              columns={displayViewColumns}
              rowKey={(record) => record._source?.feature_id?.toString() || record.part_code}
              pagination={false}
              size="small"
              bordered
              scroll={{ 
                x: 1220,
                y: 400,
              }}
            />
          </div>
        )}

        {/* 操作按钮 */}
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          {shouldShowCountdown && isExpired ? (
            <div style={{ 
              padding: '8px 12px',
              background: token.colorFillQuaternary,
              borderRadius: 6,
              textAlign: 'center'
            }}>
              <Space>
                <ClockCircleOutlined style={{ color: token.colorTextTertiary }} />
                <span style={{ color: token.colorTextTertiary, fontSize: 14 }}>
                  确认时间已过期
                </span>
              </Space>
            </div>
          ) : (
            <Button
              type="primary"
              icon={<CheckOutlined />}
              onClick={handleConfirm}
              loading={confirming || loading}
              disabled={loading}
              size="large"
            >
              <Space size={8}>
                <span>确认修改</span>
                {shouldShowCountdown && (
                  <span style={{ 
                    fontSize: 12, 
                    opacity: 0.8,
                    fontWeight: 400
                  }}>
                    ({formatTime(timeLeft)})
                  </span>
                )}
              </Space>
            </Button>
          )}
        </div>
      </Space>
    </Card>
  )
}

export default ModificationCard
import React, { useState } from 'react'
import { Table, Button, Typography, Pagination, Tooltip } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import MinimalDxfViewer from './MinimalDxfViewer'

const { Text } = Typography

interface AbnormalAnomaly {
  type: string
  description: string
  [key: string]: any
}

interface AbnormalSituation {
  dimension_anomalies?: AbnormalAnomaly[]
  wire_cut_anomalies?: AbnormalAnomaly[]
}

interface ReviewDataItem {
  part_code: string
  part_name: string
  subgraph_file_url: string
  material: string | null
  length_mm: number
  width_mm: number
  thickness_mm: number
  quantity: number
  process_code: string
  process_name: string
  process_description: string
  process_note: string | null
  wire_length: number | null
  edm_time: number | string | null
  nc_milling_time: number | string | null
  grinding_time: number | string | null
  engraving_time: number | string | null
  other_time: number | string | null
  process_unit_price: string
  material_unit_price: string | null
  abnormal_situation?: AbnormalSituation | null
  _source?: any
}

interface TableDataItem extends Omit<ReviewDataItem, '_source'> {
  key: number
}

interface ReviewDataListProps {
  data: ReviewDataItem[]
  jobId: string
}

const ReviewDataList: React.FC<ReviewDataListProps> = ({ data }) => {
  const [dxfModalVisible, setDxfModalVisible] = useState(false)
  const [currentDxfUrl, setCurrentDxfUrl] = useState<string>('')
  const [currentPartName, setCurrentPartName] = useState<string>('')
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const handleViewDxf = (url: string, partName: string) => {
    setCurrentDxfUrl(url)
    setCurrentPartName(partName)
    setDxfModalVisible(true)
  }

  const handlePageChange = (page: number, newPageSize?: number) => {
    setCurrentPage(page)
    if (newPageSize && newPageSize !== pageSize) {
      setPageSize(newPageSize)
      setCurrentPage(1) // 改变每页数量时重置到第一页
    }
  }

  const columns: ColumnsType<TableDataItem> = [
    {
      title: '序号',
      key: 'index',
      width: 70,
      align: 'center',
      render: (_text, _record, index) => (currentPage - 1) * pageSize + index + 1
    },
    {
      title: '名称',
      dataIndex: 'part_name',
      key: 'part_name',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '编号',
      dataIndex: 'part_code',
      key: 'part_code',
      width: 120,
      align: 'center',
      render: (text) => text ? <Text strong>{text}</Text> : '-'
    },
    {
      title: '材质',
      dataIndex: 'material',
      key: 'material',
      width: 100,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '规格',
      key: 'specification',
      width: 150,
      align: 'center',
      render: (_text, record) => {
        const length = (record.length_mm !== null && record.length_mm !== undefined) ? record.length_mm : '-'
        const width = (record.width_mm !== null && record.width_mm !== undefined) ? record.width_mm : '-'
        const thickness = (record.thickness_mm !== null && record.thickness_mm !== undefined) ? record.thickness_mm : '-'
        return `${length}×${width}×${thickness}`
      }
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 80,
      align: 'center',
      render: (text) => (text !== null && text !== undefined) ? text : '-'
    },
    {
      title: '热处理',
      dataIndex: 'heat_treatment',
      key: 'heat_treatment',
      width: 100,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '工艺',
      dataIndex: 'process_description',
      key: 'process_description',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '单重',
      dataIndex: 'weight',
      key: 'weight',
      width: 100,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '废料单重',
      dataIndex: 'scrap_weight',
      key: 'scrap_weight',
      width: 100,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '钻孔工时/单件',
      dataIndex: 'drilling_time',
      key: 'drilling_time',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '开粗工时/单件',
      dataIndex: 'nc_roughing_time',
      key: 'nc_roughing_time',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '线割长度/单件',
      dataIndex: 'wire_length',
      key: 'wire_length',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '线割工艺/单件',
      dataIndex: 'process_note',
      key: 'process_note',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '线割工时/单件',
      key: 'wire_time',
      width: 120,
      align: 'center',
      render: (_text, record) => {
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
        const result = (record.wire_length / divisor).toFixed(2)
        return result
      }
    },
    {
      title: '放电工时/单件',
      dataIndex: 'edm_time',
      key: 'edm_time',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '精铣工时/单件',
      dataIndex: 'nc_milling_time',
      key: 'nc_milling_time',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '研磨工时/单件',
      dataIndex: 'grinding_time',
      key: 'grinding_time',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '雕刻工时/单件',
      dataIndex: 'engraving_time',
      key: 'engraving_time',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '其它工时/单件',
      dataIndex: 'other_time',
      key: 'other_time',
      width: 120,
      align: 'center',
      render: (text) => text || '-'
    },
    {
      title: '工艺单价',
      dataIndex: 'process_unit_price',
      key: 'process_unit_price',
      width: 100,
      align: 'center',
      render: (text) => text ? <Text>¥{text}</Text> : '-'
    },
    {
      title: '材质单价',
      dataIndex: 'material_unit_price',
      key: 'material_unit_price',
      width: 100,
      align: 'center',
      render: (text) => text ? <Text>¥{text}</Text> : '-'
    },
    {
      title: '异常原因',
      dataIndex: 'abnormal_situation',
      key: 'abnormal_situation',
      width: 200,
      align: 'center',
      render: (abnormalSituation: AbnormalSituation | null | undefined) => {
        if (!abnormalSituation) {
          return '-'
        }

        const descriptions: string[] = []

        // 收集 dimension_anomalies 中的所有 description
        if (abnormalSituation.dimension_anomalies && abnormalSituation.dimension_anomalies.length > 0) {
          abnormalSituation.dimension_anomalies.forEach(anomaly => {
            if (anomaly.description) {
              descriptions.push(anomaly.description)
            }
          })
        }

        // 收集 wire_cut_anomalies 中的所有 description
        if (abnormalSituation.wire_cut_anomalies && abnormalSituation.wire_cut_anomalies.length > 0) {
          abnormalSituation.wire_cut_anomalies.forEach(anomaly => {
            if (anomaly.description) {
              descriptions.push(anomaly.description)
            }
          })
        }

        // 如果没有任何描述，返回 '-'
        if (descriptions.length === 0) {
          return '-'
        }

        // 生成完整的异常信息内容（用于 Tooltip）
        const fullContent = (
          <div style={{ maxWidth: 400 }}>
            {descriptions.map((desc, index) => (
              <div key={index} style={{ marginBottom: index < descriptions.length - 1 ? 8 : 0 }}>
                {index + 1}. {desc}
              </div>
            ))}
          </div>
        )

        // 生成单行显示的内容（用分号分隔）
        const singleLineText = descriptions.map((desc, index) => `${index + 1}. ${desc}`).join('; ')

        return (
          <Tooltip 
            title={fullContent} 
            placement="topLeft" 
            styles={{ root: { maxWidth: 500 } }}
          >
            <div style={{ 
              textAlign: 'left',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              cursor: 'pointer'
            }}>
              {singleLineText}
            </div>
          </Tooltip>
        )
      }
    },
    {
      title: '操作',
      dataIndex: 'subgraph_file_url',
      key: 'operation',
      width: 120,
      fixed: 'right',
      align: 'center',
      render: (url, record) => url ? (
        <Button
          type="link"
          icon={<EyeOutlined />}
          onClick={() => handleViewDxf(url, record.part_name)}
        >
          查看图纸
        </Button>
      ) : '-'
    },
  ]

  // 过滤掉 _source 字段
  const tableData: TableDataItem[] = data.map((item, index) => {
    const { _source, ...rest } = item
    return {
      ...rest,
      key: index,
    }
  })

  // 计算当前页的数据
  const startIndex = (currentPage - 1) * pageSize
  const endIndex = startIndex + pageSize
  const currentPageData = tableData.slice(startIndex, endIndex)

  return (
    <>
      <div style={{ marginBottom: tableData.length > pageSize ? 0 : 20 }}>
        <Table
          columns={columns}
          dataSource={currentPageData}
          pagination={false}
          scroll={{ 
            x: 1220,
          }}
          size="small"
          bordered
          sticky
        />
      </div>

      {/* 分页器 - 只在数据超过一页时显示 */}
      {tableData.length > pageSize && (
        <div style={{ 
          marginTop: 16, 
          marginBottom: 24,
          display: 'flex', 
          justifyContent: 'flex-end' 
        }}>
          <Pagination
            current={currentPage}
            total={tableData.length}
            pageSize={pageSize}
            showQuickJumper
            showSizeChanger
            pageSizeOptions={['10', '20', '50', '100']}
            onChange={handlePageChange}
            onShowSizeChange={handlePageChange}
            showTotal={(total) => `共 ${total} 条`}
          />
        </div>
      )}

      {/* DXF 查看器弹窗 */}
      <MinimalDxfViewer
        visible={dxfModalVisible}
        onClose={() => setDxfModalVisible(false)}
        filePath={currentDxfUrl}
        partName={currentPartName}
      />
    </>
  )
}

export default ReviewDataList

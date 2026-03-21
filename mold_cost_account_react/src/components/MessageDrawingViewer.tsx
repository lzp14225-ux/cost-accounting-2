import React from 'react'
import { Space, Divider, Typography } from 'antd'
import { FileImageOutlined } from '@ant-design/icons'
import DrawingViewButton from './DrawingViewButton'
import { extractDrawingPaths, extractDrawingsFromReviewData } from '../utils/drawingUtils'

const { Text } = Typography

interface MessageDrawingViewerProps {
  content: string
  progressData?: any
}

const MessageDrawingViewer: React.FC<MessageDrawingViewerProps> = ({
  content,
  progressData
}) => {
  // 从消息内容中提取图纸路径
  const drawingsFromContent = extractDrawingPaths(content)
  
  // 从进度数据中提取图纸信息（如果是review_display_view类型）
  const drawingsFromProgressData = progressData?.type === 'review_display_view' && progressData?.data
    ? extractDrawingsFromReviewData(progressData.data)
    : []
  
  // 合并所有图纸信息，去重
  const allDrawings = [
    ...drawingsFromContent,
    ...drawingsFromProgressData.map(d => ({
      filePath: d.filePath,
      partName: d.partName
    }))
  ]
  
  // 去重：基于filePath
  const uniqueDrawings = allDrawings.filter((drawing, index, self) =>
    index === self.findIndex(d => d.filePath === drawing.filePath)
  )
  
  if (uniqueDrawings.length === 0) {
    return null
  }
  
  return (
    <div style={{ marginTop: 12 }}>
      <Divider style={{ margin: '8px 0' }} />
      
      <div style={{ 
        padding: '8px 12px',
        background: '#f8f9fa',
        borderRadius: 6,
        border: '1px solid #e9ecef'
      }}>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space size={4}>
            <FileImageOutlined style={{ color: '#1890ff' }} />
            <Text strong style={{ fontSize: 13, color: '#1890ff' }}>
              相关图纸 ({uniqueDrawings.length})
            </Text>
          </Space>
          
          <div style={{ 
            display: 'flex', 
            flexWrap: 'wrap', 
            gap: 8 
          }}>
            {uniqueDrawings.map((drawing, index) => (
              <DrawingViewButton
                key={`${drawing.filePath}-${index}`}
                filePath={drawing.filePath}
                partName={drawing.partName || `图纸${index + 1}`}
                size="small"
                type="default"
                style={{
                  fontSize: 12,
                  height: 28,
                  padding: '0 8px',
                  borderRadius: 4
                }}
              />
            ))}
          </div>
        </Space>
      </div>
    </div>
  )
}

export default MessageDrawingViewer
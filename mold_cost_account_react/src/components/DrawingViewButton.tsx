import React, { useState } from 'react'
import { Button, Space } from 'antd'
import { EyeOutlined, FileImageOutlined } from '@ant-design/icons'
import SimplestDxfViewer from './SimplestDxfViewer'

interface DrawingViewButtonProps {
  filePath: string
  partName?: string
  size?: 'small' | 'middle' | 'large'
  type?: 'default' | 'primary' | 'link' | 'text'
  style?: React.CSSProperties
}

const DrawingViewButton: React.FC<DrawingViewButtonProps> = ({
  filePath,
  partName = '图纸',
  size = 'small',
  type = 'link',
  style
}) => {
  const [dxfModalVisible, setDxfModalVisible] = useState(false)

  const handleViewDrawing = () => {
    setDxfModalVisible(true)
  }

  return (
    <>
      <Button
        type={type}
        size={size}
        icon={<EyeOutlined />}
        onClick={handleViewDrawing}
        style={style}
      >
        <Space size={4}>
          <FileImageOutlined />
          查看图纸
        </Space>
      </Button>

      <SimplestDxfViewer
        visible={dxfModalVisible}
        onClose={() => setDxfModalVisible(false)}
        filePath={filePath}
        partName={partName}
      />
    </>
  )
}

export default DrawingViewButton
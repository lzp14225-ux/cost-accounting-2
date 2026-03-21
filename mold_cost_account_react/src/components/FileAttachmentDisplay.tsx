import React from 'react'
import { Button, Card, Flex, Typography, theme } from 'antd'
import { FileOutlined, DownloadOutlined } from '@ant-design/icons'
import { FileAttachment } from '../store/useAppStore'

const { Text } = Typography

interface FileAttachmentDisplayProps {
  file: FileAttachment
}

const FileAttachmentDisplay: React.FC<FileAttachmentDisplayProps> = ({ file }) => {
  const { token } = theme.useToken()
  
  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const getFileTypeColor = (type: string) => {
    if (type.includes('dwg')) return token.colorInfo
    if (type.includes('prt')) return token.colorSuccess
    return token.colorTextSecondary
  }

  return (
    <Card
      size="small"
      style={{
        marginBottom: 8,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
        background: token.colorFillAlter,
      }}
      styles={{ body: { padding: 8, paddingRight: 12 } }}
    >
      <Flex align="center" gap={8}>
        <FileOutlined 
          style={{ 
            fontSize: 40, 
            color: getFileTypeColor(file.type),
          }} 
        />
        
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <Text 
            style={{ 
              fontSize: 14,
              display: 'block',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              marginBottom: 0,
              minWidth: 82,
              maxWidth: 132,
            }}
          >
            {file.name}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {formatFileSize(file.size)}
          </Text>
        </div>

        {file.url && (
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => window.open(file.url, '_blank')}
            style={{ 
              color: token.colorTextTertiary,
              borderRadius: token.borderRadiusSM,
            }}
          />
        )}
      </Flex>
    </Card>
  )
}

export default FileAttachmentDisplay
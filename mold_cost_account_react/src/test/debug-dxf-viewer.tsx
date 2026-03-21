import React, { useState } from 'react'
import { Button, Space, Typography, Card, Alert, Input } from 'antd'
import { fileService } from '../services/fileService'
import WorkingDxfViewer from '../components/WorkingDxfViewer'

const { Title, Text } = Typography

const DebugDxfViewer: React.FC = () => {
  const [testFilePath, setTestFilePath] = useState('dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-01.dxf')
  const [apiResult, setApiResult] = useState<any>(null)
  const [apiError, setApiError] = useState<string>('')
  const [showViewer, setShowViewer] = useState(false)

  const testAPI = async () => {
    // console.log('🧪 开始测试API调用...')
    setApiError('')
    setApiResult(null)
    
    try {
      // console.log('测试文件路径:', testFilePath)
      const result = await fileService.getPresignedUrl(testFilePath, 3600)
      
      // console.log('✅ API调用成功:', result)
      setApiResult(result)
      
    } catch (error: any) {
      console.error('❌ API调用失败:', error)
      setApiError(error.message || '未知错误')
    }
  }

  return (
    <div style={{ padding: '20px', maxWidth: 1000, margin: '0 auto' }}>
      <Title level={2}>DXF查看器调试工具</Title>
      
      <Space direction="vertical" size={24} style={{ width: '100%' }}>
        {/* API测试 */}
        <Card title="1. API测试" size="small">
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <Text>文件路径:</Text>
              <Input
                value={testFilePath}
                onChange={(e) => setTestFilePath(e.target.value)}
                placeholder="输入DXF文件路径"
                style={{ marginTop: 8 }}
              />
            </div>
            
            <Button type="primary" onClick={testAPI}>
              测试预签名URL API
            </Button>
            
            {apiError && (
              <Alert
                message="API调用失败"
                description={apiError}
                type="error"
                showIcon
              />
            )}
            
            {apiResult && (
              <Alert
                message="API调用成功"
                description={
                  <div>
                    <div><strong>URL:</strong> {apiResult.url?.substring(0, 100)}...</div>
                    <div><strong>过期时间:</strong> {apiResult.expires_at}</div>
                    <div><strong>文件路径:</strong> {apiResult.file_path}</div>
                  </div>
                }
                type="success"
                showIcon
              />
            )}
          </Space>
        </Card>

        {/* DXF查看器测试 */}
        <Card title="2. DXF查看器测试" size="small">
          <Space>
            <Button 
              type="primary" 
              onClick={() => setShowViewer(true)}
              disabled={!testFilePath}
            >
              打开DXF查看器
            </Button>
            <Text type="secondary">
              将会使用上面的文件路径打开查看器
            </Text>
          </Space>
        </Card>

        {/* 调试信息 */}
        <Card title="3. 调试信息" size="small">
          <Space direction="vertical">
            <Text><strong>当前文件路径:</strong> {testFilePath}</Text>
            <Text><strong>API结果:</strong> {apiResult ? '有数据' : '无数据'}</Text>
            <Text><strong>错误信息:</strong> {apiError || '无错误'}</Text>
            <Alert
              message="调试步骤"
              description={
                <ol>
                  <li>首先测试API调用，确保能获取到预签名URL</li>
                  <li>如果API成功，再测试DXF查看器</li>
                  <li>打开浏览器开发者工具查看详细日志</li>
                  <li>检查网络请求是否成功</li>
                </ol>
              }
              type="info"
            />
          </Space>
        </Card>
      </Space>

      {/* DXF查看器弹窗 */}
      <WorkingDxfViewer
        visible={showViewer}
        onClose={() => setShowViewer(false)}
        filePath={testFilePath}
        partName="测试图纸"
      />
    </div>
  )
}

export default DebugDxfViewer
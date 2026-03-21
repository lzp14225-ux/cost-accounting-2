import React from 'react'
import { Button, Space, Typography, Card, Alert } from 'antd'
import DrawingViewButton from '../components/DrawingViewButton'
import MessageDrawingViewer from '../components/MessageDrawingViewer'

const { Title, Text } = Typography

const DrawingViewerTest: React.FC = () => {
  // 测试数据
  const testMessage = {
    content: '特征识别完成，发现以下图纸文件：dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-01.dxf 和 dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-02.dxf',
    progressData: {
      type: 'review_display_view',
      data: [
        {
          part_code: 'LP-01',
          part_name: '左侧面板',
          subgraph_file_url: 'dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-01.dxf'
        },
        {
          part_code: 'LP-02',
          part_name: '右侧面板',
          subgraph_file_url: 'dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-02.dxf'
        }
      ]
    }
  }

  return (
    <div style={{ padding: '20px', maxWidth: 800, margin: '0 auto' }}>
      <Title level={2}>DXF 3D 图纸查看器测试</Title>
      
      <Space direction="vertical" size={24} style={{ width: '100%' }}>
        {/* 功能说明 */}
        <Alert
          message="DXF 3D 渲染功能已修复"
          description="修复了clearColor选项问题，现在使用最简配置确保DXF查看器能正常工作。点击查看图纸按钮将会显示真正的3D DXF渲染。"
          type="success"
          showIcon
        />

        {/* 单个图纸查看按钮测试 */}
        <Card title="单个图纸查看按钮" size="small">
          <Space>
            <DrawingViewButton
              filePath="dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-01.dxf"
              partName="左侧面板"
            />
            <DrawingViewButton
              filePath="dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-02.dxf"
              partName="右侧面板"
              type="primary"
            />
          </Space>
        </Card>

        {/* 消息中的图纸查看器测试 */}
        <Card title="消息中的图纸查看器" size="small">
          <div style={{ 
            background: '#f8f9fa', 
            padding: 16, 
            borderRadius: 8,
            border: '1px solid #e9ecef'
          }}>
            <Text>{testMessage.content}</Text>
            
            <MessageDrawingViewer
              content={testMessage.content}
              progressData={testMessage.progressData}
            />
          </div>
        </Card>

        {/* 3D 渲染功能说明 */}
        <Card title="3D 渲染功能" size="small">
          <Space direction="vertical">
            <Text>
              <strong>已集成的功能：</strong>
            </Text>
            <ul>
              <li>✅ 真正的DXF 3D渲染（基于Three.js和WebGL）</li>
              <li>✅ 鼠标交互控制：左键旋转、滚轮缩放、右键平移</li>
              <li>✅ 自动适应视图（FitView）</li>
              <li>✅ 高性能渲染，支持大型DXF文件</li>
              <li>✅ 错误处理和重新加载功能</li>
              <li>✅ 响应式布局，自动调整大小</li>
            </ul>
            
            <Alert
              message="操作提示"
              description={
                <div>
                  <div>• 鼠标左键：旋转视图</div>
                  <div>• 鼠标滚轮：缩放视图</div>
                  <div>• 鼠标右键：平移视图</div>
                  <div>• 重新加载按钮：重新渲染DXF文件</div>
                </div>
              }
              type="info"
            />
          </Space>
        </Card>

        {/* API 测试说明 */}
        <Card title="API 测试说明" size="small">
          <Space direction="vertical">
            <Text>
              <strong>预签名URL接口：</strong> /api/v1/files/presigned-url
            </Text>
            <Text type="secondary">
              点击"查看图纸"按钮将会：
            </Text>
            <ol>
              <li>调用预签名URL接口获取文件访问链接</li>
              <li>动态加载dxf-viewer库</li>
              <li>创建DxfViewer实例并渲染3D图纸</li>
              <li>提供交互控制和下载功能</li>
            </ol>
            <Text type="warning">
              注意：需要确保网络可以访问服务器并且有有效的登录状态
            </Text>
          </Space>
        </Card>
      </Space>
    </div>
  )
}

export default DrawingViewerTest
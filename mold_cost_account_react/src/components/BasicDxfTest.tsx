import React, { useRef, useEffect, useState } from 'react'
import { Modal, Button, Alert } from 'antd'

interface BasicDxfTestProps {
  visible: boolean
  onClose: () => void
  presignedUrl: string
}

const BasicDxfTest: React.FC<BasicDxfTestProps> = ({
  visible,
  onClose,
  presignedUrl
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const [testResult, setTestResult] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)

  const runBasicTest = async () => {
    if (!containerRef.current || !presignedUrl) return

    setIsLoading(true)
    setTestResult('')
    
    try {
      const container = containerRef.current
      container.innerHTML = ''
      
      let result = '🧪 基础DXF测试开始\n\n'
      
      // 1. 测试容器
      result += `📦 容器测试:\n`
      result += `- 尺寸: ${container.clientWidth} x ${container.clientHeight}\n`
      result += `- 父元素: ${container.parentElement?.tagName}\n\n`
      
      // 2. 测试URL
      result += `🔗 URL测试:\n`
      result += `- URL长度: ${presignedUrl.length}\n`
      result += `- URL前缀: ${presignedUrl.substring(0, 50)}...\n\n`
      
      // 3. 测试文件下载
      result += `📥 文件下载测试:\n`
      try {
        const response = await fetch(presignedUrl)
        result += `- HTTP状态: ${response.status} ${response.statusText}\n`
        result += `- Content-Type: ${response.headers.get('content-type')}\n`
        result += `- Content-Length: ${response.headers.get('content-length')}\n`
        
        const arrayBuffer = await response.arrayBuffer()
        result += `- 文件大小: ${arrayBuffer.byteLength} bytes\n`
        result += `- 文件前16字节: ${Array.from(new Uint8Array(arrayBuffer.slice(0, 16))).map(b => b.toString(16).padStart(2, '0')).join(' ')}\n\n`
        
        // 4. 测试dxf-viewer导入
        result += `📚 dxf-viewer导入测试:\n`
        try {
          const dxfModule = await import('dxf-viewer')
          result += `- 模块导入: ✅ 成功\n`
          result += `- 可用类: ${Object.keys(dxfModule).join(', ')}\n`
          
          const { DxfViewer } = dxfModule
          result += `- DxfViewer类: ${typeof DxfViewer}\n\n`
          
          // 5. 测试DxfViewer创建
          result += `🏗️ DxfViewer创建测试:\n`
          try {
            const viewer = new DxfViewer(container)
            result += `- 创建实例: ✅ 成功\n`
            result += `- HasRenderer: ${viewer.HasRenderer()}\n`
            
            try {
              const canvas = viewer.GetCanvas()
              result += `- Canvas获取: ${canvas ? '✅ 成功' : '❌ 失败'}\n`
              if (canvas) {
                result += `- Canvas尺寸: ${canvas.width} x ${canvas.height}\n`
                result += `- Canvas类型: ${canvas.constructor.name}\n`
              }
            } catch (e) {
              result += `- Canvas获取: ❌ 失败 - ${e}\n`
            }
            
            // 6. 测试DXF加载
            result += `\n📄 DXF加载测试:\n`
            try {
              await viewer.Load(arrayBuffer)
              result += `- ArrayBuffer加载: ✅ 成功\n`
              
              try {
                const dxfData = viewer.GetDxf()
                result += `- DXF数据获取: ✅ 成功\n`
                result += `- DXF数据类型: ${typeof dxfData}\n`
                if (dxfData && typeof dxfData === 'object') {
                  result += `- DXF属性: ${Object.keys(dxfData).slice(0, 5).join(', ')}\n`
                }
              } catch (e) {
                result += `- DXF数据获取: ❌ 失败 - ${e}\n`
              }
              
              try {
                const bounds = viewer.GetBounds()
                result += `- 边界获取: ✅ 成功\n`
                result += `- 边界信息: ${JSON.stringify(bounds)}\n`
              } catch (e) {
                result += `- 边界获取: ❌ 失败 - ${e}\n`
              }
              
              // 7. 测试渲染
              result += `\n🎨 渲染测试:\n`
              viewer.SetSize(800, 600)
              result += `- 设置尺寸: ✅ 完成\n`
              
              viewer.FitView()
              result += `- FitView: ✅ 完成\n`
              
              viewer.Render()
              result += `- Render: ✅ 完成\n`
              
              // 检查最终canvas状态
              const finalCanvas = viewer.GetCanvas()
              if (finalCanvas) {
                result += `- 最终Canvas尺寸: ${finalCanvas.width} x ${finalCanvas.height}\n`
                result += `- Canvas样式: ${finalCanvas.style.cssText || '无样式'}\n`
              }
              
            } catch (loadError) {
              result += `- ArrayBuffer加载: ❌ 失败 - ${loadError}\n`
              
              // 尝试URL加载
              try {
                await viewer.Load(presignedUrl)
                result += `- URL加载: ✅ 成功\n`
              } catch (urlError) {
                result += `- URL加载: ❌ 失败 - ${urlError}\n`
              }
            }
            
          } catch (viewerError) {
            result += `- 创建实例: ❌ 失败 - ${viewerError}\n`
          }
          
        } catch (importError) {
          result += `- 模块导入: ❌ 失败 - ${importError}\n`
        }
        
      } catch (fetchError) {
        result += `- 文件下载: ❌ 失败 - ${fetchError}\n`
      }
      
      result += `\n🏁 测试完成`
      setTestResult(result)
      
    } catch (error) {
      setTestResult(`❌ 测试过程中发生错误: ${error}`)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    if (visible && presignedUrl && containerRef.current) {
      runBasicTest()
    }
  }, [visible, presignedUrl])

  return (
    <Modal
      title="DXF基础测试"
      open={visible}
      onCancel={onClose}
      footer={[
        <Button key="retest" onClick={runBasicTest} loading={isLoading}>
          重新测试
        </Button>,
        <Button key="close" onClick={onClose}>
          关闭
        </Button>
      ]}
      width="80%"
      style={{ maxWidth: 1000 }}
    >
      <div style={{ display: 'flex', gap: 16, height: '70vh' }}>
        {/* 左侧：测试结果 */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          <Alert
            message="测试结果"
            description={
              <pre style={{ 
                whiteSpace: 'pre-wrap', 
                fontSize: 12, 
                lineHeight: 1.4,
                margin: 0,
                maxHeight: '60vh',
                overflow: 'auto'
              }}>
                {testResult || '等待测试...'}
              </pre>
            }
            type="info"
          />
        </div>
        
        {/* 右侧：DXF容器 */}
        <div style={{ flex: 1 }}>
          <div
            ref={containerRef}
            style={{
              width: '100%',
              height: '100%',
              border: '2px solid #1890ff',
              borderRadius: 4,
              background: '#f0f0f0'
            }}
          />
        </div>
      </div>
    </Modal>
  )
}

export default BasicDxfTest
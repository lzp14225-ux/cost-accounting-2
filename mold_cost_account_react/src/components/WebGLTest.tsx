import React, { useRef, useEffect, useState } from 'react'
import { Modal, Button, Alert } from 'antd'

interface WebGLTestProps {
  visible: boolean
  onClose: () => void
}

const WebGLTest: React.FC<WebGLTestProps> = ({ visible, onClose }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [testResult, setTestResult] = useState<string>('')

  const runWebGLTest = () => {
    let result = '🧪 WebGL支持测试\n\n'
    
    try {
      // 1. 检查WebGL支持
      const canvas = canvasRef.current
      if (!canvas) {
        result += '❌ Canvas元素未找到\n'
        setTestResult(result)
        return
      }
      
      result += '✅ Canvas元素创建成功\n'
      
      // 2. 测试WebGL上下文
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
      if (!gl) {
        result += '❌ WebGL不支持\n'
        result += '可能原因：\n'
        result += '- 浏览器不支持WebGL\n'
        result += '- 显卡驱动问题\n'
        result += '- WebGL被禁用\n'
        setTestResult(result)
        return
      }
      
      result += '✅ WebGL上下文创建成功\n'
      
      // 3. 获取WebGL信息
      result += `\n📊 WebGL信息:\n`
      result += `- 版本: ${gl.getParameter(gl.VERSION)}\n`
      result += `- 渲染器: ${gl.getParameter(gl.RENDERER)}\n`
      result += `- 供应商: ${gl.getParameter(gl.VENDOR)}\n`
      result += `- GLSL版本: ${gl.getParameter(gl.SHADING_LANGUAGE_VERSION)}\n`
      
      // 4. 测试基本渲染
      result += `\n🎨 基本渲染测试:\n`
      
      // 设置视口
      gl.viewport(0, 0, canvas.width, canvas.height)
      result += `- 视口设置: ✅ ${canvas.width}x${canvas.height}\n`
      
      // 清除颜色
      gl.clearColor(0.2, 0.4, 0.8, 1.0)
      gl.clear(gl.COLOR_BUFFER_BIT)
      result += `- 清除颜色: ✅ 蓝色背景\n`
      
      // 5. 测试Three.js兼容性
      result += `\n🔧 Three.js兼容性测试:\n`
      try {
        // 检查必要的WebGL扩展
        const extensions = [
          'OES_texture_float',
          'OES_texture_half_float',
          'WEBGL_depth_texture',
          'OES_standard_derivatives'
        ]
        
        extensions.forEach(ext => {
          const supported = gl.getExtension(ext)
          result += `- ${ext}: ${supported ? '✅' : '❌'}\n`
        })
        
      } catch (e) {
        result += `- 扩展检查失败: ${e}\n`
      }
      
      result += `\n✅ WebGL测试完成`
      
    } catch (error) {
      result += `❌ 测试过程中发生错误: ${error}\n`
    }
    
    setTestResult(result)
  }

  useEffect(() => {
    if (visible) {
      setTimeout(runWebGLTest, 100)
    }
  }, [visible])

  return (
    <Modal
      title="WebGL支持测试"
      open={visible}
      onCancel={onClose}
      footer={[
        <Button key="retest" onClick={runWebGLTest}>
          重新测试
        </Button>,
        <Button key="close" onClick={onClose}>
          关闭
        </Button>
      ]}
      width="60%"
    >
      <div style={{ display: 'flex', gap: 16, height: '50vh' }}>
        {/* 左侧：测试结果 */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          <Alert
            message="WebGL测试结果"
            description={
              <pre style={{ 
                whiteSpace: 'pre-wrap', 
                fontSize: 12, 
                lineHeight: 1.4,
                margin: 0,
                maxHeight: '40vh',
                overflow: 'auto'
              }}>
                {testResult || '正在测试...'}
              </pre>
            }
            type="info"
          />
        </div>
        
        {/* 右侧：WebGL Canvas */}
        <div style={{ flex: 1 }}>
          <canvas
            ref={canvasRef}
            width={300}
            height={200}
            style={{
              width: '100%',
              height: '200px',
              border: '2px solid #1890ff',
              borderRadius: 4
            }}
          />
          <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
            如果WebGL正常，这里应该显示蓝色背景
          </div>
        </div>
      </div>
    </Modal>
  )
}

export default WebGLTest
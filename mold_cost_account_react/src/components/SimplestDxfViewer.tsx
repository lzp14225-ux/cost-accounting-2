import React, { useState, useRef, useEffect } from 'react'
import { Modal, Button, Typography, Space, message, Spin, Alert } from 'antd'
import { EyeOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { fileService } from '../services/fileService'
import BasicDxfTest from './BasicDxfTest'
import WebGLTest from './WebGLTest'

const { Text } = Typography

interface SimplestDxfViewerProps {
  visible: boolean
  onClose: () => void
  filePath: string
  partName: string
}

const SimplestDxfViewer: React.FC<SimplestDxfViewerProps> = ({
  visible,
  onClose,
  filePath,
  partName
}) => {
  const [loading, setLoading] = useState(false)
  const [presignedUrl, setPresignedUrl] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [dxfLoading, setDxfLoading] = useState(false)
  const [dxfError, setDxfError] = useState<string>('')
  const [showBasicTest, setShowBasicTest] = useState(false)
  const [showWebGLTest, setShowWebGLTest] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)

  // 当弹窗打开时获取预签名URL
  useEffect(() => {
    if (visible && filePath && !presignedUrl) {
      handleGetPresignedUrl()
    }
  }, [visible, filePath])

  // 当获取到URL后加载DXF文件
  useEffect(() => {
    if (presignedUrl && containerRef.current && visible) {
      loadDxfFile()
    }
  }, [presignedUrl, visible])

  // 处理窗口尺寸变化和键盘事件
  useEffect(() => {
    if (!visible || !viewerRef.current) return

    const handleResize = () => {
      const container = containerRef.current
      if (container && viewerRef.current) {
        const width = container.clientWidth || 800
        const height = container.clientHeight || 600
        console.log('🔄 窗口尺寸变化，重新设置:', width, 'x', height)
        
        // 只重新设置尺寸，不调用FitView（避免图纸消失）
        try {
          viewerRef.current.SetSize(width, height)
        } catch (error) {
          console.warn('调整尺寸失败:', error)
        }
      }
    }

    const handleKeyPress = (event: KeyboardEvent) => {
      // 按空格键重置视图
      if (event.code === 'Space' && visible) {
        event.preventDefault()
        handleResetView()
      }
      
      // 按R键重置视图
      if (event.key === 'r' || event.key === 'R') {
        if (visible) {
          event.preventDefault()
          handleResetView()
        }
      }
    }

    // 监听窗口变化和键盘事件
    window.addEventListener('resize', handleResize)
    window.addEventListener('keydown', handleKeyPress)
    
    // 延迟初始化，确保容器已渲染
    const timer = setTimeout(handleResize, 300)
    
    return () => {
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('keydown', handleKeyPress)
      clearTimeout(timer)
    }
  }, [visible, presignedUrl])

  // 清理viewer
  useEffect(() => {
    return () => {
      if (viewerRef.current) {
        try {
          viewerRef.current.Destroy()
        } catch (error) {
          console.warn('Error destroying DXF viewer:', error)
        }
      }
    }
  }, [])

  // 获取预签名URL
  const handleGetPresignedUrl = async () => {
    try {
      setLoading(true)
      setError('')
      
      console.log('🔄 开始获取预签名URL，文件路径:', filePath)
      const result = await fileService.getPresignedUrl(filePath, 3600)
      console.log('✅ 预签名URL获取成功:', result)
      
      if (!result.url || typeof result.url !== 'string') {
        throw new Error('API返回的URL无效')
      }
      
      setPresignedUrl(result.url)
      
    } catch (error: any) {
      console.error('❌ 获取预签名URL失败:', error)
      setError(error.message || '获取图纸链接失败')
      message.error('获取图纸链接失败')
    } finally {
      setLoading(false)
    }
  }

  // 加载DXF文件
  const loadDxfFile = async () => {
    if (!containerRef.current || !presignedUrl) return

    try {
      setDxfLoading(true)
      setDxfError('')

      // 动态导入dxf-viewer
      const { DxfViewer } = await import('dxf-viewer')
      
      // 清理之前的viewer
      if (viewerRef.current) {
        viewerRef.current.Destroy()
      }

      // 清空容器
      const container = containerRef.current
      container.innerHTML = ''

      // 获取容器的实际尺寸
      const width = container.clientWidth || 800
      const height = container.clientHeight || 600
      console.log('📐 容器尺寸:', width, 'x', height)

      console.log('📦 创建DxfViewer实例')
      // 创建viewer
      const viewer = new DxfViewer(container, {
        canvasWidth: width,
        canvasHeight: height,
        autoResize: false
      })
      viewerRef.current = viewer
      
      console.log('✅ DxfViewer实例创建成功')

      console.log('🔄 加载DXF文件...')
      
      // 加载DXF文件
      // 注意：dxf-viewer不支持SHX字体文件（AutoCAD专有格式）
      // 只支持OpenType字体（TTF/OTF），但DXF文件通常使用SHX字体
      // 因此文字可能无法显示，这是库的已知限制
      await viewer.Load({ 
        url: presignedUrl
      } as any)
      console.log('✅ DXF文件加载成功')
      
      // 详细检查DXF数据中的文本
      try {
        const dxf = viewer.GetDxf()
        console.log('🔍 ===== DXF文本诊断报告 =====')
        
        if (dxf && dxf.entities) {
          const textEntities = dxf.entities.filter((e: any) => 
            e.type === 'TEXT' || e.type === 'MTEXT'
          )
          
          console.log(`📊 文本实体总数: ${textEntities.length}`)
          
          if (textEntities.length > 0) {
            console.log('📝 文本详细信息:')
            textEntities.slice(0, 5).forEach((entity: any, index: number) => {
              console.log(`  ${index + 1}. 类型: ${entity.type}`)
              console.log(`     文本: "${entity.text || entity.textString || '(空)'}"`)
              console.log(`     字体样式: ${entity.style || '(未指定)'}`)
              console.log(`     位置: (${entity.position?.x}, ${entity.position?.y})`)
              console.log(`     高度: ${entity.height || '(未指定)'}`)
            })
            
            // 检查字体样式表
            if (dxf.tables && dxf.tables.style) {
              console.log('🎨 字体样式表:')
              dxf.tables.style.forEach((style: any) => {
                console.log(`  - 样式名: ${style.name}`)
                console.log(`    字体文件: ${style.fontFile || style.primaryFontFile || '(未指定)'}`)
                console.log(`    大字体: ${style.bigFontFile || '(无)'}`)
              })
            }
            
            // console.log('')
            // console.log('⚠️ ===== 重要说明 =====')
            // console.log('❌ dxf-viewer库不支持SHX字体文件')
            // console.log('❌ SHX是AutoCAD专有格式，不是Web标准字体')
            // console.log('❌ 即使字体文件存在于/fonts目录，也无法加载')
            // console.log('')
            // console.log('💡 解决方案:')
            // console.log('1. 在AutoCAD中使用TXTEXP命令将文字炸开为几何图形')
            // console.log('2. 或使用EXPLODE命令分解文字')
            // console.log('3. 或考虑使用支持SHX的商业查看器')
            // console.log('4. 或在服务端用AutoCAD引擎渲染为图片')
            // console.log('========================')
          } else {
            console.log('✅ DXF文件不包含文本实体')
          }
        }
      } catch (e) {
        console.error('❌ 无法检查文本实体:', e)
      }
      
      console.log('🎉 DXF加载完成！')
      
      setDxfLoading(false)
      
    } catch (error: any) {
      console.error('❌ DXF文件加载失败:', error)
      setDxfError(`加载失败: ${error.message}`)
      setDxfLoading(false)
    }
  }

  // 适应视图 - 只在用户点击按钮时调用
  const handleResetView = () => {
    if (viewerRef.current && containerRef.current) {
      console.log('🔄 适应视图开始')
      const container = containerRef.current
      const width = container.clientWidth || 800
      const height = container.clientHeight || 600
      
      console.log('📏 当前容器尺寸:', width, 'x', height)
      
      try {
        // 重新设置尺寸
        viewerRef.current.SetSize(width, height)
        
        // 执行FitView
        viewerRef.current.FitView()
        
        console.log('✅ 适应完成')
        message.success('视图已适应')
        
      } catch (error) {
        console.error('❌ 适应视图失败:', error)
        message.error('视图适应失败')
      }
    }
  }

  // 调试信息
  const handleDebugInfo = () => {
    if (viewerRef.current && containerRef.current) {
      console.log('🐛 === DXF查看器调试信息 ===')
      
      const container = containerRef.current
      console.log('📦 容器信息:')
      console.log('- 尺寸:', container.clientWidth, 'x', container.clientHeight)
      console.log('- 样式:', container.style.cssText)
      console.log('- 子元素数量:', container.children.length)
      
      const viewer = viewerRef.current
      console.log('🔍 Viewer状态:')
      console.log('- HasRenderer:', viewer.HasRenderer())
      
      try {
        const canvas = viewer.GetCanvas()
        if (canvas) {
          console.log('🖼️ Canvas信息:')
          console.log('- 尺寸:', canvas.width, 'x', canvas.height)
          console.log('- 样式:', canvas.style.cssText)
          console.log('- 父元素:', canvas.parentElement)
        } else {
          console.log('❌ 无Canvas元素')
        }
      } catch (e) {
        console.log('❌ 获取Canvas失败:', e)
      }
      
      try {
        const dxf = viewer.GetDxf()
        console.log('📄 DXF数据:', dxf)
      } catch (e) {
        console.log('❌ 获取DXF数据失败:', e)
      }
      
      try {
        const bounds = viewer.GetBounds()
        console.log('📐 边界信息:', bounds)
      } catch (e) {
        console.log('❌ 获取边界失败:', e)
      }
      
      console.log('🐛 === 调试信息结束 ===')
    }
  }

  // 重新加载DXF文件
  const handleReloadDxf = () => {
    if (presignedUrl) {
      loadDxfFile()
    } else {
      handleGetPresignedUrl()
    }
  }

  // 下载文件
  const handleDownload = () => {
    if (presignedUrl) {
      const link = document.createElement('a')
      link.href = presignedUrl
      link.download = `${partName}.dxf`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
  }

  // 重置状态
  const handleClose = () => {
    if (viewerRef.current) {
      try {
        viewerRef.current.Destroy()
      } catch (error) {
        console.warn('Error destroying DXF viewer:', error)
      }
      viewerRef.current = null
    }
    
    setPresignedUrl('')
    setError('')
    setDxfError('')
    setLoading(false)
    setDxfLoading(false)
    
    onClose()
  }

  return (
    <Modal
      title={
        <Space>
          <EyeOutlined />
          <span>查看图纸 - {partName}</span>
        </Space>
      }
      open={visible}
      onCancel={handleClose}
      footer={[
        <Button 
          key="webgl" 
          onClick={() => setShowWebGLTest(true)} 
          style={{ backgroundColor: '#722ed1', borderColor: '#722ed1', color: 'white' }}
        >
          WebGL测试
        </Button>,
        <Button 
          key="test" 
          onClick={() => setShowBasicTest(true)} 
          disabled={!presignedUrl}
          style={{ backgroundColor: '#52c41a', borderColor: '#52c41a', color: 'white' }}
        >
          基础测试
        </Button>,
        <Button 
          key="debug" 
          onClick={handleDebugInfo} 
          disabled={!presignedUrl || dxfLoading}
          style={{ backgroundColor: '#ff9800', borderColor: '#ff9800', color: 'white' }}
        >
          调试信息
        </Button>,
        <Button 
          key="reload" 
          icon={<ReloadOutlined />} 
          onClick={handleReloadDxf} 
          disabled={!presignedUrl || dxfLoading}
        >
          重新加载
        </Button>,
        <Button 
          key="download" 
          icon={<DownloadOutlined />} 
          onClick={handleDownload} 
          disabled={!presignedUrl}
        >
          下载
        </Button>,
        <Button key="close" onClick={handleClose}>
          关闭
        </Button>
      ]}
      width="90%"
      style={{ maxWidth: 1200 }}
      styles={{
        body: { height: '70vh', padding: 0 }
      }}
    >
      <div style={{ 
        height: '100%', 
        display: 'flex',
        flexDirection: 'column',
        background: '#f5f5f5'
      }}>
        {loading ? (
          <div style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'column',
            gap: 16
          }}>
            <Spin size="large" />
            <Text type="secondary">正在获取图纸链接...</Text>
          </div>
        ) : error ? (
          <div style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'column',
            gap: 16
          }}>
            <Alert
              message="获取图纸失败"
              description={error}
              type="error"
              showIcon
            />
            <Button onClick={handleGetPresignedUrl}>重试</Button>
          </div>
        ) : presignedUrl ? (
          <div style={{ flex: 1, position: 'relative' }}>
            {/* DXF 3D 渲染区域 */}
            <div
              ref={containerRef}
              style={{
                width: '100%',
                height: '100%',
                background: '#ffffff',
                border: '1px solid #d9d9d9'
              }}
              onDoubleClick={handleResetView}
              title="双击重置视图"
            />
            
            {/* 操作提示 */}
            {!dxfLoading && !dxfError && presignedUrl && (
              <div style={{
                position: 'absolute',
                top: 10,
                right: 10,
                background: 'rgba(0, 0, 0, 0.8)',
                color: 'white',
                padding: '10px 14px',
                borderRadius: 6,
                fontSize: 12,
                zIndex: 5,
                pointerEvents: 'none',
                lineHeight: '1.4'
              }}>
                <div>🖱️ 左键拖拽：旋转视图</div>
                <div>🎯 滚轮：缩放视图</div>
                <div style={{ marginTop: 4, paddingTop: 4, borderTop: '1px solid rgba(255,255,255,0.3)' }}>
                  <div>🔄 双击画面：适应视图</div>
                  <div>⌨️ 空格键/R键：适应视图</div>
                </div>
              </div>
            )}
            
            {/* DXF加载状态覆盖层 */}
            {dxfLoading && (
              <div style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: 'rgba(255, 255, 255, 0.8)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexDirection: 'column',
                gap: 16,
                zIndex: 10
              }}>
                <Spin size="large" />
                <Text type="secondary">正在渲染DXF图纸...</Text>
              </div>
            )}
            
            {/* DXF加载错误覆盖层 */}
            {dxfError && (
              <div style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: 'rgba(255, 255, 255, 0.9)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexDirection: 'column',
                gap: 16,
                zIndex: 10,
                padding: 20
              }}>
                <Alert
                  message="DXF渲染失败"
                  description={dxfError}
                  type="error"
                  showIcon
                />
                <Button onClick={handleReloadDxf}>重新加载</Button>
              </div>
            )}
          </div>
        ) : (
          <div style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <Text type="secondary">准备加载图纸...</Text>
          </div>
        )}
      </div>

      {/* 基础测试弹窗 */}
      <BasicDxfTest
        visible={showBasicTest}
        onClose={() => setShowBasicTest(false)}
        presignedUrl={presignedUrl}
      />

      {/* WebGL测试弹窗 */}
      <WebGLTest
        visible={showWebGLTest}
        onClose={() => setShowWebGLTest(false)}
      />
    </Modal>
  )
}

export default SimplestDxfViewer
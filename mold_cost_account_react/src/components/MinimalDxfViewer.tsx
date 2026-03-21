import React, { useState, useRef, useEffect } from 'react'
import { Modal, Button, Typography, Space, message, Spin, Alert } from 'antd'
import { EyeOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { fileService } from '../services/fileService'

const { Text } = Typography

interface MinimalDxfViewerProps {
  visible: boolean
  onClose: () => void
  filePath: string
  partName: string
}

const MinimalDxfViewer: React.FC<MinimalDxfViewerProps> = ({
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
  const [textOverlays, setTextOverlays] = useState<any[]>([]) // 文字覆盖层
  const [showTextOverlay, setShowTextOverlay] = useState(true) // 是否显示文字覆盖层
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

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

  // 移除滚轮事件监听器 - 不需要在滚轮后重新加载，这会导致闪烁

  // 监听窗口尺寸变化，动态调整 viewer 尺寸
  useEffect(() => {
    if (!visible || !viewerRef.current || !containerRef.current) return

    const handleResize = () => {
      const container = containerRef.current
      if (container && viewerRef.current) {
        const width = container.clientWidth || 800
        const height = container.clientHeight || 600
        console.log('🔄 窗口尺寸变化，重新设置:', width, 'x', height)
        
        try {
          viewerRef.current.SetSize(width, height)
          // 不调用 FitView，避免视图被重置导致图纸消失
          // viewerRef.current.FitView()
        } catch (error) {
          console.warn('调整尺寸失败:', error)
        }
      }
    }

    // 监听窗口变化
    window.addEventListener('resize', handleResize)
    
    // 初始调整尺寸（不调用FitView）
    const timer = setTimeout(handleResize, 100)
    
    return () => {
      window.removeEventListener('resize', handleResize)
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
      
      const result = await fileService.getPresignedUrl(filePath, 3600)
      setPresignedUrl(result.url)
      
    } catch (error: any) {
      console.error('获取预签名URL失败:', error)
      setError(error.message || '获取图纸链接失败')
      message.error('获取图纸链接失败')
    } finally {
      setLoading(false)
    }
  }

  // 加载DXF文件 - 最简单的实现
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

      // 创建viewer
      const viewer = new DxfViewer(container, {
        canvasWidth: width,
        canvasHeight: height,
        autoResize: false
      })
      viewerRef.current = viewer

      console.log('✅ DxfViewer实例创建成功')

      // 加载DXF文件
      // 注意：dxf-viewer不支持SHX字体文件（AutoCAD专有格式）
      // 只支持OpenType字体（TTF/OTF），但DXF文件通常使用SHX字体
      // 因此文字可能无法显示，这是库的已知限制
      await viewer.Load({ 
        url: presignedUrl,
        fonts: [
            // 'fonts/1.SHX', 
            'SimHei.ttf',
        ]
      })
      console.log('✅ DXF文件加载成功')
      
      // 详细检查DXF数据中的文本
      try {
        const dxf = viewer.GetDxf()
        console.log('🔍 ===== DXF文本诊断报告 =====')
        
        if (dxf && dxf.entities) {
          const textEntities = dxf.entities.filter((e: any) => 
            e.type === 'TEXT' || e.type === 'MTEXT'
          )
          
          if (textEntities.length > 0) {
            console.log('� 文本详细信息:')
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

      // 不自动调用 FitView()，避免图纸消失
      // 用户可以通过"适应视图"按钮手动调整
      console.log('ℹ️ 图纸已加载，点击"适应视图"按钮可调整视图')
      
      setDxfLoading(false)
      
    } catch (error: any) {
      console.error('DXF文件加载失败:', error)
      setDxfError(`加载失败: ${error.message}`)
      setDxfLoading(false)
    }
  }

  // 适应视图 - 只在用户点击按钮时调用
  const handleResetView = () => {
    if (viewerRef.current && containerRef.current) {
      try {
        console.log('🔄 适应视图')
        const container = containerRef.current
        const width = container.clientWidth || 800
        const height = container.clientHeight || 600
        
        // 重新设置尺寸并调整视图
        viewerRef.current.SetSize(width, height)
        viewerRef.current.FitView()
        
        message.success('视图已适应')
      } catch (error) {
        console.error('适应视图失败:', error)
        message.error('视图适应失败')
      }
    }
  }

  // 重新加载
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
            />
            
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
            
            {/* 操作提示 */}
            {!dxfLoading && !dxfError && presignedUrl && (
              <div style={{
                position: 'absolute',
                top: 10,
                right: 10,
                background: 'rgba(0, 0, 0, 0.85)',
                color: 'white',
                padding: '12px 16px',
                borderRadius: 6,
                fontSize: 12,
                zIndex: 5,
                pointerEvents: 'none',
                lineHeight: '1.8',
                boxShadow: '0 2px 8px rgba(0,0,0,0.3)'
              }}>
                <div style={{ fontWeight: 'bold', marginBottom: 6, fontSize: 13 }}>📖 操作说明</div>
                <div>🎯 滚轮：缩放图纸</div>
                <div>🖱️ 左键拖拽：旋转视角</div>
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
    </Modal>
  )
}

export default MinimalDxfViewer

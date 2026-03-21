import React, { useState, useRef, useEffect } from 'react'
import { Modal, Button, Typography, Space, message, Spin, Alert } from 'antd'
import { EyeOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { fileService } from '../services/fileService'

const { Text } = Typography

interface WorkingDxfViewerProps {
  visible: boolean
  onClose: () => void
  filePath: string
  partName: string
}

const WorkingDxfViewer: React.FC<WorkingDxfViewerProps> = ({
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

  // 处理窗口尺寸变化
  useEffect(() => {
    if (!visible || !viewerRef.current) return

    const handleResize = () => {
      const container = containerRef.current
      if (container && viewerRef.current) {
        const width = container.clientWidth || 800
        const height = container.clientHeight || 600
        console.log('🔄 窗口尺寸变化，重新设置:', width, 'x', height)
        
        // 只重新设置尺寸，不调用FitView（避免NaN问题）
        viewerRef.current.SetSize(width, height)
      }
    }

    // 监听窗口变化
    window.addEventListener('resize', handleResize)
    
    // 延迟初始化，确保容器已渲染
    const timer = setTimeout(handleResize, 300)
    
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
      
      console.log('🔄 开始获取预签名URL，文件路径:', filePath)
      const result = await fileService.getPresignedUrl(filePath, 3600)
      console.log('✅ 预签名URL获取成功:', result)
      console.log('📋 返回的URL:', result.url)
      console.log('📋 URL长度:', result.url?.length)
      
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

      console.log('📦 创建DxfViewer实例')
      const viewer = new DxfViewer(container)
      viewerRef.current = viewer
      
      console.log('✅ DxfViewer实例创建成功')

      console.log('🔄 加载DXF文件...')
      
      // 加载文件 - 使用对象格式
      await viewer.Load({ url: presignedUrl })
      console.log('✅ DXF文件加载成功')
      
      // 设置视图 - 多次调用确保正确显示
      viewer.FitView()
      console.log('✅ 第1次FitView完成')
      
      // 延迟再次FitView
      setTimeout(() => {
        if (viewerRef.current) {
          viewerRef.current.FitView()
          console.log('✅ 第2次FitView完成 (100ms)')
        }
      }, 100)
      
      setTimeout(() => {
        if (viewerRef.current) {
          viewerRef.current.FitView()
          console.log('✅ 第3次FitView完成 (300ms)')
        }
      }, 300)
      
      setTimeout(() => {
        if (viewerRef.current) {
          viewerRef.current.FitView()
          console.log('✅ 第4次FitView完成 (600ms)')
        }
      }, 600)
      
      console.log('🎉 DXF加载完成！')
      
    } catch (error: any) {
      console.error('❌ DXF文件加载失败:', error)
      setDxfError(`加载失败: ${error.message}`)
    } finally {
      setDxfLoading(false)
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
                border: '1px solid #d9d9d9',
                borderRadius: 6,
                overflow: 'hidden'
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
                background: 'rgba(0, 0, 0, 0.7)',
                color: 'white',
                padding: '8px 12px',
                borderRadius: 4,
                fontSize: 12,
                zIndex: 5,
                pointerEvents: 'none'
              }}>
                <div>鼠标左键：旋转</div>
                <div>鼠标滚轮：缩放</div>
                <div>鼠标右键：平移</div>
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

export default WorkingDxfViewer
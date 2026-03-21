import React, { useState, useRef, useEffect } from 'react'
import { Modal, Button, Typography, Space, message, Spin, Alert } from 'antd'
import { EyeOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { fileService } from '../services/fileService'

const { Text } = Typography

interface SimpleDxfViewerProps {
  visible: boolean
  onClose: () => void
  filePath: string
  partName: string
}

const SimpleDxfViewer: React.FC<SimpleDxfViewerProps> = ({
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
    console.log('useEffect触发 - 弹窗状态变化:', {
      visible: visible,
      filePath: filePath,
      hasPresignedUrl: !!presignedUrl
    })
    
    if (visible && filePath && !presignedUrl) {
      console.log('开始获取预签名URL')
      handleGetPresignedUrl()
    }
  }, [visible, filePath])

  // 当获取到URL后加载DXF文件
  useEffect(() => {
    console.log('useEffect触发 - presignedUrl变化:', {
      presignedUrl: presignedUrl,
      hasContainer: !!containerRef.current,
      visible: visible
    })
    
    if (presignedUrl && containerRef.current && visible) {
      console.log('条件满足，开始加载DXF文件')
      loadDxfFile()
    }
  }, [presignedUrl, visible])

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
      
      console.log('获取预签名URL:', filePath)
      
      if (!filePath || typeof filePath !== 'string' || filePath.trim() === '') {
        throw new Error('文件路径无效或为空')
      }
      
      const result = await fileService.getPresignedUrl(filePath, 3600)
      
      console.log('预签名URL获取成功:', result)
      
      if (!result || !result.url) {
        throw new Error('预签名URL响应无效')
      }
      
      console.log('设置预签名URL:', result.url)
      setPresignedUrl(result.url)
      
    } catch (error: any) {
      console.error('获取预签名URL失败:', error)
      setError(error.message || '获取图纸链接失败')
      message.error('获取图纸链接失败')
    } finally {
      setLoading(false)
    }
  }

  // 加载DXF文件 - 简化版本，专注于解决clearColor问题
  const loadDxfFile = async () => {
    if (!containerRef.current || !presignedUrl) {
      console.error('加载DXF失败：容器或URL为空', {
        hasContainer: !!containerRef.current,
        presignedUrl: presignedUrl
      })
      return
    }

    try {
      setDxfLoading(true)
      setDxfError('')

      console.log('开始加载DXF查看器...')
      console.log('预签名URL:', presignedUrl)
      
      // 验证URL格式
      if (!presignedUrl || typeof presignedUrl !== 'string' || presignedUrl.trim() === '') {
        throw new Error('预签名URL无效或为空')
      }
      
      // 动态导入dxf-viewer
      const { DxfViewer, DxfFetcher } = await import('dxf-viewer')
      
      console.log('DXF查看器加载成功，开始渲染文件:', presignedUrl)
      
      // 清理之前的viewer
      if (viewerRef.current) {
        viewerRef.current.Destroy()
      }

      // 清空容器
      const container = containerRef.current
      container.innerHTML = ''

      // 创建新的viewer实例 - 使用最简配置避免clearColor问题
      console.log('创建DxfViewer实例...')
      const viewer = new DxfViewer(container)  // 不传递任何选项，使用默认配置

      viewerRef.current = viewer

      console.log('开始加载DXF文件，URL长度:', presignedUrl.length)
      console.log('URL前100字符:', presignedUrl.substring(0, 100))
      
      // 尝试使用DxfFetcher来获取和解析DXF文件
      console.log('尝试方法: 使用DxfFetcher')
      try {
        const fetcher = new DxfFetcher()
        console.log('DxfFetcher创建成功，开始获取文件...')
        
        // DxfFetcher.Fetch需要进度回调函数
        const progressCallback = (progress: number) => {
          console.log('DXF获取进度:', progress)
        }
        
        // 使用DxfFetcher获取DXF数据
        const dxfData = await fetcher.Fetch(presignedUrl.trim(), progressCallback)
        console.log('DXF数据获取成功，类型:', typeof dxfData, '数据:', dxfData)
        
        // 将解析后的数据加载到查看器
        await viewer.Load(dxfData)
        console.log('✅ DxfFetcher方法成功')
        
      } catch (fetcherError) {
        console.log('❌ DxfFetcher方法失败:', fetcherError.message)
        
        // 尝试不使用进度回调
        console.log('尝试方法: DxfFetcher无回调')
        try {
          const fetcher = new DxfFetcher()
          const dxfData = await fetcher.Fetch(presignedUrl.trim())
          console.log('DXF数据获取成功（无回调）')
          await viewer.Load(dxfData)
          console.log('✅ DxfFetcher无回调方法成功')
        } catch (noCallbackError) {
          console.log('❌ DxfFetcher无回调方法失败:', noCallbackError.message)
          
          // 尝试创建一个File对象
          console.log('尝试方法: File对象')
          try {
            const response = await fetch(presignedUrl.trim())
            if (!response.ok) {
              throw new Error(`HTTP ${response.status}: ${response.statusText}`)
            }
            
            const blob = await response.blob()
            console.log('Blob获取成功，大小:', blob.size)
            
            // 创建File对象
            const file = new File([blob], 'drawing.dxf', { type: 'application/dxf' })
            console.log('File对象创建成功')
            
            await viewer.Load(file)
            console.log('✅ File对象方法成功')
            
          } catch (fileError) {
            console.log('❌ File对象方法失败:', fileError.message)
            
            // 最后尝试：直接传递ArrayBuffer
            console.log('尝试方法: ArrayBuffer')
            try {
              const response = await fetch(presignedUrl.trim())
              const arrayBuffer = await response.arrayBuffer()
              console.log('ArrayBuffer获取成功，大小:', arrayBuffer.byteLength)
              
              await viewer.Load(arrayBuffer)
              console.log('✅ ArrayBuffer方法成功')
              
            } catch (arrayBufferError) {
              console.log('❌ ArrayBuffer方法失败:', arrayBufferError.message)
              throw new Error(`所有加载方法都失败了。最后错误: ${arrayBufferError.message}`)
            }
          }
        }
      }
      
      console.log('DXF文件加载成功，设置视图...')
      
      // 设置初始视图
      viewer.FitView()
      
      console.log('DXF查看器初始化完成')
      
    } catch (error: any) {
      console.error('DXF文件加载失败:', error)
      setDxfError(error.message || 'DXF文件加载失败')
    } finally {
      setDxfLoading(false)
    }
  }

  // 重置状态
  const handleClose = () => {
    // 清理viewer
    if (viewerRef.current) {
      try {
        viewerRef.current.Destroy()
      } catch (error) {
        console.warn('Error destroying DXF viewer:', error)
      }
      viewerRef.current = null
    }
    
    // 重置所有状态
    setPresignedUrl('')
    setError('')
    setDxfError('')
    setLoading(false)
    setDxfLoading(false)
    
    onClose()
  }

  // 重新加载DXF文件
  const handleReloadDxf = () => {
    console.log('🔄 重新加载DXF文件')
    if (presignedUrl) {
      loadDxfFile()
    } else {
      console.log('⚠️ 没有预签名URL，重新获取')
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
          key="test" 
          onClick={async () => {
            console.log('🧪 测试API调用')
            try {
              const result = await fileService.getPresignedUrl(filePath, 3600)
              console.log('✅ 测试成功:', result)
              message.success('API测试成功，检查控制台')
            } catch (error) {
              console.error('❌ 测试失败:', error)
              message.error('API测试失败，检查控制台')
            }
          }}
        >
          测试API
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
            {!dxfLoading && !dxfError && (
              <div style={{
                position: 'absolute',
                top: 10,
                right: 10,
                background: 'rgba(0, 0, 0, 0.7)',
                color: 'white',
                padding: '8px 12px',
                borderRadius: 4,
                fontSize: 12,
                zIndex: 5
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

export default SimpleDxfViewer
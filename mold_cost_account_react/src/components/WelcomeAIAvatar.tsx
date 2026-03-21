import React, { useEffect, useRef, useState } from 'react'

interface WelcomeAIAvatarProps {
  size?: number
  onClick?: () => void
}

const WelcomeAIAvatar: React.FC<WelcomeAIAvatarProps> = ({ size = 80, onClick }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const animationFrameRef = useRef<number>()
  const mousePositionRef = useRef({ x: 0, y: 0, isTracking: false })
  const [isHovered, setIsHovered] = useState(false)
  
  const isHoveredRef = useRef(false)

  useEffect(() => { isHoveredRef.current = isHovered }, [isHovered])

  // 监听全页面鼠标移动
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect()
        const centerX = rect.left + rect.width / 2
        const centerY = rect.top + rect.height / 2
        
        // 计算鼠标相对于头像中心的位置
        mousePositionRef.current = {
          x: e.clientX - centerX,
          y: e.clientY - centerY,
          isTracking: true
        }
      }
    }

    // 监听全页面鼠标移动
    window.addEventListener('mousemove', handleMouseMove)
    
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
    }
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const width = size * 1.5
    const height = size * 2
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)

    let time = 0

    // 眨眼状态机
    const blinkRef = {
      state: 'open',
      progress: 1,
      nextBlinkTime: Date.now() + Math.random() * 4000 + 2000,
      isDoubleBlink: false
    }

    const draw = () => {
      const hovered = isHoveredRef.current
      
      ctx.clearRect(0, 0, width, height)
      time += 0.05
      const centerX = width / 2
      const centerY = height / 2
      const radius = size / 2 - 4

      // 眨眼逻辑
      const now = Date.now()
      if (blinkRef.state === 'open' && now > blinkRef.nextBlinkTime) {
        blinkRef.state = 'closing'
      }
      if (blinkRef.state === 'closing') {
        blinkRef.progress -= 0.25
        if (blinkRef.progress <= 0) {
          blinkRef.progress = 0
          blinkRef.state = 'opening'
        }
      } else if (blinkRef.state === 'opening') {
        blinkRef.progress += 0.12
        if (blinkRef.progress >= 1) {
          blinkRef.progress = 1
          blinkRef.state = 'open'
          if (!blinkRef.isDoubleBlink && Math.random() > 0.8) {
            blinkRef.isDoubleBlink = true
            blinkRef.nextBlinkTime = now + 100
          } else {
            blinkRef.isDoubleBlink = false
            blinkRef.nextBlinkTime = now + Math.random() * 4000 + 2000
          }
        }
      }

      // 绘制主体圆脸
      ctx.save()
      ctx.translate(centerX, centerY)
      
      // 悬停时添加光晕
      if (hovered) {
        ctx.shadowColor = 'rgba(102, 126, 234, 0.5)'
        ctx.shadowBlur = 20
      }
      
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fillStyle = hovered ? '#F7FAFC' : '#FFFFFF'
      ctx.fill()
      ctx.lineWidth = hovered ? 3 : 2.5
      ctx.strokeStyle = hovered ? '#667eea' : '#000'
      ctx.stroke()
      
      ctx.shadowColor = 'transparent'
      ctx.shadowBlur = 0

      // 计算眼睛应该看向的方向（基于全页面鼠标位置）
      let eyeOffsetX = 0
      let eyeOffsetY = 0
      
      if (mousePositionRef.current.isTracking) {
        const mouseX = mousePositionRef.current.x
        const mouseY = mousePositionRef.current.y
        const distance = Math.sqrt(mouseX * mouseX + mouseY * mouseY)
        
        // 眼睛可移动的最大范围
        const maxEyeMovement = radius * 0.15
        
        if (distance > 10) { // 添加最小距离阈值，避免在中心时抖动
          // 计算角度
          const angle = Math.atan2(mouseY, mouseX)
          
          // 根据距离调整眼睛移动幅度
          // 使用更平滑的距离映射函数
          const minDistance = 50  // 最小有效距离
          const maxDistance = 800 // 最大有效距离
          const clampedDistance = Math.max(minDistance, Math.min(distance, maxDistance))
          const distanceFactor = (clampedDistance - minDistance) / (maxDistance - minDistance)
          
          // 计算眼睛偏移量
          const movementAmount = maxEyeMovement * (0.3 + distanceFactor * 0.7) // 至少移动30%
          eyeOffsetX = Math.cos(angle) * movementAmount
          eyeOffsetY = Math.sin(angle) * movementAmount
        }
      }

      // 绘制眼睛
      const eyeY = -radius * 0.15  // 向上移动
      const eyeSpacing = radius * 0.3
      const eyeSize = hovered ? 1.15 : 1
      
      const drawEye = (x: number) => {
        ctx.save()
        ctx.translate(x + eyeOffsetX, eyeY + eyeOffsetY)
        ctx.scale(eyeSize, blinkRef.progress * eyeSize)
        ctx.beginPath()
        ctx.ellipse(0, 0, radius * 0.12, radius * 0.18, 0, 0, Math.PI * 2)  // 眼睛长度稍短（从 0.22 改为 0.18）
        ctx.fillStyle = hovered ? '#667eea' : '#000'
        ctx.fill()
        
        // 添加高光
        if (blinkRef.progress > 0.5) {
          ctx.beginPath()
          ctx.ellipse(-radius * 0.04, -radius * 0.06, radius * 0.04, radius * 0.05, 0, 0, Math.PI * 2)  // 高光也相应调整
          ctx.fillStyle = 'rgba(255, 255, 255, 0.7)'
          ctx.fill()
        }
        
        ctx.restore()
      }
      
      drawEye(-eyeSpacing)
      drawEye(eyeSpacing)

      // 绘制微笑（悬停时）
      if (hovered) {
        ctx.beginPath()
        ctx.arc(0, radius * 0.25, radius * 0.35, 0.3, Math.PI - 0.3)
        ctx.strokeStyle = '#667eea'
        ctx.lineWidth = 2.5
        ctx.lineCap = 'round'
        ctx.stroke()
        
        // 添加腮红
        ctx.fillStyle = 'rgba(255, 182, 193, 0.3)'
        ctx.beginPath()
        ctx.ellipse(-radius * 0.45, radius * 0.1, radius * 0.15, radius * 0.12, 0, 0, Math.PI * 2)
        ctx.fill()
        ctx.beginPath()
        ctx.ellipse(radius * 0.45, radius * 0.1, radius * 0.15, radius * 0.12, 0, 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.restore()

      animationFrameRef.current = requestAnimationFrame(draw)
    }

    draw()
    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current)
    }
  }, [size])

  return (
    <div 
      ref={containerRef}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={onClick}
      style={{ 
        width: size * 1.5, 
        height: size * 2, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        cursor: 'pointer',
        userSelect: 'none',
        transition: 'transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
        transform: isHovered ? 'scale(1.08)' : 'scale(1)',
      }}
    >
      <canvas ref={canvasRef} style={{ width: size * 1.5, height: size * 2 }} />
    </div>
  )
}

export default WelcomeAIAvatar

import React, { useEffect, useRef } from 'react'

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  life: number
  color: string
  size: number
  gravity: number
}

interface Rocket {
  x: number
  y: number
  targetY: number
  vy: number
  color: string
  exploded: boolean
  trail: Array<{ x: number; y: number; opacity: number }>
}

interface FireworksProps {
  active: boolean
  extraTrigger: number
  onComplete?: () => void
}

const Fireworks: React.FC<FireworksProps> = ({ active, extraTrigger, onComplete }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const particlesRef = useRef<Particle[]>([])
  const rocketsRef = useRef<Rocket[]>([])
  const animationFrameRef = useRef<number>()
  const startTimeRef = useRef<number>(0)
  const isInitializedRef = useRef(false)
  const timeoutsRef = useRef<NodeJS.Timeout[]>([])

  const colors = [
    '#667eea', '#764ba2', '#f093fb', '#4facfe',
    '#43e97b', '#fa709a', '#fee140', '#30cfd0',
    '#a8edea', '#fed6e3', '#ff9a9e', '#fad0c4'
  ]

  // 创建爆炸效果
  const createExplosion = (x: number, y: number, color: string) => {
    const particleCount = 80
    
    for (let i = 0; i < particleCount; i++) {
      const angle = (Math.PI * 2 * i) / particleCount + (Math.random() - 0.5) * 0.5
      const speed = 2 + Math.random() * 4
      
      particlesRef.current.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 1,
        color,
        size: 2 + Math.random() * 3,
        gravity: 0.05 + Math.random() * 0.05
      })
    }
  }

  // 发射单个火箭
  const launchSingleRocket = () => {
    const canvas = canvasRef.current
    if (!canvas) return

    const color = colors[Math.floor(Math.random() * colors.length)]
    const startX = canvas.width * (0.2 + Math.random() * 0.6)
    const targetY = canvas.height * (0.2 + Math.random() * 0.2)
    
    rocketsRef.current.push({
      x: startX,
      y: canvas.height,
      targetY,
      vy: -8 - Math.random() * 4,
      color,
      exploded: false,
      trail: []
    })
  }

  // 监听额外触发（烟花进行中的点击）
  useEffect(() => {
    if (extraTrigger === 0 || !isInitializedRef.current) return
    
    // 发射一个额外的烟花
    launchSingleRocket()
  }, [extraTrigger])

  useEffect(() => {
    if (!active) {
      isInitializedRef.current = false
      return
    }

    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // 设置canvas尺寸
    const resizeCanvas = () => {
      canvas.width = window.innerWidth
      canvas.height = window.innerHeight
    }
    resizeCanvas()
    window.addEventListener('resize', resizeCanvas)

    // 只在第一次激活时初始化
    if (!isInitializedRef.current) {
      particlesRef.current = []
      rocketsRef.current = []
      startTimeRef.current = Date.now()
      isInitializedRef.current = true

      // 清理之前的定时器
      timeoutsRef.current.forEach(timeout => clearTimeout(timeout))
      timeoutsRef.current = []

      // 发射5个烟花，带有时间间隔
      const fireworkCount = 5
      
      for (let i = 0; i < fireworkCount; i++) {
        const timeout = setTimeout(() => {
          launchSingleRocket()
        }, i * 400)
        
        timeoutsRef.current.push(timeout)
      }
    }

    // 动画循环
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // 更新和绘制火箭
      rocketsRef.current.forEach((rocket, index) => {
        if (!rocket.exploded) {
          // 更新火箭位置
          rocket.y += rocket.vy
          rocket.vy += 0.15 // 重力减速
          
          // 添加尾迹
          rocket.trail.push({ x: rocket.x, y: rocket.y, opacity: 1 })
          if (rocket.trail.length > 15) {
            rocket.trail.shift()
          }
          
          // 更新尾迹透明度
          rocket.trail.forEach((point, i) => {
            point.opacity = i / rocket.trail.length
          })
          
          // 绘制尾迹
          rocket.trail.forEach((point) => {
            ctx.save()
            ctx.globalAlpha = point.opacity * 0.8
            ctx.fillStyle = rocket.color
            ctx.shadowBlur = 10
            ctx.shadowColor = rocket.color
            ctx.beginPath()
            ctx.arc(point.x, point.y, 2, 0, Math.PI * 2)
            ctx.fill()
            ctx.restore()
          })
          
          // 绘制火箭头部
          ctx.save()
          ctx.fillStyle = '#ffffff'
          ctx.shadowBlur = 15
          ctx.shadowColor = rocket.color
          ctx.beginPath()
          ctx.arc(rocket.x, rocket.y, 3, 0, Math.PI * 2)
          ctx.fill()
          ctx.restore()
          
          // 检查是否到达目标高度或开始下落
          if (rocket.y <= rocket.targetY || rocket.vy > 0) {
            rocket.exploded = true
            createExplosion(rocket.x, rocket.y, rocket.color)
            rocketsRef.current.splice(index, 1)
          }
        }
      })

      // 更新和绘制爆炸粒子
      particlesRef.current.forEach((particle, index) => {
        // 更新位置
        particle.x += particle.vx
        particle.y += particle.vy
        
        // 应用重力
        particle.vy += particle.gravity
        
        // 空气阻力
        particle.vx *= 0.99
        particle.vy *= 0.99
        
        // 生命值衰减
        particle.life -= 0.008
        
        // 绘制粒子
        if (particle.life > 0) {
          ctx.save()
          ctx.globalAlpha = particle.life
          ctx.fillStyle = particle.color
          ctx.shadowBlur = 10
          ctx.shadowColor = particle.color
          
          ctx.beginPath()
          ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2)
          ctx.fill()
          
          // 添加拖尾效果
          ctx.globalAlpha = particle.life * 0.5
          ctx.beginPath()
          ctx.arc(
            particle.x - particle.vx * 2,
            particle.y - particle.vy * 2,
            particle.size * 0.5,
            0,
            Math.PI * 2
          )
          ctx.fill()
          
          ctx.restore()
        } else {
          particlesRef.current.splice(index, 1)
        }
      })

      // 检查是否所有效果都结束了
      const elapsed = Date.now() - startTimeRef.current
      if (rocketsRef.current.length === 0 && particlesRef.current.length === 0 && elapsed > 3000) {
        onComplete?.()
        return
      }

      animationFrameRef.current = requestAnimationFrame(animate)
    }

    animate()

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current)
      }
      // 清理所有定时器
      timeoutsRef.current.forEach(timeout => clearTimeout(timeout))
      window.removeEventListener('resize', resizeCanvas)
    }
  }, [active, onComplete])

  if (!active) return null

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 9999,
      }}
    />
  )
}

export default Fireworks

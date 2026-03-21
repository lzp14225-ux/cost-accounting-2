import React, { useEffect, useRef, useState } from 'react'

interface AIAvatarProps {
  size?: number
  isTyping?: boolean
  isLatest?: boolean
  onClick?: () => void
}

const AIAvatar: React.FC<AIAvatarProps> = ({ 
  size = 48, 
  isTyping = false, 
  isLatest = false, 
  onClick 
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationFrameRef = useRef<number>()
  
  const [clickCount, setClickCount] = useState(0)
  const [isAngry, setIsAngry] = useState(false)
  
  const isAngryRef = useRef(false)
  const isTypingRef = useRef(isTyping)
  const isLatestRef = useRef(isLatest)
  const angryTimerRef = useRef<NodeJS.Timeout | null>(null)
  const impactRef = useRef(0)
  const particles = useRef<{x: number, y: number, opacity: number, speed: number, text: string}[]>([])

  // --- 眨眼优化：引入状态机 Ref ---
  const blinkRef = useRef({
    state: 'open', // open, closing, opening
    progress: 1,   // 0 (闭合) 到 1 (睁开)
    nextBlinkTime: Date.now() + Math.random() * 5000 + 2000,
    isDoubleBlink: false
  })

  useEffect(() => { isAngryRef.current = isAngry }, [isAngry])
  useEffect(() => { isTypingRef.current = isTyping }, [isTyping])
  useEffect(() => { isLatestRef.current = isLatest }, [isLatest])

  const handleClick = () => {
    // 如果不是最新消息，或者正在打字，则不响应点击
    if (!isLatest || isTyping) return 
    onClick?.()
    impactRef.current = 6 
    setClickCount(prev => {
      const nextCount = prev + 1
      if (nextCount >= 3) {
        setIsAngry(true)
        if (angryTimerRef.current) clearTimeout(angryTimerRef.current)
        angryTimerRef.current = setTimeout(() => {
          setIsAngry(false)
          setClickCount(0)
        }, 3000)
      }
      return nextCount
    })
  }

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

    const mathSymbols = ['∑', 'π', '∞', '√', '∫', '∆', 'f(x)', 'y=ax+b']
    let time = 0

    const draw = () => {
      const angry = isAngryRef.current
      const typing = isTypingRef.current
      const latest = isLatestRef.current

      ctx.clearRect(0, 0, width, height)
      time += 0.05
      const centerX = width / 2
      const centerY = height / 2
      const radius = size / 2 - 4

      // --- 1. 粒子逻辑 (保持不变) ---
      if ((typing || angry) && Math.random() > 0.9) {
        particles.current.push({
          x: centerX + (Math.random() - 0.5) * size,
          y: centerY - radius - 5,
          opacity: 1,
          speed: 0.5 + Math.random(),
          text: angry ? (Math.random() > 0.5 ? '💢' : '!') : mathSymbols[Math.floor(Math.random() * mathSymbols.length)]
        })
      }
      particles.current.forEach((p, i) => {
        p.y -= p.speed; p.opacity -= 0.02
        ctx.fillStyle = angry ? `rgba(211, 47, 47, ${p.opacity})` : `rgba(0, 0, 0, ${p.opacity})`
        ctx.font = 'bold 10px Arial'
        ctx.fillText(p.text, p.x, p.y)
        if (p.opacity <= 0) particles.current.splice(i, 1)
      })

      // --- 2. 震动计算 (保持不变) ---
      impactRef.current *= 0.85
      if (impactRef.current < 0.1) impactRef.current = 0
      const impactShake = Math.sin(time * 25) * impactRef.current
      const autoShake = angry ? Math.sin(time * 40) * 1.5 : (typing ? Math.sin(time * 10) * 0.5 : 0)
      const totalShake = autoShake + impactShake

      // --- 3. 眨眼逻辑优化 ---
      const b = blinkRef.current
      if (latest && !angry) {
        const now = Date.now()
        if (b.state === 'open' && now > b.nextBlinkTime) {
          b.state = 'closing'
        }
        if (b.state === 'closing') {
          b.progress -= 0.25 // 闭合速度快
          if (b.progress <= 0) {
            b.progress = 0
            b.state = 'opening'
          }
        } else if (b.state === 'opening') {
          b.progress += 0.12 // 睁开速度慢，更自然
          if (b.progress >= 1) {
            b.progress = 1
            b.state = 'open'
            // 判定是否双闪
            if (!b.isDoubleBlink && Math.random() > 0.8) {
              b.isDoubleBlink = true
              b.nextBlinkTime = now + 100 // 很快再次眨眼
            } else {
              b.isDoubleBlink = false
              b.nextBlinkTime = now + Math.random() * 4000 + 2000
            }
          }
        }
      } else {
        b.progress = 1 // 生气或非活跃时不眨眼
      }

      // --- 4. 绘制主体圆脸 (保持不变) ---
      ctx.save()
      ctx.translate(centerX + totalShake, centerY)
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fillStyle = angry ? '#FFEBEE' : '#FFFFFF'
      ctx.fill()
      ctx.lineWidth = 2.5
      ctx.strokeStyle = angry ? '#D32F2F' : '#000'
      ctx.stroke()

      // --- 5. 绘制眉毛 (保持不变) ---
      if (angry) {
        ctx.strokeStyle = '#D32F2F'; ctx.lineWidth = 2.5; ctx.lineCap = 'round'
        ctx.beginPath(); ctx.moveTo(-radius * 0.45, -radius * 0.35); ctx.lineTo(-radius * 0.15, -radius * 0.15); ctx.stroke()
        ctx.beginPath(); ctx.moveTo(radius * 0.45, -radius * 0.35); ctx.lineTo(radius * 0.15, -radius * 0.15); ctx.stroke()
      }

      // --- 6. 绘制眼睛 (使用优化后的进度) ---
      const eyeY = angry ? -radius * 0.05 : (typing ? radius * 0.15 : -radius * 0.05)
      const eyeSpacing = radius * 0.3
      const drawEye = (x: number) => {
        ctx.save()
        ctx.translate(x, eyeY)
        // 使用 b.progress 替代原来的 Math.sin 判定
        ctx.scale(1, b.progress)
        ctx.beginPath()
        ctx.ellipse(0, 0, radius * 0.12, radius * 0.22, 0, 0, Math.PI * 2)
        ctx.fillStyle = angry ? '#D32F2F' : '#000'
        ctx.fill()
        ctx.restore()
      }
      drawEye(-eyeSpacing)
      drawEye(eyeSpacing)
      ctx.restore()

      // --- 7. 绘制图纸 (保持不变) ---
      if (typing && !angry) {
        const paperY = centerY + radius * 0.6
        ctx.save()
        ctx.translate(centerX, paperY)
        ctx.fillStyle = '#FFF'; ctx.strokeStyle = '#000'; ctx.lineWidth = 1.5
        ctx.beginPath(); ctx.rect(-radius * 0.7, 0, radius * 1.4, radius * 0.9); ctx.fill(); ctx.stroke()
        ctx.beginPath(); ctx.lineWidth = 1
        for(let i=1; i<=3; i++) {
          ctx.moveTo(-radius * 0.5, i * 6); ctx.lineTo(radius * 0.4, i * 6)
        }
        ctx.stroke()
        ctx.fillStyle = '#FFF'
        const drawHand = (x: number) => {
          ctx.beginPath(); ctx.arc(x, 5, radius * 0.18, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
        }
        drawHand(-radius * 0.7); drawHand(radius * 0.7)
        ctx.restore()
      }

      animationFrameRef.current = requestAnimationFrame(draw)
    }

    draw()
    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current)
    }
  }, [size]) 

  return (
    <div 
      onClick={handleClick} 
      style={{ 
        width: size * 1.5, height: size * 2, 
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: (isLatest && !isTyping) ? 'pointer' : 'default', 
        userSelect: 'none',
        pointerEvents: (isLatest && !isTyping) ? 'auto' : 'none' // 禁用点击事件
      }}
    >
      <canvas ref={canvasRef} style={{ width: size * 1.5, height: size * 2 }} />
    </div>
  )
}

export default AIAvatar
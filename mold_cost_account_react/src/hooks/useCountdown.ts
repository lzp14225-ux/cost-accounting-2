import { useState, useEffect, useRef } from 'react'

interface UseCountdownOptions {
  initialTime: number // 初始时间（秒）
  onExpired?: () => void // 倒计时结束回调
}

interface UseCountdownReturn {
  timeLeft: number // 剩余时间（秒）
  isExpired: boolean // 是否已过期
  formatTime: (seconds: number) => string // 格式化时间显示
  reset: () => void // 重置倒计时
  pause: () => void // 暂停倒计时
  resume: () => void // 恢复倒计时
}

export const useCountdown = (options: UseCountdownOptions): UseCountdownReturn => {
  const { initialTime, onExpired } = options
  const [timeLeft, setTimeLeft] = useState(initialTime)
  const [isPaused, setIsPaused] = useState(false)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const onExpiredRef = useRef(onExpired)

  // 更新回调引用
  useEffect(() => {
    onExpiredRef.current = onExpired
  }, [onExpired])

  // 格式化时间显示 (MM:SS)
  const formatTime = (seconds: number): string => {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`
  }

  // 重置倒计时
  const reset = () => {
    setTimeLeft(initialTime)
    setIsPaused(false)
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    startCountdown()
  }

  // 暂停倒计时
  const pause = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    setIsPaused(true)
  }

  // 恢复倒计时
  const resume = () => {
    setIsPaused(false)
  }

  // 启动倒计时
  const startCountdown = () => {
    // 清除现有的定时器
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    intervalRef.current = setInterval(() => {
      setTimeLeft((prevTime) => {
        if (prevTime <= 1) {
          // 倒计时结束
          if (intervalRef.current) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
          }
          onExpiredRef.current?.()
          return 0
        }
        return prevTime - 1
      })
    }, 1000)
  }

  // 组件挂载时启动倒计时
  useEffect(() => {
    if (!isPaused && timeLeft > 0) {
      startCountdown()
    } else if (isPaused && intervalRef.current) {
      // 如果暂停，清除定时器
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    // 清理函数
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [isPaused])

  const isExpired = timeLeft <= 0

  return {
    timeLeft,
    isExpired,
    formatTime,
    reset,
    pause,
    resume,
  }
}
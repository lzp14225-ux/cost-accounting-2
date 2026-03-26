import { useEffect, useRef, useState } from 'react'
import type { FC } from 'react'
import { Modal, Form, Input, Button, message, Checkbox } from 'antd'
import { UserOutlined, LockOutlined, EyeInvisibleOutlined, EyeTwoTone } from '@ant-design/icons'
import { AnimatePresence, motion } from 'framer-motion'
import { loginApi, LoginParams } from '../api/auth'
import { AUTH_STORAGE_KEYS } from '../constants/auth'
import './LoginModal.css'

interface LoginModalProps {
  visible: boolean
  onClose: () => void
  onLoginSuccess?: () => void
}

type ActiveField = 'idle' | 'username' | 'password'

type GazeVector = {
  x: number
  y: number
}

const DEFAULT_GAZE: GazeVector = { x: 0, y: 0 }

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

const getGazeVector = (stage: HTMLDivElement | null, target: HTMLDivElement | null): GazeVector => {
  if (!stage || !target) {
    return DEFAULT_GAZE
  }

  const stageRect = stage.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()

  const targetX = targetRect.left + targetRect.width / 2
  const targetY = targetRect.top + targetRect.height / 2
  const stageX = stageRect.left + stageRect.width / 2
  const stageY = stageRect.top + stageRect.height / 2

  return {
    x: clamp(((targetX - stageX) / stageRect.width) * 18, -6, 6),
    y: clamp(((targetY - stageY) / stageRect.height) * 12, -4, 5),
  }
}

const getPointerGaze = (stage: HTMLDivElement | null, clientX: number, clientY: number): GazeVector => {
  if (!stage) {
    return DEFAULT_GAZE
  }

  const stageRect = stage.getBoundingClientRect()
  const stageX = stageRect.left + stageRect.width / 2
  const stageY = stageRect.top + stageRect.height / 2

  return {
    x: clamp(((clientX - stageX) / stageRect.width) * 18, -6, 6),
    y: clamp(((clientY - stageY) / stageRect.height) * 12, -4, 5),
  }
}

const FrontCatLoader: FC<{ gaze: GazeVector }> = ({ gaze }) => (
  <div className="loader loader--front">
    <div className="wrapper">
      <div className="catContainer">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 733 673"
          className="catbody"
        >
          <path
            fill="#212121"
            d="M111.002 139.5C270.502 -24.5001 471.503 2.4997 621.002 139.5C770.501 276.5 768.504 627.5 621.002 649.5C473.5 671.5 246 687.5 111.002 649.5C-23.9964 611.5 -48.4982 303.5 111.002 139.5Z"
          />
          <path fill="#212121" d="M184 9L270.603 159H97.3975L184 9Z" />
          <path fill="#212121" d="M541 0L627.603 150H454.397L541 0Z" />
          <ellipse cx="270" cy="314" rx="50" ry="58" fill="#FFFFFF" />
          <ellipse cx="458" cy="314" rx="50" ry="58" fill="#FFFFFF" />
          <motion.g
            animate={{ x: gaze.x * 7.4, y: gaze.y * 6.2 }}
            transition={{ type: 'spring', stiffness: 260, damping: 18 }}
          >
            <circle cx="270" cy="314" r="38" fill="#212121" />
            <circle cx="458" cy="314" r="38" fill="#212121" />
          </motion.g>
          <circle cx="284" cy="299" r="6.2" fill="#FFFFFF" opacity="0.82" />
          <circle cx="472" cy="299" r="6.2" fill="#FFFFFF" opacity="0.82" />
        </svg>

        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 158 564"
          className="tail"
        >
          <path
            fill="#191919"
            d="M5.97602 76.066C-11.1099 41.6747 12.9018 0 51.3036 0V0C71.5336 0 89.8636 12.2558 97.2565 31.0866C173.697 225.792 180.478 345.852 97.0691 536.666C89.7636 553.378 73.0672 564 54.8273 564V564C16.9427 564 -5.4224 521.149 13.0712 488.085C90.2225 350.15 87.9612 241.089 5.97602 76.066Z"
          />
        </svg>

        <div className="text">
          <span className="bigzzz">Z</span>
          <span className="zzz">Z</span>
        </div>
      </div>

      <div className="wallContainer">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 500 126"
          className="wall"
        >
          <line strokeWidth="6" stroke="#7C7C7C" y2="3" x2="450" y1="3" x1="50" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="85" x2="400" y1="85" x1="100" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="122" x2="375" y1="122" x1="125" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="500" y1="43" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="1.99391" x2="115.5" y1="43.0061" x1="115.5" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.00002" x2="189" y1="43.0122" x1="189" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.00612" x2="262.5" y1="43.0183" x1="262.5" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.01222" x2="336" y1="43.0244" x1="336" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.01833" x2="409.5" y1="43.0305" x1="409.5" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="153" y1="84.0122" x1="153" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="228" y1="84.0122" x1="228" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="303" y1="84.0122" x1="303" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="378" y1="84.0122" x1="378" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="84" x2="192" y1="125.012" x1="192" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="84" x2="267" y1="125.012" x1="267" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="84" x2="342" y1="125.012" x1="342" />
        </svg>
      </div>
    </div>
  </div>
)

const SleepyCatLoader: FC = () => (
  <div className="loader">
    <div className="wrapper">
      <div className="catContainer">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 733 673"
          className="catbody"
        >
          <path
            fill="#212121"
            d="M111.002 139.5C270.502 -24.5001 471.503 2.4997 621.002 139.5C770.501 276.5 768.504 627.5 621.002 649.5C473.5 671.5 246 687.5 111.002 649.5C-23.9964 611.5 -48.4982 303.5 111.002 139.5Z"
          />
          <path
            fill="#212121"
            d="M184 9L270.603 159H97.3975L184 9Z"
          />
          <path
            fill="#212121"
            d="M541 0L627.603 150H454.397L541 0Z"
          />
        </svg>

        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 158 564"
          className="tail"
        >
          <path
            fill="#191919"
            d="M5.97602 76.066C-11.1099 41.6747 12.9018 0 51.3036 0V0C71.5336 0 89.8636 12.2558 97.2565 31.0866C173.697 225.792 180.478 345.852 97.0691 536.666C89.7636 553.378 73.0672 564 54.8273 564V564C16.9427 564 -5.4224 521.149 13.0712 488.085C90.2225 350.15 87.9612 241.089 5.97602 76.066Z"
          />
        </svg>

        <div className="text">
          <span className="bigzzz">Z</span>
          <span className="zzz">Z</span>
        </div>
      </div>

      <div className="wallContainer">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 500 126"
          className="wall"
        >
          <line strokeWidth="6" stroke="#7C7C7C" y2="3" x2="450" y1="3" x1="50" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="85" x2="400" y1="85" x1="100" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="122" x2="375" y1="122" x1="125" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="500" y1="43" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="1.99391" x2="115.5" y1="43.0061" x1="115.5" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.00002" x2="189" y1="43.0122" x1="189" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.00612" x2="262.5" y1="43.0183" x1="262.5" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.01222" x2="336" y1="43.0244" x1="336" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="2.01833" x2="409.5" y1="43.0305" x1="409.5" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="153" y1="84.0122" x1="153" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="228" y1="84.0122" x1="228" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="303" y1="84.0122" x1="303" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="43" x2="378" y1="84.0122" x1="378" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="84" x2="192" y1="125.012" x1="192" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="84" x2="267" y1="125.012" x1="267" />
          <line strokeWidth="6" stroke="#7C7C7C" y2="84" x2="342" y1="125.012" x1="342" />
        </svg>
      </div>
    </div>
  </div>
)

const LoginModal: FC<LoginModalProps> = ({ visible, onClose, onLoginSuccess }) => {
  const [loading, setLoading] = useState(false)
  const [activeField, setActiveField] = useState<ActiveField>('idle')
  const [gaze, setGaze] = useState<GazeVector>(DEFAULT_GAZE)
  const [form] = Form.useForm()
  const heroRef = useRef<HTMLDivElement>(null)
  const usernameAnchorRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!visible) {
      setActiveField('idle')
      setGaze(DEFAULT_GAZE)
      return
    }

    const rememberedUsername = localStorage.getItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME)
    const rememberedPassword = localStorage.getItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD)

    if (rememberedUsername) {
      form.setFieldsValue({
        username: rememberedUsername,
        password: rememberedPassword,
        remember: true,
      })
    }
  }, [visible, form])

  useEffect(() => {
    if (!visible || activeField !== 'username') {
      setGaze(DEFAULT_GAZE)
      return
    }

    const updateGaze = () => {
      setGaze(getGazeVector(heroRef.current, usernameAnchorRef.current))
    }

    const frameId = window.requestAnimationFrame(updateGaze)
    window.addEventListener('resize', updateGaze)

    return () => {
      window.cancelAnimationFrame(frameId)
      window.removeEventListener('resize', updateGaze)
    }
  }, [activeField, visible])

  useEffect(() => {
    if (!visible || activeField === 'password') {
      return
    }

    const handlePointerMove = (event: MouseEvent) => {
      setGaze(getPointerGaze(heroRef.current, event.clientX, event.clientY))
    }

    window.addEventListener('mousemove', handlePointerMove)

    return () => {
      window.removeEventListener('mousemove', handlePointerMove)
    }
  }, [activeField, visible])

  const handleLogin = async (values: LoginParams & { remember?: boolean }) => {
    setLoading(true)

    try {
      const response = await loginApi({
        username: values.username,
        password: values.password,
      })

      if (response.success) {
        if (response.token) {
          localStorage.setItem(AUTH_STORAGE_KEYS.TOKEN, response.token)
        }

        localStorage.setItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN, 'true')
        localStorage.setItem(
          AUTH_STORAGE_KEYS.USER_INFO,
          JSON.stringify({
            userId: response.user_info.user_id,
            username: response.user_info.username,
            realName: response.user_info.real_name,
            email: response.user_info.email,
            role: response.user_info.role,
            department: response.user_info.department,
            isActive: response.user_info.is_active,
            createdAt: response.user_info.created_at,
            lastLoginAt: response.user_info.last_login_at,
            loginTime: new Date().toISOString(),
          })
        )

        if (values.remember) {
          localStorage.setItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME, values.username)
          localStorage.setItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD, values.password)
        } else {
          localStorage.removeItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME)
          localStorage.removeItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD)
        }

        message.success(`登录成功，欢迎回来 ${response.user_info.real_name}`)
        form.resetFields()
        onClose()
        onLoginSuccess?.()
      } else {
        message.error(response.message || '登录失败，请重试')
        form.setFieldsValue({ password: '' })
      }
    } catch (error: any) {
      console.error('登录错误:', error)
      message.error(error.message || '登录失败，请检查网络连接')
      form.setFieldsValue({ password: '' })
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = () => {
    form.resetFields()
    setActiveField('idle')
    setGaze(DEFAULT_GAZE)
    onClose()
  }

  return (
    <Modal
      title={null}
      open={visible}
      onCancel={handleCancel}
      footer={null}
      width={780}
      centered
      destroyOnHidden
      maskClosable={!loading}
      className="login-modal"
      styles={{
        content: { padding: 0, overflow: 'hidden', borderRadius: 30 },
        body: { padding: 0 },
      }}
    >
      <div className="login-modal__shell">
        <motion.div
          ref={heroRef}
          className="login-modal__hero"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.35 }}
        >
          <div className="login-modal__cat-scene">
            <AnimatePresence mode="sync" initial={false}>
              {activeField === 'password' ? (
                <motion.div
                  key="sleepy-cat"
                  className="login-modal__cat-layer"
                  initial={{ opacity: 0, rotateY: -70, scale: 0.9, y: 10 }}
                  animate={{ opacity: 1, rotateY: 0, scale: 1, y: 0 }}
                  exit={{ opacity: 0, rotateY: 70, scale: 0.92, y: -6 }}
                  transition={{ duration: 0.48, ease: [0.22, 1, 0.36, 1] }}
                >
                  <SleepyCatLoader />
                </motion.div>
              ) : (
                <motion.div
                  key="front-cat"
                  className="login-modal__cat-layer"
                  initial={{ opacity: 0, rotateY: 70, scale: 0.9, y: 10 }}
                  animate={{ opacity: 1, rotateY: 0, scale: 1, y: 0 }}
                  exit={{ opacity: 0, rotateY: -70, scale: 0.92, y: -6 }}
                  transition={{ duration: 0.48, ease: [0.22, 1, 0.36, 1] }}
                >
                  <FrontCatLoader gaze={gaze} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>

        <motion.div
          className="login-modal__form-wrap"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.35, delay: 0.05 }}
        >
          <div className="login-modal__form-head">
            <span className="login-modal__tag">账号验证</span>
            <h3>欢迎回来</h3>
            <p>输入账号和密码后即可继续使用完整功能。</p>
          </div>

          <Form
            form={form}
            name="login"
            onFinish={handleLogin}
            autoComplete="off"
            layout="vertical"
            requiredMark={false}
          >
            <div ref={usernameAnchorRef}>
              <Form.Item
                className="login-modal__item"
                label="用户名"
                name="username"
                rules={[
                  { required: true, message: '请输入用户名' },
                  { min: 2, message: '用户名至少 2 个字符' },
                ]}
              >
                <Input
                  prefix={<UserOutlined />}
                  placeholder="请输入用户名"
                  size="large"
                  autoComplete="username"
                  className="login-modal__input"
                  onFocus={() => setActiveField('username')}
                  onBlur={() => setActiveField('idle')}
                />
              </Form.Item>
            </div>

            <Form.Item
              className="login-modal__item"
              label="密码"
              name="password"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 6, message: '密码至少 6 个字符' },
              ]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                size="large"
                autoComplete="current-password"
                className="login-modal__input"
                iconRender={(isVisible) => (isVisible ? <EyeTwoTone /> : <EyeInvisibleOutlined />)}
                onFocus={() => setActiveField('password')}
                onBlur={() => setActiveField('idle')}
              />
            </Form.Item>

            <Form.Item name="remember" valuePropName="checked" style={{ marginBottom: 20 }}>
              <Checkbox className="login-modal__checkbox">记住密码</Checkbox>
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                block
                size="large"
                className="login-modal__submit"
              >
                {loading ? '登录中...' : '登录'}
              </Button>
            </Form.Item>
          </Form>
        </motion.div>
      </div>
    </Modal>
  )
}

export default LoginModal

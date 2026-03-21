import React, { useState, useEffect } from 'react'
import { Modal, Form, Input, Button, message, Checkbox } from 'antd'
import { UserOutlined, LockOutlined, EyeInvisibleOutlined, EyeTwoTone } from '@ant-design/icons'
import { loginApi, LoginParams } from '../api/auth'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

interface LoginModalProps {
  visible: boolean
  onClose: () => void
  onLoginSuccess?: () => void
}

const LoginModal: React.FC<LoginModalProps> = ({ visible, onClose, onLoginSuccess }) => {
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  // 记住密码功能
  useEffect(() => {
    if (visible) {
      const rememberedUsername = localStorage.getItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME)
      const rememberedPassword = localStorage.getItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD)
      if (rememberedUsername) {
        form.setFieldsValue({
          username: rememberedUsername,
          password: rememberedPassword,
          remember: true,
        })
      }
    }
  }, [visible, form])

  const handleLogin = async (values: LoginParams & { remember?: boolean }) => {
    setLoading(true)
    try {
      const response = await loginApi({
        username: values.username,
        password: values.password,
      })
      
      if (response.success) {
        // 保存 token
        if (response.token) {
          localStorage.setItem(AUTH_STORAGE_KEYS.TOKEN, response.token)
        }
        
        // 保存登录状态
        localStorage.setItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN, 'true')
        localStorage.setItem(AUTH_STORAGE_KEYS.USER_INFO, JSON.stringify({
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
        }))
        
        // 记住密码
        if (values.remember) {
          localStorage.setItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME, values.username)
          localStorage.setItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD, values.password)
        } else {
          localStorage.removeItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME)
          localStorage.removeItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD)
        }
        
        message.success(`登录成功，欢迎回来 ${response.user_info.real_name}！`)
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
    onClose()
  }

  return (
    <Modal
      title={null}
      open={visible}
      onCancel={handleCancel}
      footer={null}
      width={420}
      centered
      destroyOnHidden
      styles={{
        content: { padding: 0 },
        body: { padding: '40px 32px 32px' }
      }}
    >
      <div style={{ textAlign: 'center', marginBottom: 32 }}>
        <div style={{
          fontSize: 24,
          fontWeight: 600,
          color: '#1a1a1a',
          marginBottom: 8,
        }}>
          用户登录
        </div>
        <div style={{ fontSize: 14, color: '#8c8c8c' }}>
          登录以体验全部功能
        </div>
      </div>

      <Form
        form={form}
        name="login"
        onFinish={handleLogin}
        autoComplete="off"
        layout="vertical"
      >
        <Form.Item
          label="用户名"
          name="username"
          rules={[
            { required: true, message: '请输入用户名' },
            { min: 2, message: '用户名至少2个字符' }
          ]}
        >
          <Input
            prefix={<UserOutlined style={{ color: '#bfbfbf' }} />}
            placeholder="请输入用户名"
            size="large"
            style={{ height: 44, borderRadius: 8 }}
          />
        </Form.Item>

        <Form.Item
          label="密码"
          name="password"
          rules={[
            { required: true, message: '请输入密码' },
            { min: 6, message: '密码至少6个字符' }
          ]}
        >
          <Input.Password
            prefix={<LockOutlined style={{ color: '#bfbfbf' }} />}
            placeholder="请输入密码"
            size="large"
            iconRender={(visible) => (visible ? <EyeTwoTone /> : <EyeInvisibleOutlined />)}
            style={{ height: 44, borderRadius: 8 }}
          />
        </Form.Item>

        <Form.Item name="remember" valuePropName="checked" style={{ marginBottom: 24 }}>
          <Checkbox>记住密码</Checkbox>
        </Form.Item>

        <Form.Item style={{ marginBottom: 0 }}>
          <Button
            type="primary"
            htmlType="submit"
            loading={loading}
            block
            size="large"
            style={{
              height: 44,
              borderRadius: 8,
              fontSize: 16,
              fontWeight: 500,
            }}
          >
            {loading ? '登录中...' : '登录'}
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default LoginModal

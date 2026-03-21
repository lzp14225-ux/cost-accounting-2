import React, { useState, useEffect } from 'react'
import { Form, Input, Button, Typography, Flex, message, Checkbox, Row, Col } from 'antd'
import { UserOutlined, LockOutlined, CloudUploadOutlined, EyeInvisibleOutlined, EyeTwoTone, RocketOutlined, SafetyOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { loginApi, LoginParams } from '../api/auth'
import { getValidToken } from '../utils/auth'
import { AUTH_STORAGE_KEYS } from '../constants/auth'

const { Title, Text, Paragraph } = Typography

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()

  // 检查是否已经登录
  useEffect(() => {
    const isLoggedIn = localStorage.getItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN) === 'true'
    const userInfo = localStorage.getItem(AUTH_STORAGE_KEYS.USER_INFO)
    const token = getValidToken()
    
    // 只有当三个条件都满足时才认为已登录
    if (isLoggedIn && userInfo && token) {
      try {
        const user = JSON.parse(userInfo)
        if (user.userId) {
          navigate('/app')
        }
      } catch (error) {
        // 如果用户信息解析失败，清除相关数据
        localStorage.removeItem(AUTH_STORAGE_KEYS.IS_LOGGED_IN)
        localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
      }
    }
  }, [navigate])

  // 记住密码功能
  useEffect(() => {
    const rememberedUsername = localStorage.getItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME)
    const rememberedPassword = localStorage.getItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD)
    if (rememberedUsername) {
      form.setFieldsValue({
        username: rememberedUsername,
        password: rememberedPassword,
        remember: true,
      })
    }
  }, [form])

  const handleLogin = async (values: LoginParams & { remember?: boolean }) => {
    setLoading(true)
    try {
      // 调用真实的登录API
      const response = await loginApi({
        username: values.username,
        password: values.password,
      })
      
      if (response.success) {
        // 保存 token 到 localStorage（API 中已经保存了，这里确保一致性）
        if (response.token) {
          localStorage.setItem(AUTH_STORAGE_KEYS.TOKEN, response.token)
        }
        
        // 保存登录状态到localStorage
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
        
        // 记住密码功能
        if (values.remember) {
          localStorage.setItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME, values.username)
          localStorage.setItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD, values.password)
        } else {
          localStorage.removeItem(AUTH_STORAGE_KEYS.REMEMBERED_USERNAME)
          localStorage.removeItem(AUTH_STORAGE_KEYS.REMEMBERED_PASSWORD)
        }
        
        message.success(`登录成功，欢迎回来 ${response.user_info.real_name}！`)
        navigate('/app')
      } else {
        message.error(response.message || '登录失败，请重试')
        // 清除密码字段
        form.setFieldsValue({ password: '' })
      }
    } catch (error: any) {
      console.error('登录错误:', error)
      message.error(error.message || '登录失败，请检查网络连接')
      // 清除密码字段
      form.setFieldsValue({ password: '' })
    } finally {
      setLoading(false)
    }
  }

  const features = [
    {
      icon: <RocketOutlined style={{ fontSize: 24, color: '#10a37f' }} />,
      title: '智能分析',
      description: 'AI驱动的成本分析算法，快速准确计算模具制造成本'
    },
    {
      icon: <ThunderboltOutlined style={{ fontSize: 24, color: '#10a37f' }} />,
      title: '高效便捷',
      description: '一键上传CAD文件，自动识别零件特征，秒级生成报价'
    },
    {
      icon: <SafetyOutlined style={{ fontSize: 24, color: '#10a37f' }} />,
      title: '精准可靠',
      description: '基于行业大数据，结合实际生产经验，确保报价准确性'
    }
  ]

  return (
    <div style={{
      height: '100vh',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      display: 'flex',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* 背景装饰元素 */}
      <div style={{
        position: 'absolute',
        top: '-50%',
        left: '-50%',
        width: '200%',
        height: '200%',
        background: 'radial-gradient(circle, rgba(255,255,255,0.05) 1px, transparent 1px)',
        backgroundSize: '60px 60px',
        animation: 'float 25s ease-in-out infinite',
      }} />

      <Row style={{ width: '100%', height: '100%' }}>
        {/* 左侧介绍区域 */}
        <Col xs={0} md={14} lg={15} xl={16} style={{
          background: 'rgba(255, 255, 255, 0.05)',
          backdropFilter: 'blur(10px)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '60px 80px',
          position: 'relative',
        }}>
          {/* 装饰圆形 */}
          <div style={{
            position: 'absolute',
            top: '15%',
            right: '10%',
            width: '200px',
            height: '200px',
            background: 'rgba(255,255,255,0.08)',
            borderRadius: '50%',
            animation: 'pulse 6s ease-in-out infinite',
          }} />
          
          <div style={{
            position: 'absolute',
            bottom: '20%',
            left: '5%',
            width: '150px',
            height: '150px',
            background: 'rgba(255,255,255,0.06)',
            borderRadius: '50%',
            animation: 'pulse 8s ease-in-out infinite reverse',
          }} />

          <div style={{ position: 'relative', zIndex: 1 }}>
            {/* Logo和主标题 */}
            <Flex align="center" gap={20} style={{ marginBottom: 40 }}>
              <div style={{
                width: 80,
                height: 80,
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #10a37f 0%, #0d8f6b 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 8px 32px rgba(16, 163, 127, 0.4)',
                position: 'relative',
              }}>
                <CloudUploadOutlined style={{ fontSize: 40, color: 'white' }} />
                <div style={{
                  position: 'absolute',
                  inset: -3,
                  borderRadius: '50%',
                  background: 'linear-gradient(135deg, #10a37f, #0d8f6b, #10a37f)',
                  zIndex: -1,
                  animation: 'rotate 4s linear infinite',
                }} />
              </div>
              <div>
                <Title level={1} style={{ 
                  margin: 0,
                  color: 'white',
                  fontSize: 42,
                  fontWeight: 800,
                  textShadow: '0 2px 4px rgba(0,0,0,0.3)',
                }}>
                  九章智核
                </Title>
                <Text style={{ 
                  color: 'rgba(255,255,255,0.9)',
                  fontSize: 18,
                  fontWeight: 500,
                }}>
                  Mold Cost Calculation System
                </Text>
              </div>
            </Flex>

            {/* 系统介绍 */}
            <div style={{ marginBottom: 50 }}>
              <Paragraph style={{ 
                color: 'rgba(255,255,255,0.9)',
                fontSize: 18,
                lineHeight: 1.8,
                marginBottom: 20,
              }}>
                专业的模具成本核算解决方案，集成先进的AI算法和丰富的行业经验，
                为您提供快速、准确、可靠的模具制造成本分析和报价服务。
              </Paragraph>
              <Paragraph style={{ 
                color: 'rgba(255,255,255,0.8)',
                fontSize: 16,
                lineHeight: 1.7,
              }}>
                支持多种CAD文件格式，自动识别零件特征，智能计算材料成本、加工费用、
                人工成本等各项费用，帮助企业提高报价效率，降低成本核算误差。
              </Paragraph>
            </div>

            {/* 功能特色 */}
            <div>
              <Title level={3} style={{ 
                color: 'white', 
                marginBottom: 30,
                fontSize: 24,
                fontWeight: 600,
              }}>
                核心优势
              </Title>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                {features.map((feature, index) => (
                  <div key={index} style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 16,
                    padding: '20px 24px',
                    background: 'rgba(255,255,255,0.1)',
                    borderRadius: 16,
                    backdropFilter: 'blur(10px)',
                    border: '1px solid rgba(255,255,255,0.2)',
                    transition: 'all 0.3s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255,255,255,0.15)'
                    e.currentTarget.style.transform = 'translateX(8px)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(255,255,255,0.1)'
                    e.currentTarget.style.transform = 'translateX(0)'
                  }}
                  >
                    <div style={{
                      width: 48,
                      height: 48,
                      borderRadius: 12,
                      background: 'rgba(255,255,255,0.2)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      {feature.icon}
                    </div>
                    <div>
                      <Title level={4} style={{ 
                        color: 'white', 
                        margin: 0, 
                        marginBottom: 8,
                        fontSize: 18,
                        fontWeight: 600,
                      }}>
                        {feature.title}
                      </Title>
                      <Text style={{ 
                        color: 'rgba(255,255,255,0.8)',
                        fontSize: 14,
                        lineHeight: 1.6,
                      }}>
                        {feature.description}
                      </Text>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Col>

        {/* 右侧登录区域 */}
        <Col xs={24} md={10} lg={9} xl={8} style={{
          background: 'rgba(255, 255, 255, 0.95)',
          backdropFilter: 'blur(20px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '40px',
          position: 'relative',
        }}>
          <div style={{
            width: '100%',
            maxWidth: 400,
            position: 'relative',
            zIndex: 1,
          }}>
            {/* 登录标题 */}
            <div style={{ textAlign: 'center', marginBottom: 40 }}>
              <Title level={2} style={{ 
                margin: 0, 
                marginBottom: 8,
                background: 'linear-gradient(135deg, #333 0%, #666 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                fontSize: 32,
                fontWeight: 700,
              }}>
                欢迎登录
              </Title>
              <Text style={{ 
                color: '#666',
                fontSize: 16,
              }}>
                请输入您的账户信息
              </Text>
            </div>

            {/* 登录表单 */}
            <Form
              form={form}
              name="login"
              onFinish={handleLogin}
              autoComplete="off"
              size="large"
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
                  prefix={<UserOutlined style={{ color: '#10a37f' }} />}
                  placeholder="请输入用户名"
                  style={{ 
                    borderRadius: 12,
                    height: 48,
                    fontSize: 16,
                    border: '2px solid #f0f0f0',
                    transition: 'all 0.3s ease',
                  }}
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
                  prefix={<LockOutlined style={{ color: '#10a37f' }} />}
                  placeholder="请输入密码"
                  iconRender={(visible) => (visible ? <EyeTwoTone /> : <EyeInvisibleOutlined />)}
                  style={{ 
                    borderRadius: 12,
                    height: 48,
                    fontSize: 16,
                    border: '2px solid #f0f0f0',
                    transition: 'all 0.3s ease',
                  }}
                />
              </Form.Item>

              <Form.Item name="remember" valuePropName="checked" style={{ marginBottom: 32 }}>
                <Checkbox style={{ color: '#666' }}>记住密码</Checkbox>
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  style={{
                    width: '100%',
                    height: 52,
                    borderRadius: 12,
                    fontSize: 16,
                    fontWeight: 600,
                    background: 'linear-gradient(135deg, #10a37f 0%, #0d8f6b 100%)',
                    border: 'none',
                    boxShadow: '0 4px 16px rgba(16, 163, 127, 0.3)',
                    transition: 'all 0.3s ease',
                  }}
                >
                  {loading ? '登录中...' : '立即登录'}
                </Button>
              </Form.Item>
            </Form>
          </div>
        </Col>
      </Row>

      <style>{`
        @keyframes float {
          0%, 100% { transform: translateY(0px) rotate(0deg); }
          50% { transform: translateY(-30px) rotate(180deg); }
        }
        
        @keyframes pulse {
          0%, 100% { transform: scale(1); opacity: 0.4; }
          50% { transform: scale(1.2); opacity: 0.2; }
        }
        
        @keyframes rotate {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        
        .ant-input:focus,
        .ant-input-password:focus {
          border-color: #10a37f !important;
          box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.1) !important;
        }
        
        .ant-input-affix-wrapper:focus,
        .ant-input-affix-wrapper-focused {
          border-color: #10a37f !important;
          box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.1) !important;
        }

        .ant-btn-primary:hover {
          transform: translateY(-2px) !important;
          box-shadow: 0 6px 20px rgba(16, 163, 127, 0.4) !important;
        }

        @media (max-width: 768px) {
          .ant-col-xs-24 {
            padding: 20px !important;
          }
        }
      `}</style>
    </div>
  )
}

export default Login
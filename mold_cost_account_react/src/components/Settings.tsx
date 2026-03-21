import React, { useState, useEffect } from 'react'
import { 
  Card, 
  Typography, 
  Select, 
  Button, 
  Space, 
  Flex,
  Avatar,
  Modal,
  theme,
  message as antdMessage,
} from 'antd'
import { 
  SettingOutlined, 
  LogoutOutlined,
  RightOutlined,
  UserOutlined,
  SunOutlined,
  MoonOutlined,
  CloseOutlined,
  MenuOutlined,
  SoundOutlined,
} from '@ant-design/icons'
import { useAppStore } from '../store/useAppStore'
import { logoutApi } from '../api/auth'
import { clearAuthData } from '../utils/auth'
import { AUTH_STORAGE_KEYS } from '../constants/auth'
import { speechSynthesisService, VOICE_TYPES, VOICE_TYPE_NAMES, VoiceType } from '../services/speechSynthesisService'

const { Text } = Typography

interface UserInfo {
  userId: string;
  username: string;
  realName: string;
  email: string;
  role: string;
  department?: string;
  isActive: boolean;
  createdAt: string;
  lastLoginAt?: string;
  loginTime: string;
}

const Settings: React.FC = () => {
  const { token } = theme.useToken()
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null)
  const [userDetailVisible, setUserDetailVisible] = useState(false)
  const [voiceType, setVoiceType] = useState<VoiceType>(VOICE_TYPES.FEMALE)
  
  const {
    clearMessages,
    setCurrentJobId,
    setCurrentView,
    isMobile,
    setMobileDrawerVisible,
    themeMode,
    setThemeMode,
  } = useAppStore()

  // 获取用户信息
  useEffect(() => {
    const loadUserInfo = () => {
      try {
        const userInfoStr = localStorage.getItem(AUTH_STORAGE_KEYS.USER_INFO)
        if (userInfoStr) {
          const userData = JSON.parse(userInfoStr)
          setUserInfo(userData)
        }
      } catch (error) {
        console.error('解析用户信息失败:', error)
        localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
      }
    }

    loadUserInfo()
  }, [])

  // 加载音色设置
  useEffect(() => {
    const currentVoiceType = speechSynthesisService.getVoiceType()
    setVoiceType(currentVoiceType)
  }, [])

  // 获取用户显示名称
  const getDisplayName = () => {
    if (!userInfo) return '用户'
    return userInfo.realName || userInfo.username || '用户'
  }

  // 获取用户角色显示
  const getRoleDisplay = () => {
    if (!userInfo) return '操作员'
    
    const roleMap: Record<string, string> = {
      'admin': '管理员',
      'operator': '操作员',
      'viewer': '查看者',
      'engineer': '工程师',
      'manager': '经理',
    }
    
    return roleMap[userInfo.role] || userInfo.role || '操作员'
  }

  // 获取用户头像显示
  const getAvatarContent = () => {
    if (!userInfo) return <UserOutlined />
    
    if (userInfo.realName) {
      return userInfo.realName.charAt(0).toUpperCase()
    }
    
    if (userInfo.username) {
      return userInfo.username.charAt(0).toUpperCase()
    }
    
    return <UserOutlined />
  }

  // 处理退出登录
  const handleLogout = () => {
    Modal.confirm({
      title: '退出登录',
      content: '确定要退出登录吗？',
      okText: '退出',
      okType: 'danger',
      cancelText: '取消',
      okButtonProps: themeMode === 'dark' ? {
        style: {
          background: '#ef4444',
          borderColor: '#ef4444',
          color: '#ffffff',
        },
        onMouseEnter: (e: any) => {
          e.currentTarget.style.background = '#f87171'
          e.currentTarget.style.borderColor = '#f87171'
          e.currentTarget.style.opacity = '0.9'
        },
        onMouseLeave: (e: any) => {
          e.currentTarget.style.background = '#ef4444'
          e.currentTarget.style.borderColor = '#ef4444'
          e.currentTarget.style.opacity = '1'
        },
      } : undefined,
      cancelButtonProps: themeMode === 'dark' ? {
        style: {
          background: '#2a2a2a',
          borderColor: '#3a3a3a',
          color: '#e0e0e0',
        },
        onMouseEnter: (e: any) => {
          e.currentTarget.style.background = 'rgba(255, 255, 255, .05)'
        },
        onMouseLeave: (e: any) => {
          e.currentTarget.style.background = '#2a2a2a'
        },
      } : undefined,
      onOk: async () => {
        try {
          await logoutApi()
        } catch (error: any) {
          console.error('退出登录错误:', error)
        } finally {
          // 清除本地存储
          clearAuthData()
          
          // 清除应用状态
          clearMessages()
          setCurrentJobId(undefined)
          
          // 触发登录状态变化事件
          window.dispatchEvent(new Event('loginStateChange'))
          
          antdMessage.success('已退出登录')
          
          // 跳转到聊天页面
          setCurrentView('chat')
        }
      },
    })
  }

  // 处理主题切换
  const handleThemeChange = (value: 'light' | 'dark') => {
    setThemeMode(value)
    antdMessage.success(`已切换到${value === 'light' ? '浅色' : '深色'}模式`)
  }

  // 处理音色切换
  const handleVoiceTypeChange = (value: VoiceType) => {
    setVoiceType(value)
    speechSynthesisService.setVoiceType(value)
    antdMessage.success(`已切换到${VOICE_TYPE_NAMES[value]}`)
  }

  // 处理返回聊天
  const handleBackToChat = () => {
    setCurrentView('chat')
  }

  // 处理打开侧边栏（移动端）
  const handleOpenSidebar = () => {
    setMobileDrawerVisible(true)
  }

  return (
    <div style={{ 
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: themeMode === 'dark' ? '#1a1a1a' : '#ffffff',
      transition: 'background 0.3s ease',
    }}>
      <style>{`
        .settings-card {
          background: ${themeMode === 'dark' ? '#2a2a2a' : '#F7F7F7'};
          transition: background 0.2s ease;
        }
        .settings-card:hover {
          background: ${themeMode === 'dark' ? '#333333' : '#F0F0F0'} !important;
        }
        .theme-select .ant-select-selector {
          background: ${themeMode === 'dark' ? '#2a2a2a' : '#F7F7F7'} !important;
          border: none !important;
          box-shadow: none !important;
          transition: background 0.2s ease !important;
          color: ${themeMode === 'dark' ? '#e0e0e0' : 'inherit'} !important;
        }
        .theme-select:hover .ant-select-selector {
          background: ${themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : '#E8E8E8'} !important;
        }
        .theme-select.ant-select-focused .ant-select-selector {
          background: ${themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : '#E8E8E8'} !important;
        }
        .settings-card:hover .theme-select .ant-select-selector {
          background: ${themeMode === 'dark' ? '#333333' : '#F0F0F0'} !important;
        }
        .settings-card:hover .theme-select:hover .ant-select-selector {
          background: ${themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : '#E8E8E8'} !important;
        }
        
        /* 深色模式下的文字颜色 */
        ${themeMode === 'dark' ? `
          .settings-card .ant-card-body {
            color: #e0e0e0;
          }
          .theme-select .ant-select-arrow {
            color: #888888 !important;
          }
        ` : ''}
      `}</style>
      {/* 顶部导航栏 */}
      <div style={{
        padding: '12px 24px',
        background: themeMode === 'dark' ? '#1a1a1a' : '#ffffff',
        transition: 'background 0.3s ease',
      }}>
        <Flex align="center" justify="space-between">
          {/* 左侧：移动端显示菜单按钮 */}
          <div style={{ width: 40 }}>
            {isMobile && (
              <Button
                type="text"
                icon={<MenuOutlined />}
                onClick={handleOpenSidebar}
                style={{
                  color: token.colorTextSecondary,
                  padding: '4px 8px',
                  height: 32,
                  width: 32,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              />
            )}
          </div>

          {/* 中间：空白 */}
          <div style={{ flex: 1 }} />

          {/* 右侧：关闭按钮 */}
          <Button
            type="text"
            icon={<CloseOutlined />}
            onClick={handleBackToChat}
            style={{
              color: token.colorTextSecondary,
              padding: '4px 8px',
              height: 32,
              width: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          />
        </Flex>
      </div>

      {/* 内容区域 */}
      <div style={{ 
        flex: 1,
        overflow: 'auto',
        padding: '0 24px 24px',
      }}>
        <div style={{ maxWidth: 640, margin: '0 auto' }}>
          <Space direction="vertical" style={{ width: '100%' }} size={24}>
            {/* 页面标题 */}
            <Flex align="center" gap={12} style={{ marginBottom: 8 }}>
              <SettingOutlined style={{ 
                fontSize: 24, 
                color: themeMode === 'dark' ? '#e0e0e0' : token.colorText 
              }} />
              <Text style={{ 
                fontSize: 24, 
                fontWeight: 600,
                color: themeMode === 'dark' ? '#e0e0e0' : token.colorText,
              }}>设置</Text>
            </Flex>
            {/* 用户信息卡片 */}
            <Card
            className="settings-card"
            style={{
              borderRadius: 12,
              border: 'none',
              cursor: 'pointer',
              transition: 'all 0.2s',
              background: themeMode === 'dark' ? '#2a2a2a' : '#F7F7F7',
            }}
            styles={{ body: { padding: '16px' } }}
            hoverable
            onClick={() => setUserDetailVisible(true)}
          >
            <Flex align="center" justify="space-between">
              <Flex align="center" gap={16}>
                <Avatar
                  size={48}
                  style={{
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    fontSize: 20,
                  }}
                >
                  {getAvatarContent()}
                </Avatar>
                <div>
                  <div style={{ 
                    fontSize: 16, 
                    fontWeight: 600, 
                    color: themeMode === 'dark' ? '#e0e0e0' : token.colorText,
                  }}>
                    {getDisplayName()}
                  </div>
                  <div style={{ 
                    fontSize: 14, 
                    color: themeMode === 'dark' ? '#888888' : token.colorTextSecondary,
                  }}>
                    {userInfo?.username || '未登录'} • {getRoleDisplay()}
                  </div>
                </div>
              </Flex>
              <RightOutlined style={{ 
                fontSize: 16, 
                color: themeMode === 'dark' ? '#666666' : token.colorTextTertiary 
              }} />
            </Flex>
          </Card>

            {/* 通用设置 */}
            <div>
            <Text style={{ 
              fontSize: 14, 
              color: themeMode === 'dark' ? '#888888' : token.colorTextSecondary,
              fontWeight: 500,
              marginBottom: 12,
              display: 'block',
            }}>
              通用
            </Text>

              {/* 界面主题 */}
              {/* <Card
              className="settings-card"
              style={{
                borderRadius: 12,
                border: 'none',
                marginBottom: 12,
                background: themeMode === 'dark' ? '#2a2a2a' : '#F7F7F7',
              }}
              styles={{ body: { padding: '8px 16px' } }}
            >
              <Flex justify="space-between" align="center">
                <Flex align="center" gap={12}>
                  {themeMode === 'light' ? (
                    <SunOutlined style={{ fontSize: 20, color: token.colorPrimary }} />
                  ) : (
                    <MoonOutlined style={{ fontSize: 20, color: '#8b5cf6' }} />
                  )}
                  <div>
                    <div style={{ 
                      fontSize: 14, 
                      fontWeight: 500, 
                      color: themeMode === 'dark' ? '#e0e0e0' : token.colorText,
                    }}>
                      界面主题
                    </div>
                  </div>
                </Flex>
                <Select
                  className="theme-select"
                  value={themeMode}
                  onChange={handleThemeChange}
                  style={{ width: 120 }}
                  options={[
                    { label: '浅色', value: 'light' },
                    { label: '深色', value: 'dark' },
                  ]}
                />
              </Flex>
            </Card> */}

              {/* 角色音色 */}
              <Card
              className="settings-card"
              style={{
                borderRadius: 12,
                border: 'none',
                marginBottom: 12,
                background: themeMode === 'dark' ? '#2a2a2a' : '#F7F7F7',
              }}
              styles={{ body: { padding: '8px 16px' } }}
            >
              <Flex justify="space-between" align="center">
                <Flex align="center" gap={12}>
                  <SoundOutlined style={{ 
                    fontSize: 20, 
                    color: themeMode === 'dark' ? '#8b5cf6' : token.colorPrimary 
                  }} />
                  <div>
                    <div style={{ 
                      fontSize: 14, 
                      fontWeight: 500, 
                      color: themeMode === 'dark' ? '#e0e0e0' : token.colorText,
                    }}>
                      角色音色
                    </div>
                  </div>
                </Flex>
                <Select
                  className="theme-select"
                  value={voiceType}
                  onChange={handleVoiceTypeChange}
                  style={{ width: 120 }}
                  options={[
                    { label: VOICE_TYPE_NAMES[VOICE_TYPES.FEMALE], value: VOICE_TYPES.FEMALE },
                    { label: VOICE_TYPE_NAMES[VOICE_TYPES.MALE], value: VOICE_TYPES.MALE },
                  ]}
                />
              </Flex>
            </Card>

              {/* 退出登录 */}
              <Card
              className="settings-card"
              style={{
                borderRadius: 12,
                border: 'none',
                cursor: 'pointer',
                transition: 'all 0.2s',
                background: themeMode === 'dark' ? '#2a2a2a' : '#F7F7F7',
                marginTop: '28px'
              }}
              styles={{ body: { height: '48px', padding: 0, display: 'flex', justifyContent: 'center', alignItems: 'center' } }}
              hoverable
              onClick={handleLogout}
            >
              <Flex align="center" gap={12}>
                <LogoutOutlined style={{ 
                  fontSize: 20, 
                  color: themeMode === 'dark' ? '#ef4444' : token.colorError 
                }} />
                <div style={{ 
                  fontSize: 15, 
                  fontWeight: 500, 
                  color: themeMode === 'dark' ? '#ef4444' : token.colorError,
                }}>
                  退出登录
                </div>
              </Flex>
            </Card>
            </div>
          </Space>
        </div>
      </div>

      {/* 用户详情弹窗 */}
      <Modal
        title="用户信息"
        open={userDetailVisible}
        onCancel={() => setUserDetailVisible(false)}
        footer={[
          <Button key="close" type="primary" onClick={() => setUserDetailVisible(false)}>
            关闭
          </Button>
        ]}
        width={480}
      >
        {userInfo && (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <Flex justify="center" style={{ marginTop: 16, marginBottom: 8 }}>
              <Avatar
                size={80}
                style={{
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  fontSize: 32,
                }}
              >
                {getAvatarContent()}
              </Avatar>
            </Flex>

            {/* <Divider style={{ margin: '8px 0' }} /> */}

            <div>
              <Text type="secondary" style={{ fontSize: 13 }}>昵称</Text>
              <div style={{ 
                fontSize: 15, 
                marginTop: 4,
                background: '#F7F7F7',
                padding: '12px 16px',
                borderRadius: 8,
              }}>
                {userInfo.realName || '未设置'}
              </div>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 13 }}>用户名</Text>
              <div style={{ 
                fontSize: 15, 
                marginTop: 4,
                background: '#F7F7F7',
                padding: '12px 16px',
                borderRadius: 8,
              }}>
                {userInfo.username}
              </div>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 13 }}>邮箱</Text>
              <div style={{ 
                fontSize: 15, 
                marginTop: 4,
                background: '#F7F7F7',
                padding: '12px 16px',
                borderRadius: 8,
              }}>
                {userInfo.email || '未设置'}
              </div>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 13 }}>角色</Text>
              <div style={{ 
                fontSize: 15, 
                marginTop: 4,
                background: '#F7F7F7',
                padding: '12px 16px',
                borderRadius: 8,
              }}>
                {getRoleDisplay()}
              </div>
            </div>

            {userInfo.department && (
              <div>
                <Text type="secondary" style={{ fontSize: 13 }}>部门</Text>
                <div style={{ 
                  fontSize: 15, 
                  marginTop: 4,
                  background: '#F7F7F7',
                  padding: '12px 16px',
                  borderRadius: 8,
                }}>
                  {userInfo.department}
                </div>
              </div>
            )}

            {userInfo.lastLoginAt && (
              <div>
                <Text type="secondary" style={{ fontSize: 13 }}>上次登录</Text>
                <div style={{ 
                  fontSize: 15, 
                  marginTop: 4,
                  background: '#F7F7F7',
                  padding: '12px 16px',
                  borderRadius: 8,
                }}>
                  {new Date(userInfo.lastLoginAt).toLocaleString('zh-CN')}
                </div>
              </div>
            )}

            <div>
              <Text type="secondary" style={{ fontSize: 13 }}>账号创建时间</Text>
              <div style={{ 
                fontSize: 15, 
                marginTop: 4,
                background: '#F7F7F7',
                padding: '12px 16px',
                borderRadius: 8,
              }}>
                {new Date(userInfo.createdAt).toLocaleString('zh-CN')}
              </div>
            </div>
          </Space>
        )}
      </Modal>
    </div>
  )
}

export default Settings
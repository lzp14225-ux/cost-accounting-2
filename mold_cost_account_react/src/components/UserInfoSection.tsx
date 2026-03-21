import React, { useState, useEffect } from 'react'
import {
  Avatar,
  Flex,
  Dropdown,
  Modal,
  message,
  Tooltip,
} from 'antd'
import {
  UserOutlined,
  SettingOutlined,
  LogoutOutlined,
  MoreOutlined,
  KeyOutlined,
} from '@ant-design/icons'
import { theme } from 'antd'
import { useAppStore } from '../store/useAppStore'
import { logoutApi } from '../api/auth'
import { clearAuthData } from '../utils/auth'
import { AUTH_STORAGE_KEYS } from '../constants/auth'
import ChangePasswordModal from './ChangePasswordModal'

interface UserInfoSectionProps {
  sidebarCollapsed: boolean;
}

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

const UserInfoSection: React.FC<UserInfoSectionProps> = ({ sidebarCollapsed }) => {
  const { token } = theme.useToken()
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null)
  const [changePasswordVisible, setChangePasswordVisible] = useState(false)
  
  const {
    clearMessages,
    setCurrentJobId,
    themeMode,
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
        // 如果解析失败，清除无效数据
        localStorage.removeItem(AUTH_STORAGE_KEYS.USER_INFO)
      }
    }

    loadUserInfo()
  }, [])

  // 处理退出登录
  const handleLogout = () => {
    Modal.confirm({
      title: '退出登录',
      content: '确定要退出登录吗？',
      okText: '退出',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          // 调用退出登录API
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
          
          message.success('已退出登录')
          
          // 跳转到聊天页面
          const { setCurrentView } = useAppStore.getState()
          setCurrentView('chat')
        }
      },
    })
  }

  // 处理打开设置
  const handleOpenSettings = () => {
    const { setCurrentView, setMobileDrawerVisible, isMobile } = useAppStore.getState()
    setCurrentView('settings')
    // 如果是移动端，关闭抽屉
    if (isMobile) {
      setMobileDrawerVisible(false)
    }
  }

  // 处理打开修改密码弹窗
  const handleOpenChangePassword = () => {
    setChangePasswordVisible(true)
  }

  // 用户菜单项
  const userMenuItems = [
    {
      key: 'settings',
      label: '设置',
      icon: <SettingOutlined />,
      onClick: handleOpenSettings,
    },
    {
      key: 'changePassword',
      label: '修改密码',
      icon: <KeyOutlined />,
      onClick: handleOpenChangePassword,
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      label: '退出登录',
      icon: <LogoutOutlined />,
      danger: true,
      onClick: handleLogout,
    },
  ]

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
    
    // 如果有真实姓名，使用姓名的首字母
    if (userInfo.realName) {
      return userInfo.realName.charAt(0).toUpperCase()
    }
    
    // 否则使用用户名的首字母
    if (userInfo.username) {
      return userInfo.username.charAt(0).toUpperCase()
    }
    
    return <UserOutlined />
  }

  // 获取用户详细信息tooltip
  const getUserTooltip = () => {
    if (!userInfo) return '用户信息'
    
    return (
      <div style={{ maxWidth: 200 }}>
        <div><strong>昵称:</strong> {userInfo.realName || '未设置'}</div>
        <div><strong>用户名:</strong> {userInfo.username}</div>
        <div><strong>邮箱:</strong> {userInfo.email || '未设置'}</div>
        <div><strong>角色:</strong> {getRoleDisplay()}</div>
        {userInfo.department && <div><strong>部门:</strong> {userInfo.department}</div>}
        {userInfo.lastLoginAt && (
          <div><strong>上次登录:</strong> {new Date(userInfo.lastLoginAt).toLocaleString('zh-CN')}</div>
        )}
      </div>
    )
  }

  return (
    <>
      <div
        className="user-info-section"
        style={{
          padding: sidebarCollapsed ? '16px 8px' : '16px 20px',
          background: themeMode === 'dark' ? '#161717' : '#FAFAFA',
          transition: 'background 0.3s ease',
        }}
      >
        <style>{`
          .user-info-container:hover {
            background: ${themeMode === 'dark' ? 'rgba(255, 255, 255, .05)' : token.colorFillQuaternary} !important;
          }
          
          .user-avatar-collapsed:hover {
            transform: scale(1.05);
            box-shadow: 0 2px 8px ${token.colorPrimary}40;
          }
          
          .ant-tooltip-inner {
            text-align: left;
          }
          
          .user-info-section {
            background: ${themeMode === 'dark' ? '#161717' : '#FAFAFA'} !important;
          }
        `}</style>
        {sidebarCollapsed ? (
          // 折叠状态 - 只显示头像，点击显示菜单
          <div style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            width: '100%',
          }}>
            <Dropdown
              menu={{ items: userMenuItems }}
              trigger={['click']}
              placement="topRight"
            >
              <Tooltip title={getDisplayName()} placement="right">
                <Avatar
                  size={32}
                  style={{
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                  }}
                  className="user-avatar-collapsed"
                >
                  {getAvatarContent()}
                </Avatar>
              </Tooltip>
            </Dropdown>
          </div>
        ) : (
          // 展开状态 - 显示完整用户信息
          <Dropdown
            menu={{ items: userMenuItems }}
            trigger={['click']}
            placement="topRight"
          >
              <div
                style={{
                  cursor: 'pointer',
                  borderRadius: 8,
                  padding: '8px',
                  margin: '-8px',
                  transition: 'all 0.3s ease',
                }}
                className="user-info-container"
              >
                <Flex
                  align="center"
                  gap={12}
                  justify="flex-start"
                >
                  <Avatar
                    size={32}
                    style={{
                      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      flexShrink: 0,
                    }}
                  >
                    {getAvatarContent()}
                  </Avatar>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 14,
                    fontWeight: 500,
                    color: themeMode === 'dark' ? 'rgba(255, 255, 255, .84)' : token.colorText,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    transition: 'color 0.3s ease',
                  }}>
                    {getDisplayName()}
                  </div>
                  <div style={{
                    fontSize: 12,
                    color: themeMode === 'dark' ? 'rgba(255, 255, 255, .6)' : token.colorTextSecondary,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    transition: 'color 0.3s ease',
                  }}>
                    {getRoleDisplay()}
                  </div>
                </div>
                <MoreOutlined
                  style={{
                    color: themeMode === 'dark' ? 'rgba(255, 255, 255, .6)' : token.colorTextSecondary,
                    fontSize: 16,
                    transition: 'color 0.3s ease',
                  }}
                />
              </Flex>
            </div>
          </Dropdown>
        )}
      </div>

      {/* 修改密码弹窗 */}
      <ChangePasswordModal
        visible={changePasswordVisible}
        onCancel={() => setChangePasswordVisible(false)}
      />
    </>
  )
}

export default UserInfoSection
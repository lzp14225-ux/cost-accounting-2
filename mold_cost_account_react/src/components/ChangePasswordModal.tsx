import React, { useState } from 'react'
import { Modal, Form, Input, message } from 'antd'
import { LockOutlined } from '@ant-design/icons'
import { changePasswordApi, logoutApi } from '../api/auth'
import { clearAuthData } from '../utils/auth'
import { useAppStore } from '../store/useAppStore'

interface ChangePasswordModalProps {
  visible: boolean
  onCancel: () => void
}

const ChangePasswordModal: React.FC<ChangePasswordModalProps> = ({ visible, onCancel }) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const { clearMessages, setCurrentJobId, setCurrentView } = useAppStore()

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)

      const response = await changePasswordApi(values.newPassword)

      if (response.success) {
        message.success(response.message || '密码修改成功，请重新登录')
        form.resetFields()
        onCancel()

        // 延迟500ms后执行退出登录操作，让用户看到成功提示
        setTimeout(async () => {
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
            
            // 跳转到聊天页面
            setCurrentView('chat')
          }
        }, 500)
      } else {
        message.error(response.message || '密码修改失败')
      }
    } catch (error: any) {
      if (error.errorFields) {
        // 表单验证错误
        return
      }
      console.error('修改密码失败:', error)
      message.error(error.message || '密码修改失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = () => {
    form.resetFields()
    onCancel()
  }

  return (
    <Modal
      title="修改密码"
      open={visible}
      onOk={handleSubmit}
      onCancel={handleCancel}
      confirmLoading={loading}
      okText="确认修改"
      cancelText="取消"
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        autoComplete="off"
      >
        <Form.Item
          name="newPassword"
          label="新密码"
          rules={[
            { required: true, message: '请输入新密码' },
            { min: 6, message: '密码长度至少为6位' },
          ]}
        >
          <Input.Password
            prefix={<LockOutlined />}
            placeholder="请输入新密码"
            autoComplete="new-password"
          />
        </Form.Item>

        <Form.Item
          name="confirmPassword"
          label="确认密码"
          dependencies={['newPassword']}
          rules={[
            { required: true, message: '请确认新密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('newPassword') === value) {
                  return Promise.resolve()
                }
                return Promise.reject(new Error('两次输入的密码不一致'))
              },
            }),
          ]}
        >
          <Input.Password
            prefix={<LockOutlined />}
            placeholder="请再次输入新密码"
            autoComplete="new-password"
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default ChangePasswordModal

import React, { useState } from 'react'
import { Card, Form, Input, Select, Checkbox, Button, Space, Typography, Divider } from 'antd'
import { InteractionCard } from '../services/websocketService'

const { Title, Text } = Typography
const { Option } = Select

interface InteractionCardDisplayProps {
  card: InteractionCard
  onSubmit: (cardId: string, action: string, inputs: Record<string, any>) => Promise<void>
  loading?: boolean
}

const InteractionCardDisplay: React.FC<InteractionCardDisplayProps> = ({
  card,
  onSubmit,
  loading = false,
}) => {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (action: string) => {
    try {
      setSubmitting(true)
      
      // 获取表单数据
      const values = await form.validateFields()
      
      // 提交用户输入
      await onSubmit(card.id, action, values)
      
      // 重置表单
      form.resetFields()
    } catch (error) {
      console.error('提交失败:', error)
    } finally {
      setSubmitting(false)
    }
  }

  const renderField = (field: any) => {
    const { name, label, type, required, options, defaultValue } = field

    switch (type) {
      case 'text':
        return (
          <Form.Item
            key={name}
            name={name}
            label={label}
            rules={[{ required, message: `请输入${label}` }]}
            initialValue={defaultValue}
          >
            <Input placeholder={`请输入${label}`} />
          </Form.Item>
        )

      case 'number':
        return (
          <Form.Item
            key={name}
            name={name}
            label={label}
            rules={[{ required, message: `请输入${label}` }]}
            initialValue={defaultValue}
          >
            <Input type="number" placeholder={`请输入${label}`} />
          </Form.Item>
        )

      case 'select':
        return (
          <Form.Item
            key={name}
            name={name}
            label={label}
            rules={[{ required, message: `请选择${label}` }]}
            initialValue={defaultValue}
          >
            <Select placeholder={`请选择${label}`}>
              {options?.map((option: any) => (
                <Option key={option.value} value={option.value}>
                  {option.label}
                </Option>
              ))}
            </Select>
          </Form.Item>
        )

      case 'checkbox':
        return (
          <Form.Item
            key={name}
            name={name}
            valuePropName="checked"
            initialValue={defaultValue}
          >
            <Checkbox>{label}</Checkbox>
          </Form.Item>
        )

      default:
        return null
    }
  }

  return (
    <Card
      style={{
        marginBottom: 16,
        border: '2px solid #1890ff',
        borderRadius: 8,
        boxShadow: '0 4px 12px rgba(24, 144, 255, 0.15)',
      }}
      bodyStyle={{ padding: 24 }}
    >
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0, color: '#1890ff' }}>
          {card.title}
        </Title>
        {card.description && (
          <Text type="secondary" style={{ marginTop: 8, display: 'block' }}>
            {card.description}
          </Text>
        )}
      </div>

      <Divider style={{ margin: '16px 0' }} />

      <Form
        form={form}
        layout="vertical"
        onFinish={() => {}} // 不使用默认提交
      >
        {card.fields?.map(renderField)}

        <Form.Item style={{ marginBottom: 0, marginTop: 24 }}>
          <Space>
            {card.actions?.map((action) => (
              <Button
                key={action.action}
                type={action.type === 'primary' ? 'primary' : action.type === 'danger' ? 'primary' : 'default'}
                danger={action.type === 'danger'}
                loading={submitting || loading}
                onClick={() => handleSubmit(action.action)}
              >
                {action.label}
              </Button>
            ))}
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}

export default InteractionCardDisplay
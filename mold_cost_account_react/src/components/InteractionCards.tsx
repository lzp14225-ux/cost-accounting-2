import React, { useState } from 'react'
import { Card, Button, Input, InputNumber, Select, Form, Space, Typography, Flex, Alert, theme } from 'antd'
import { ExclamationCircleOutlined, InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { InteractionCard } from '../store/useAppStore'
import { useAppStore } from '../store/useAppStore'
import { chatService } from '../services/chatService'

const { Title, Text } = Typography
const { TextArea } = Input

interface InteractionCardsProps {
  cards: InteractionCard[]
}

const InteractionCards: React.FC<InteractionCardsProps> = ({ cards }) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState<string | null>(null)
  const { token } = theme.useToken()
  
  const { removeInteractionCard, addMessage } = useAppStore()

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'error':
        return <ExclamationCircleOutlined style={{ color: token.colorError, fontSize: 16 }} />
      case 'warning':
        return <WarningOutlined style={{ color: token.colorWarning, fontSize: 16 }} />
      default:
        return <InfoCircleOutlined style={{ color: token.colorInfo, fontSize: 16 }} />
    }
  }

  const getSeverityType = (severity: string) => {
    switch (severity) {
      case 'error':
        return 'error'
      case 'warning':
        return 'warning'
      default:
        return 'info'
    }
  }

  const handleSubmit = async (card: InteractionCard, action: string) => {
    setLoading(card.id)
    
    try {
      let inputs = {}
      
      if (action === 'submit' && card.fields) {
        // 获取表单数据
        const values = await form.validateFields()
        inputs = values
      }

      // 发送响应到后端
      await chatService.submitInteraction(card.id, action, inputs)

      // 添加用户消息
      if (action === 'submit') {
        const inputText = Object.entries(inputs)
          .map(([key, value]) => `${key}: ${value}`)
          .join(', ')
        
        addMessage({
          type: 'user',
          content: `已提交参数: ${inputText}`,
          jobId: card.jobId,
        })
      } else if (action === 're_recognize') {
        addMessage({
          type: 'user',
          content: '请重新识别参数',
          jobId: card.jobId,
        })
      }

      // 移除卡片
      removeInteractionCard(card.id)

    } catch (error) {
      console.error('提交交互失败:', error)
    } finally {
      setLoading(null)
    }
  }

  const renderField = (field: any) => {
    const commonProps = {
      placeholder: field.placeholder || `请输入${field.label}`,
      style: { width: '100%' },
    }

    switch (field.component) {
      case 'number':
        return (
          <InputNumber
            {...commonProps}
            min={field.min}
            max={field.max}
            precision={field.precision || 2}
            addonAfter={field.unit}
          />
        )
      
      case 'select':
        return (
          <Select {...commonProps}>
            {field.options?.map((option: any) => (
              <Select.Option key={option.value} value={option.value}>
                {option.label}
              </Select.Option>
            ))}
          </Select>
        )
      
      case 'textarea':
        return (
          <TextArea
            {...commonProps}
            rows={3}
            maxLength={field.maxLength}
          />
        )
      
      default:
        return (
          <Input
            {...commonProps}
            maxLength={field.maxLength}
          />
        )
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%', margin: '16px 0' }} size={16}>
      {cards.map((card) => (
        <Card
          key={card.id}
          style={{
            borderRadius: token.borderRadiusLG,
            boxShadow: token.boxShadowTertiary,
          }}
          styles={{ body: { padding: 24 } }}
        >
          <Space direction="vertical" style={{ width: '100%' }} size={20}>
            {/* 警告提示 */}
            <Alert
              message={card.title}
              description={card.message}
              type={getSeverityType(card.severity) as any}
              icon={getSeverityIcon(card.severity)}
              showIcon
              style={{
                borderRadius: token.borderRadius,
              }}
            />

            {/* 输入字段 */}
            {card.fields && card.fields.length > 0 && (
              <Card
                size="small"
                title="参数设置"
                style={{
                  background: token.colorFillAlter,
                  border: `1px solid ${token.colorBorderSecondary}`,
                }}
              >
                <Form
                  form={form}
                  layout="vertical"
                  initialValues={card.fields.reduce((acc, field) => ({
                    ...acc,
                    [field.key]: field.defaultValue,
                  }), {})}
                >
                  <Space direction="vertical" style={{ width: '100%' }} size={16}>
                    {card.fields.map((field) => (
                      <Form.Item
                        key={field.key}
                        name={field.key}
                        label={
                          <Flex align="center" gap={8}>
                            <span style={{ fontWeight: 500 }}>{field.label}</span>
                            {field.subgraphId && (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                (子图: {field.subgraphId})
                              </Text>
                            )}
                          </Flex>
                        }
                        rules={[
                          {
                            required: field.required,
                            message: `请输入${field.label}`,
                          },
                          ...(field.min !== undefined ? [{
                            type: 'number' as const,
                            min: field.min,
                            message: `${field.label}不能小于${field.min}`,
                          }] : []),
                          ...(field.max !== undefined ? [{
                            type: 'number' as const,
                            max: field.max,
                            message: `${field.label}不能大于${field.max}`,
                          }] : []),
                        ]}
                        style={{ marginBottom: 0 }}
                      >
                        {renderField(field)}
                      </Form.Item>
                    ))}
                  </Space>
                </Form>
              </Card>
            )}

            {/* 操作按钮 */}
            {card.buttons && (
              <Flex justify="flex-end" gap={12}>
                {card.buttons.map((button) => (
                  <Button
                    key={button.key}
                    type={button.style === 'primary' ? 'primary' : 'default'}
                    danger={button.style === 'danger'}
                    loading={loading === card.id}
                    onClick={() => handleSubmit(card, button.key)}
                    style={{
                      ...(button.style === 'primary' && {
                        background: token.colorPrimary,
                        borderColor: token.colorPrimary,
                      }),
                    }}
                  >
                    {button.label}
                  </Button>
                ))}
              </Flex>
            )}
          </Space>
        </Card>
      ))}
    </Space>
  )
}

export default InteractionCards
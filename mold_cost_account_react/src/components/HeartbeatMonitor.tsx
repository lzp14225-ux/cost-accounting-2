import React, { useState } from 'react'
import { Card, Statistic, Row, Col, Tag, Button, Modal, Form, InputNumber, Switch, Space, Tooltip } from 'antd'
import { HeartOutlined, SettingOutlined, WifiOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { ConnectionStats, HeartbeatConfig } from '../services/websocketService'

interface HeartbeatMonitorProps {
  stats: ConnectionStats | null
  quality: 'good' | 'poor' | 'bad' | null
  config: HeartbeatConfig
  onConfigUpdate: (config: Partial<HeartbeatConfig>) => void
}

const HeartbeatMonitor: React.FC<HeartbeatMonitorProps> = ({
  stats,
  quality,
  config,
  onConfigUpdate,
}) => {
  const [configModalVisible, setConfigModalVisible] = useState(false)
  const [form] = Form.useForm()

  const getQualityColor = () => {
    switch (quality) {
      case 'good':
        return 'green'
      case 'poor':
        return 'orange'
      case 'bad':
        return 'red'
      default:
        return 'default'
    }
  }

  const getQualityText = () => {
    switch (quality) {
      case 'good':
        return '良好'
      case 'poor':
        return '一般'
      case 'bad':
        return '较差'
      default:
        return '未知'
    }
  }

  const formatDuration = (timestamp: number) => {
    if (!timestamp) return '0秒'
    const seconds = Math.floor((Date.now() - timestamp) / 1000)
    if (seconds < 60) return `${seconds}秒`
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}分${seconds % 60}秒`
    const hours = Math.floor(minutes / 60)
    return `${hours}时${minutes % 60}分`
  }

  const getSuccessRate = () => {
    if (!stats || stats.heartbeatsSent === 0) return 0
    return Math.round((stats.heartbeatsReceived / stats.heartbeatsSent) * 100)
  }

  const handleConfigSave = async () => {
    try {
      const values = await form.validateFields()
      onConfigUpdate(values)
      setConfigModalVisible(false)
    } catch (error) {
      console.error('配置验证失败:', error)
    }
  }

  const openConfigModal = () => {
    form.setFieldsValue(config)
    setConfigModalVisible(true)
  }

  return (
    <>
      <Card
        title={
          <Space>
            <HeartOutlined style={{ color: getQualityColor() }} />
            <span>心跳监控</span>
            <Tag color={getQualityColor()}>{getQualityText()}</Tag>
          </Space>
        }
        extra={
          <Button
            type="text"
            size="small"
            icon={<SettingOutlined />}
            onClick={openConfigModal}
          >
            配置
          </Button>
        }
        size="small"
      >
        {stats ? (
          <Row gutter={16}>
            <Col span={6}>
              <Statistic
                title="延迟"
                value={stats.latency}
                suffix="ms"
                valueStyle={{ 
                  color: stats.latency > 500 ? '#ff4d4f' : stats.latency > 200 ? '#faad14' : '#52c41a' 
                }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="成功率"
                value={getSuccessRate()}
                suffix="%"
                valueStyle={{ 
                  color: getSuccessRate() < 80 ? '#ff4d4f' : getSuccessRate() < 90 ? '#faad14' : '#52c41a' 
                }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="丢失次数"
                value={stats.missedHeartbeats}
                valueStyle={{ 
                  color: stats.missedHeartbeats > 0 ? '#ff4d4f' : '#52c41a' 
                }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="连接时长"
                value={formatDuration(stats.connectTime)}
              />
            </Col>
          </Row>
        ) : (
          <div style={{ textAlign: 'center', padding: '20px 0', color: '#999' }}>
            <WifiOutlined style={{ fontSize: 24, marginBottom: 8 }} />
            <div>未连接</div>
          </div>
        )}

        {stats && (
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={8}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: '#999' }}>发送心跳</div>
                <div style={{ fontSize: 16, fontWeight: 'bold' }}>{stats.heartbeatsSent}</div>
              </div>
            </Col>
            <Col span={8}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: '#999' }}>接收心跳</div>
                <div style={{ fontSize: 16, fontWeight: 'bold' }}>{stats.heartbeatsReceived}</div>
              </div>
            </Col>
            <Col span={8}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: '#999' }}>总消息</div>
                <div style={{ fontSize: 16, fontWeight: 'bold' }}>{stats.totalMessages}</div>
              </div>
            </Col>
          </Row>
        )}
      </Card>

      <Modal
        title={
          <Space>
            <SettingOutlined />
            <span>心跳配置</span>
          </Space>
        }
        open={configModalVisible}
        onOk={handleConfigSave}
        onCancel={() => setConfigModalVisible(false)}
        width={500}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={config}
        >
          <Form.Item
            name="enabled"
            label="启用心跳检测"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          <Form.Item
            name="interval"
            label={
              <Tooltip title="心跳发送间隔时间，单位毫秒">
                <span>心跳间隔 (ms)</span>
              </Tooltip>
            }
            rules={[
              { required: true, message: '请输入心跳间隔' },
              { type: 'number', min: 5000, max: 300000, message: '间隔时间应在5秒到5分钟之间' }
            ]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="30000"
              formatter={value => `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
              parser={value => value!.replace(/\$\s?|(,*)/g, '')}
            />
          </Form.Item>

          <Form.Item
            name="timeout"
            label={
              <Tooltip title="心跳响应超时时间，单位毫秒">
                <span>超时时间 (ms)</span>
              </Tooltip>
            }
            rules={[
              { required: true, message: '请输入超时时间' },
              { type: 'number', min: 1000, max: 60000, message: '超时时间应在1秒到1分钟之间' }
            ]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="10000"
              formatter={value => `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
              parser={value => value!.replace(/\$\s?|(,*)/g, '')}
            />
          </Form.Item>

          <Form.Item
            name="maxMissed"
            label={
              <Tooltip title="允许连续丢失的最大心跳次数，超过后将断开连接">
                <span>最大丢失次数</span>
              </Tooltip>
            }
            rules={[
              { required: true, message: '请输入最大丢失次数' },
              { type: 'number', min: 1, max: 10, message: '丢失次数应在1到10之间' }
            ]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="3"
              min={1}
              max={10}
            />
          </Form.Item>
        </Form>

        <div style={{ 
          marginTop: 16, 
          padding: 12, 
          background: '#f6f8fa', 
          borderRadius: 6,
          fontSize: 12,
          color: '#666'
        }}>
          <ThunderboltOutlined style={{ marginRight: 4 }} />
          <strong>说明：</strong>
          <ul style={{ margin: '8px 0 0 16px', paddingLeft: 0 }}>
            <li>心跳间隔：发送心跳的时间间隔，建议15-60秒</li>
            <li>超时时间：等待心跳响应的最长时间，建议5-15秒</li>
            <li>最大丢失：连续丢失心跳的容忍次数，建议2-5次</li>
          </ul>
        </div>
      </Modal>
    </>
  )
}

export default HeartbeatMonitor
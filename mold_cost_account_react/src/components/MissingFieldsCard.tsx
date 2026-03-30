import React from 'react'
import { Card, Typography, Space, theme, Divider } from 'antd'
import { ExclamationCircleOutlined } from '@ant-design/icons'

const { Text } = Typography

interface MissingField {
  table: string
  record_id: string
  record_name: string
  part_code?: string
  part_name?: string
  missing: Record<string, string>
  current_values: Record<string, any>
}

interface NCFailedItem {
  record_id: string
  record_name: string
  subgraph_id?: string
  part_code?: string
  part_name?: string
  reason?: string
}

interface MissingFieldsCardProps {
  message: string
  summary?: string
  missingFields: MissingField[]
  ncFailedItems?: NCFailedItem[]
}

const scrollbarStyles = `
  .missing-fields-list::-webkit-scrollbar {
    width: 6px;
  }

  .missing-fields-list::-webkit-scrollbar-track {
    background: transparent;
    border-radius: 3px;
  }

  .missing-fields-list::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.15);
    border-radius: 3px;
    transition: background 0.2s ease;
  }

  .missing-fields-list::-webkit-scrollbar-thumb:hover {
    background: rgba(0, 0, 0, 0.25);
  }

  .missing-fields-list {
    scrollbar-width: thin;
    scrollbar-color: rgba(0, 0, 0, 0.15) transparent;
  }
`

const MissingFieldsCard: React.FC<MissingFieldsCardProps> = ({
  message,
  summary,
  missingFields,
  ncFailedItems = [],
}) => {
  const { token } = theme.useToken()
  const hasMissingFields = missingFields.length > 0
  const hasNcFailedItems = ncFailedItems.length > 0
  const resolvedMessage =
    hasMissingFields && hasNcFailedItems
      ? '发现部分必填字段为空，且有部分物料 NC 识别失败，请先处理这些记录'
      : hasNcFailedItems
        ? '发现部分物料 NC 识别失败，请先确认这些物料'
        : message

  let helperText = '请先处理这些待确认物料。'
  if (hasMissingFields && hasNcFailedItems) {
    helperText = '请先补全缺失字段，并核对 NC 识别失败的物料。'
  } else if (hasMissingFields) {
    helperText = '请在下方输入框中补充缺失的字段信息。'
  } else if (hasNcFailedItems) {
    helperText = '请检查这些物料的图纸或 NC 返回结果，必要时手动确认工艺和工时。'
  }

  return (
    <>
      <style>{scrollbarStyles}</style>

      <Card
        style={{
          background: token.colorWarningBg,
          border: `1px solid ${token.colorWarningBorder}`,
          borderRadius: token.borderRadius,
        }}
        styles={{ body: { padding: '16px' } }}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
            <ExclamationCircleOutlined
              style={{
                fontSize: 20,
                color: token.colorWarning,
                marginTop: 2,
              }}
            />
            <div style={{ flex: 1 }}>
              <Text strong style={{ fontSize: 15, color: token.colorWarningText }}>
                {resolvedMessage}
              </Text>
              {summary && (
                <div style={{ marginTop: 8 }}>
                  <Text style={{ fontSize: 14, color: token.colorTextSecondary }}>
                    {summary}
                  </Text>
                </div>
              )}
            </div>
          </div>

          <Divider style={{ margin: 0 }} />

          <div
            style={{
              maxHeight: '360px',
              overflowY: 'auto',
              overflowX: 'hidden',
              paddingRight: '4px',
            }}
            className="missing-fields-list"
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              {hasMissingFields && (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <Text strong style={{ fontSize: 13, color: token.colorTextSecondary }}>
                    缺少必填字段
                  </Text>
                  {missingFields.map((field, index) => (
                    <div
                      key={`${field.table}-${field.record_id}`}
                      style={{
                        padding: '8px 12px',
                        background: token.colorBgContainer,
                        border: `1px solid ${token.colorBorder}`,
                        borderRadius: 6,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        transition: 'all 0.2s ease',
                      }}
                    >
                      <div
                        style={{
                          minWidth: 22,
                          height: 22,
                          borderRadius: '50%',
                          background: `linear-gradient(135deg, ${token.colorPrimary}15 0%, ${token.colorPrimary}25 100%)`,
                          color: token.colorPrimary,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 12,
                          fontWeight: 600,
                          flexShrink: 0,
                        }}
                      >
                        {index + 1}
                      </div>

                      {field.part_name && (
                        <Text strong style={{ fontSize: 14, color: token.colorText, flexShrink: 0 }}>
                          {field.part_name}
                        </Text>
                      )}

                      {field.part_code && (
                        <Text
                          style={{
                            fontSize: 13,
                            color: token.colorTextSecondary,
                            flexShrink: 0,
                            fontFamily: 'monospace',
                          }}
                        >
                          ({field.part_code})
                        </Text>
                      )}

                      <div
                        style={{
                          width: 1,
                          height: 14,
                          background: token.colorBorderSecondary,
                          flexShrink: 0,
                          margin: '0 2px',
                        }}
                      />

                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
                        <Text type="secondary" style={{ fontSize: 12, flexShrink: 0 }}>
                          缺少
                        </Text>
                        {Object.entries(field.missing).map(([fieldName, fieldDesc]) => (
                          <div
                            key={fieldName}
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              background: token.colorErrorBg,
                              border: `1px solid ${token.colorErrorBorder}`,
                              color: token.colorErrorText,
                              fontSize: 12,
                              fontWeight: 500,
                              lineHeight: '18px',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {fieldDesc}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </Space>
              )}

              {hasNcFailedItems && (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <Text strong style={{ fontSize: 13, color: token.colorError }}>
                    NC 识别失败
                  </Text>
                  {ncFailedItems.map((item, index) => (
                    <div
                      key={`nc-failed-${item.record_id}-${item.part_code || index}`}
                      style={{
                        padding: '8px 12px',
                        background: token.colorBgContainer,
                        border: `1px solid ${token.colorErrorBorder}`,
                        borderRadius: 6,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                      }}
                    >
                      <div
                        style={{
                          minWidth: 22,
                          height: 22,
                          borderRadius: '50%',
                          background: token.colorErrorBg,
                          color: token.colorError,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 12,
                          fontWeight: 600,
                          flexShrink: 0,
                        }}
                      >
                        {index + 1}
                      </div>

                      {item.part_name && (
                        <Text strong style={{ fontSize: 14, color: token.colorText, flexShrink: 0 }}>
                          {item.part_name}
                        </Text>
                      )}

                      {(item.part_code || item.record_name) && (
                        <Text
                          style={{
                            fontSize: 13,
                            color: token.colorTextSecondary,
                            flexShrink: 0,
                            fontFamily: 'monospace',
                          }}
                        >
                          ({item.part_code || item.record_name})
                        </Text>
                      )}

                      <div
                        style={{
                          width: 1,
                          height: 14,
                          background: token.colorBorderSecondary,
                          flexShrink: 0,
                          margin: '0 2px',
                        }}
                      />

                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            padding: '2px 8px',
                            borderRadius: 4,
                            background: token.colorErrorBg,
                            border: `1px solid ${token.colorErrorBorder}`,
                            color: token.colorErrorText,
                            fontSize: 12,
                            fontWeight: 500,
                            lineHeight: '18px',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {item.reason || 'NC识别失败'}
                        </div>
                      </div>
                    </div>
                  ))}
                </Space>
              )}
            </Space>
          </div>

          <div
            style={{
              padding: '12px',
              background: token.colorInfoBg,
              borderRadius: token.borderRadius,
              border: `1px solid ${token.colorInfoBorder}`,
            }}
          >
            <Text style={{ fontSize: 13, color: token.colorInfoText }}>
              {helperText}
            </Text>
          </div>
        </Space>
      </Card>
    </>
  )
}

export default MissingFieldsCard

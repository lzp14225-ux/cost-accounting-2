import React from 'react'
import { Card, Typography, Space, theme, Divider } from 'antd'
import { ExclamationCircleOutlined } from '@ant-design/icons'

const { Text } = Typography

interface MissingField {
  table: string
  record_id: string
  record_name: string
  part_code?: string  // 新增：零件编号
  part_name?: string  // 新增：零件名称
  missing: Record<string, string>  // 字段名 -> 中文描述
  current_values: Record<string, any>
}

interface MissingFieldsCardProps {
  message: string
  summary?: string
  missingFields: MissingField[]
}

// 自定义滚动条样式
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
`;

const MissingFieldsCard: React.FC<MissingFieldsCardProps> = ({
  message,
  summary,
  missingFields,
}) => {
  const { token } = theme.useToken()

  return (
    <>
      {/* 注入自定义滚动条样式 */}
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
        {/* 标题和主要消息 */}
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
              {message}
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

        {/* 缺失字段列表 */}
        <div
          style={{
            maxHeight: '360px',
            overflowY: 'auto',
            overflowX: 'hidden',
            paddingRight: '4px',
          }}
          className="missing-fields-list"
        >
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
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
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = token.colorPrimaryBorder
                  e.currentTarget.style.boxShadow = `0 2px 8px ${token.colorPrimary}15`
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = token.colorBorder
                  e.currentTarget.style.boxShadow = 'none'
                }}
              >
                {/* 序号 */}
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

                {/* 零件名称 */}
                {field.part_name && (
                  <Text 
                    strong 
                    style={{ 
                      fontSize: 14, 
                      color: token.colorText, 
                      flexShrink: 0,
                    }}
                  >
                    {field.part_name}
                  </Text>
                )}

                {/* 零件编号 */}
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

                {/* 分隔符 */}
                <div style={{ 
                  width: 1, 
                  height: 14, 
                  background: token.colorBorderSecondary,
                  flexShrink: 0,
                  margin: '0 2px',
                }} />

                {/* 缺失字段标签 */}
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
        </div>

        {/* 操作提示 */}
        <div 
          style={{ 
            padding: '12px',
            background: token.colorInfoBg,
            borderRadius: token.borderRadius,
            border: `1px solid ${token.colorInfoBorder}`,
          }}
        >
          <Text style={{ fontSize: 13, color: token.colorInfoText }}>
            💡 请在下方输入框中补充缺失的字段信息，例如："将零件 LP-02 的材质设为 Cr12mov"
          </Text>
        </div>
      </Space>
    </Card>
    </>
  )
}

export default MissingFieldsCard

// 图纸相关工具函数

/**
 * 从消息内容中提取图纸文件路径
 */
export function extractDrawingPaths(content: string): Array<{
  filePath: string
  partName?: string
}> {
  const drawings: Array<{ filePath: string; partName?: string }> = []
  
  // 匹配 DXF 文件路径的正则表达式
  // 支持格式：dxf/2026/01/xxx/filename.dxf
  const dxfPathRegex = /dxf\/\d{4}\/\d{2}\/[a-f0-9-]+\/[^\/\s]+\.dxf/gi
  
  const matches = content.match(dxfPathRegex)
  if (matches) {
    matches.forEach(filePath => {
      // 尝试从文件名提取零件名称
      const fileName = filePath.split('/').pop()
      const partName = fileName ? fileName.replace('.dxf', '') : undefined
      
      drawings.push({
        filePath,
        partName
      })
    })
  }
  
  return drawings
}

/**
 * 检查消息是否包含图纸信息
 */
export function hasDrawingContent(content: string): boolean {
  return extractDrawingPaths(content).length > 0
}

/**
 * 从ReviewDataList数据中提取图纸信息
 */
export function extractDrawingsFromReviewData(data: any[]): Array<{
  filePath: string
  partName: string
  partCode: string
}> {
  if (!Array.isArray(data)) return []
  
  return data
    .filter(item => item.subgraph_file_url)
    .map(item => ({
      filePath: item.subgraph_file_url,
      partName: item.part_name || '未知零件',
      partCode: item.part_code || ''
    }))
}
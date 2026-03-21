// 测试工具函数

/**
 * 检查数组中是否有重复的ID
 */
export const checkDuplicateIds = <T extends { id: string }>(items: T[]): string[] => {
  const ids = items.map(item => item.id)
  const duplicates: string[] = []
  const seen = new Set<string>()
  
  for (const id of ids) {
    if (seen.has(id)) {
      if (!duplicates.includes(id)) {
        duplicates.push(id)
      }
    } else {
      seen.add(id)
    }
  }
  
  return duplicates
}

/**
 * 生成唯一ID
 */
export const generateUniqueId = (prefix: string = ''): string => {
  const timestamp = Date.now().toString(36)
  const random = Math.random().toString(36).substr(2, 9)
  return `${prefix}${timestamp}_${random}`
}

/**
 * 验证React key的唯一性
 */
export const validateReactKeys = (keys: string[]): boolean => {
  const uniqueKeys = new Set(keys)
  return uniqueKeys.size === keys.length
}

/**
 * 调试用：打印重复的keys
 */
export const logDuplicateKeys = (keys: string[], context: string = ''): void => {
  const duplicates = keys.filter((key, index) => keys.indexOf(key) !== index)
  if (duplicates.length > 0) {
    console.warn(`发现重复的React keys ${context}:`, duplicates)
  }
}